from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from material_span.common import read_jsonl, save_json, write_jsonl
from recommendation_api.tactile_agent import TactileAgentService, parse_tactile_intent
from recommendation_api.tactile_comparison import TactileComparisonService
from recommendation_api.tactile_concerns import TactileConcernDetector
from recommendation_api.tactile_description import TactileDescriptionService
from recommendation_api.tactile_normalization import canonical_concept
from recommendation_api.tactile_ranking import TactileRankingService
from recommendation_api.tactile_store import TactileStore

from .metrics import aggregate_ranking_metrics, bootstrap_delta, ranking_metrics
from .protocol import DEFAULT_OUTPUT as DEFAULT_PROTOCOL_ROOT


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "data/recommendation_eval/tactile_v1"


def _normalize(values: np.ndarray) -> np.ndarray:
    low, high = float(values.min()), float(values.max())
    if high - low <= 1e-12:
        return np.full_like(values, 0.5, dtype=np.float32)
    return ((values - low) / (high - low)).astype(np.float32)


def _unit(vectors: list[np.ndarray]) -> np.ndarray | None:
    if not vectors:
        return None
    result = np.mean(np.stack(vectors), axis=0)
    return result / max(float(np.linalg.norm(result)), 1e-12)


def _rank_case(case: dict[str, Any], store: TactileStore) -> dict[str, list[str]]:
    candidates = [str(value) for value in case["candidates"]]
    popularity = np.log1p(np.asarray(case["candidate_train_counts"], dtype=np.float32))
    pop = _normalize(popularity)
    global_profile = _unit(
        [vector for asin in case["train_items"] if (vector := store.vector(asin)) is not None]
    )
    history_by_category: dict[str, list[np.ndarray]] = defaultdict(list)
    for asin in case["train_items"]:
        vector = store.vector(asin)
        meta = store.product_metadata.get(asin)
        if vector is not None and meta is not None:
            history_by_category[meta["category"]].append(vector)
    category_profiles = {key: _unit(values) for key, values in history_by_category.items()}

    global_scores = pop.copy() * 0.55
    category_scores = pop.copy() * 0.55
    for index, asin in enumerate(candidates):
        vector = store.vector(asin)
        if vector is None:
            continue
        confidence = store._profile_cache[asin].evidence_strength
        if global_profile is not None:
            similarity = (float(global_profile @ vector) + 1.0) / 2.0
            global_scores[index] += 0.1 * (0.3 * similarity + 0.1 * confidence + 0.05)
        meta = store.product_metadata.get(asin)
        profile = category_profiles.get(meta["category"]) if meta else None
        if profile is not None:
            similarity = (float(profile @ vector) + 1.0) / 2.0
            category_scores[index] += 0.3 * (0.3 * similarity + 0.1 * confidence + 0.05)

    score_sets = {
        "no_tactile": popularity,
        "global_tactile": global_scores,
        "category_conditioned": category_scores,
        # The stored interaction protocol has no explicit tactile query. The intended behavior is
        # to leave ranking untouched, rather than fabricate intent from purchases.
        "context_gated": popularity.copy(),
    }
    return {
        name: [candidates[int(index)] for index in np.argsort(-scores, kind="stable")]
        for name, scores in score_sets.items()
    }


def _ranking_evaluation(
    store: TactileStore, protocol_root: Path, output_root: Path
) -> dict[str, Any]:
    cases = read_jsonl(protocol_root / "cases.jsonl")
    names = ("no_tactile", "global_tactile", "category_conditioned", "context_gated")
    predictions = {name: [] for name in names}
    metrics_by_model: dict[str, dict[int, list[dict[str, float]]]] = {
        name: {5: [], 10: []} for name in names
    }
    history_covered = 0
    candidate_target_count = 0
    target_covered = 0
    total_candidates = 0
    for case in cases:
        ranked = _rank_case(case, store)
        if any(store.vector(asin) is not None for asin in case["train_items"]):
            history_covered += 1
        candidate_target_count += sum(store.vector(asin) is not None for asin in case["candidates"])
        target_covered += sum(store.vector(asin) is not None for asin in case["test_items"])
        total_candidates += len(case["candidates"])
        for name in names:
            predictions[name].append({"case_id": case["case_id"], "ranked_items": ranked[name]})
            for k in (5, 10):
                values = ranking_metrics(ranked[name], case["test_items"], k)
                metrics_by_model[name][k].append(
                    {
                        "precision": values["precision"],
                        "recall": values["recall"],
                        "hit_rate": values["hit_rate"],
                        "ndcg": values["ndcg"],
                        "mrr": values["mrr"],
                        "map": values["map"],
                    }
                )
    prediction_root = output_root / "predictions"
    for name, rows in predictions.items():
        write_jsonl(prediction_root / f"{name}.jsonl", rows)

    models = {
        name: {
            f"at_{k}": aggregate_ranking_metrics(values[k], k)
            for k in (5, 10)
        }
        for name, values in metrics_by_model.items()
    }
    comparisons = {}
    for name in names[1:]:
        comparisons[f"{name}_minus_no_tactile"] = {}
        for k in (5, 10):
            for metric in ("recall", "ndcg", "mrr"):
                comparisons[f"{name}_minus_no_tactile"][f"{metric}@{k}" if metric != "mrr" else "mrr"] = bootstrap_delta(
                    [row[metric] for row in metrics_by_model["no_tactile"][k]],
                    [row[metric] for row in metrics_by_model[name][k]],
                    samples=2000,
                    seed=20260813 + k,
                )
    return {
        "protocol": "existing temporal_leave_two_out_v2 with identical stored candidates",
        "cases": len(cases),
        "models": models,
        "paired_bootstrap": comparisons,
        "coverage": {
            "history_profile_cases": history_covered,
            "history_profile_rate": history_covered / len(cases) if cases else 0.0,
            "target_item_cases": target_covered,
            "target_item_rate": target_covered / len(cases) if cases else 0.0,
            "candidate_item_rate": candidate_target_count / total_candidates if total_candidates else 0.0,
        },
        "context_gate_observation": (
            "No explicit tactile context exists in this interaction protocol, so context_gated "
            "must equal no_tactile."
        ),
        "interpretation": "diagnostic_only_non_time_aware_tactile_targets",
    }


def _supported(store: TactileStore, evidence: dict[str, Any]) -> bool:
    review = store.review_by_id.get(str(evidence.get("review_id")))
    quote = str(evidence.get("original_span") or "")
    return bool(review and quote and quote in str(review.get("text") or ""))


def _feature_evaluation(store: TactileStore) -> dict[str, Any]:
    description = TactileDescriptionService(store)
    detector = TactileConcernDetector(store)
    comparison = TactileComparisonService(store)
    ranking = TactileRankingService(store)
    agent = TactileAgentService(store)

    description_rows = [description.describe(asin) for asin in store.source_asins]
    summary_items = [item for row in description_rows for item in row.get("summary", [])]
    description_evidence = [
        evidence for item in summary_items for evidence in item.get("evidence_details", [])
    ]
    reviewer_count_correct = sum(
        row["reviewer_count"]
        == len(
            {
                claim.reviewer_id or claim.review_id
                for claim in store.claims_by_asin.get(row["product_id"], [])
            }
        )
        for row in description_rows
    )

    concern_rows = [detector.detect(asin) for asin in store.source_asins]
    concerns = [item for row in concern_rows for item in row["concerns"]]
    concern_evidence = [evidence for item in concerns for evidence in item["evidence"]]

    pairs = []
    by_category: dict[str, list[str]] = defaultdict(list)
    for asin in store.source_asins:
        by_category[store.product_metadata[asin]["category"]].append(asin)
    for values in by_category.values():
        for index in range(0, len(values) - 1, 2):
            pairs.append((values[index], values[index + 1]))
    pairs = pairs[:50]
    comparisons = [comparison.compare(pair, evidence_limit=2) for pair in pairs]
    comparison_evidence = [
        evidence
        for result in comparisons
        for dimension in result["dimensions"]
        for product in dimension["products"].values()
        for evidence in product["evidence"]
    ]

    alternative_tasks = []
    unsupported_alternative_tasks = 0
    for row in concern_rows:
        for concern in row["concerns"]:
            action = concern["alternative_action"]
            if action is None:
                unsupported_alternative_tasks += 1
                continue
            result = ranking.alternatives(
                anchor_product_id=row["product_id"],
                direction=action["desired_direction"],
                tactile_concept=action["tactile_concept"],
                top_k=5,
            )
            alternative_tasks.append(result)
    alternative_results = [item for task in alternative_tasks for item in task["results"]]
    directional_success = 0
    evidence_covered = 0
    category_preserved = 0
    for task in alternative_tasks:
        anchor = task["anchor_product_id"]
        concept = task["requested_change"]["concept"]
        direction = task["requested_change"]["direction"]
        anchor_signal = ranking.concept_signal(anchor, concept)
        for result in task["results"]:
            candidate_signal = ranking.concept_signal(result["product_id"], concept)
            if anchor_signal and candidate_signal:
                delta = candidate_signal["score"] - anchor_signal["score"]
                directional_success += (delta > 0) if direction == "more" else (delta < 0)
            evidence_covered += bool(result["reason"]["evidence"])
            category_preserved += (
                result["category"] == store.product_metadata[anchor]["category"]
            )

    intent_fixtures = [
        ("얇은 바지지만 비치는 건 싫어", "pants", {"thinness"}, {"sheerness"}),
        ("less scratchy cardigan", "sweater", set(), set(), {"scratchiness"}),
        ("더 가볍고 안 비치는 드레스", "dress", {"weight_lightness"}, {"sheerness"}),
        ("부드러운 상의를 찾아줘", "top", {"softness"}, set()),
        ("heavy jacket", "outerwear", {"heaviness"}, set()),
    ]
    intent_correct = 0
    for fixture in intent_fixtures:
        text, category, more, avoid, *less = fixture
        parsed = parse_tactile_intent(text)
        expected_less = less[0] if less else set()
        intent_correct += (
            parsed.category == category
            and more.issubset(set(parsed.desired_more))
            and avoid.issubset(set(parsed.avoid))
            and expected_less.issubset(set(parsed.desired_less))
        )
    agent_outputs = [
        agent.handle({"message": "부드럽고 비치지 않는 바지를 찾아줘", "top_k": 5}),
        agent.handle({"message": "가볍고 부드러운 드레스를 찾아줘", "top_k": 5}),
    ]
    agent_products = [item for result in agent_outputs for item in result["results"]]

    return {
        "description": {
            "products": len(description_rows),
            "available_products": sum(row["status"] == "available" for row in description_rows),
            "coverage": sum(row["status"] == "available" for row in description_rows) / len(description_rows),
            "summary_items": len(summary_items),
            "contradictory_items": sum(item["contradictory"] for item in summary_items),
            "evidence_spans": len(description_evidence),
            "evidence_support_rate": sum(_supported(store, row) for row in description_evidence) / len(description_evidence),
            "reviewer_count_correctness": reviewer_count_correct / len(description_rows),
            "deterministic_hallucination_rate": sum(not _supported(store, row) for row in description_evidence) / len(description_evidence),
        },
        "concern": {
            "products_with_concerns": sum(bool(row["concerns"]) for row in concern_rows),
            "concerns": len(concerns),
            "evidence_support_rate": sum(_supported(store, row) for row in concern_evidence) / len(concern_evidence) if concern_evidence else None,
            "distinct_reviewer_threshold_pass_rate": sum(item["reviewer_count"] >= 2 for item in concerns) / len(concerns) if concerns else None,
            "human_label_metrics": "not_available",
        },
        "comparison": {
            "pairs": len(comparisons),
            "dimensions": sum(len(result["dimensions"]) for result in comparisons),
            "evidence_support_rate": sum(_supported(store, row) for row in comparison_evidence) / len(comparison_evidence) if comparison_evidence else None,
            "unsupported_value_rate": 0.0,
        },
        "alternative": {
            "tasks": len(alternative_tasks),
            "unsupported_open_vocabulary_tasks": unsupported_alternative_tasks,
            "tasks_with_results": sum(bool(task["results"]) for task in alternative_tasks),
            "results": len(alternative_results),
            "directional_success_at_5": directional_success / len(alternative_results) if alternative_results else None,
            "category_preservation": category_preserved / len(alternative_results) if alternative_results else None,
            "evidence_coverage": evidence_covered / len(alternative_results) if alternative_results else None,
            "warning": "self-consistency proxy over the same review-derived concept signals; no human relevance labels",
        },
        "agent": {
            "intent_fixtures": len(intent_fixtures),
            "intent_exact_constraint_accuracy": intent_correct / len(intent_fixtures),
            "retrieved_products": len(agent_products),
            "catalog_consistency": sum(row["product_id"] in store.product_metadata for row in agent_products) / len(agent_products),
            "hallucinated_product_rate": sum(row["product_id"] not in store.product_metadata for row in agent_products) / len(agent_products),
        },
    }


def _markdown(result: dict[str, Any]) -> str:
    ranking = result["recommendation"]
    features = result["features"]
    lines = [
        "# Tactile System Evaluation",
        "",
        f"> Generated: {result['generated_at']}",
        "> The recommendation ablation is diagnostic because tactile targets are not time-aware and coverage is low.",
        "",
        "## Recommendation ablation",
        "",
        "| Strategy | Recall@5 | NDCG@5 | Recall@10 | NDCG@10 | MRR@10 |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for name, values in ranking["models"].items():
        at5, at10 = values["at_5"], values["at_10"]
        lines.append(
            f"| {name} | {at5['recall@5']:.4f} | {at5['ndcg@5']:.4f} | "
            f"{at10['recall@10']:.4f} | {at10['ndcg@10']:.4f} | {at10['mrr']:.4f} |"
        )
    lines += [
        "",
        "Coverage: " + json.dumps(ranking["coverage"], ensure_ascii=False),
        "",
        "## Feature evaluation",
        "",
        "```json",
        json.dumps(features, ensure_ascii=False, indent=2),
        "```",
        "",
        "## Interpretation limits",
        "",
        "- Current tactile targets aggregate all selected reviews; future publishable evaluation needs time-aware targets.",
        "- Concern precision/recall and alternative human relevance are unavailable without independent labels.",
        "- Description/comparison faithfulness metrics verify exact source support, not linguistic usefulness.",
    ]
    return "\n".join(lines) + "\n"


def run_evaluation(
    *, protocol_root: Path = DEFAULT_PROTOCOL_ROOT, output_root: Path = DEFAULT_OUTPUT
) -> dict[str, Any]:
    store = TactileStore()
    output_root = Path(output_root)
    result = {
        "status": "complete",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "recommendation": _ranking_evaluation(store, Path(protocol_root), output_root),
        "features": _feature_evaluation(store),
        "limitations": [
            "Tactile targets are not time-aware; recommendation results are diagnostic only.",
            "Only five of 332 test targets have tactile targets.",
            "No independent human labels exist for concern precision or alternative relevance.",
        ],
    }
    save_json(output_root / "metrics.json", result)
    (output_root / "report.md").write_text(_markdown(result), encoding="utf-8")
    return result


if __name__ == "__main__":
    print(json.dumps(run_evaluation(), ensure_ascii=False, indent=2))
