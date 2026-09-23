from __future__ import annotations

import hashlib
import itertools
import math
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np

from .common import (
    PATHS, axis_map, load_experiment, load_taxonomy, read_json, sha256_file,
    utc_now, write_json, write_jsonl,
)
from .modeling import _load_matrices


def constraint_relevance(value: float, direction: int, strength: float, maximum: float) -> float:
    return float(maximum * np.clip(direction * value / max(strength, 1e-12), 0.0, 1.0))


def query_relevance(
    target_values: np.ndarray,
    constraints: list[dict[str, Any]],
    maximum: float,
) -> np.ndarray:
    parts = [
        np.asarray(
            [constraint_relevance(value, int(item["direction_sign"]), float(item["strength"]), maximum) for value in target_values[:, int(item["axis_number"])]],
            dtype=np.float32,
        )
        for item in constraints
    ]
    return np.min(np.stack(parts, axis=1), axis=1)


def ranking_metrics(relevance: np.ndarray, score: np.ndarray, cutoffs: list[int]) -> dict[str, Any]:
    if not len(relevance):
        return {"candidates": 0, "pairwise_accuracy": None, **{f"ndcg@{k}": None for k in cutoffs}, **{f"recall@{k}": None for k in cutoffs}}
    order = np.argsort(-score, kind="stable")
    ideal = np.argsort(-relevance, kind="stable")
    output: dict[str, Any] = {"candidates": int(len(relevance))}
    relevant_total = int(np.sum(relevance > 0))
    for k in cutoffs:
        actual_values = relevance[order[:k]]
        ideal_values = relevance[ideal[:k]]
        discounts = np.log2(np.arange(2, len(actual_values) + 2))
        dcg = float(np.sum((np.power(2.0, actual_values) - 1.0) / discounts))
        ideal_discounts = np.log2(np.arange(2, len(ideal_values) + 2))
        idcg = float(np.sum((np.power(2.0, ideal_values) - 1.0) / ideal_discounts))
        output[f"ndcg@{k}"] = dcg / idcg if idcg > 0 else None
        output[f"recall@{k}"] = float(np.sum(relevance[order[:k]] > 0) / relevant_total) if relevant_total else None
    correct, comparisons = 0, 0
    for left, right in itertools.combinations(range(len(relevance)), 2):
        delta = float(relevance[left] - relevance[right])
        if abs(delta) <= 1e-12:
            continue
        correct += int(np.sign(score[left] - score[right]) == np.sign(delta))
        comparisons += 1
    output["pairwise_accuracy"] = correct / comparisons if comparisons else None
    output["pairwise_comparisons"] = comparisons
    return output


def _query_id(payload: str) -> str:
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def generate_queries(data: dict[str, Any], config: dict[str, Any]) -> list[dict[str, Any]]:
    retrieval = config["retrieval"]
    taxonomy = axis_map(load_taxonomy())
    split = read_json(PATHS.manifests / f"family_split_{config['experiment']['seed']}.json")["splits"]
    product_index = {value: index for index, value in enumerate(data["product_ids"])}
    test = np.asarray([product_index[value] for value in split["test"]], dtype=int)
    minimum_support = int(retrieval["minimum_test_support"])
    minimum_candidates = int(retrieval["minimum_candidates"])
    minimum_relevant = int(retrieval["minimum_relevant"])
    maximum = float(retrieval["maximum_relevance"])
    queries = []
    for category in sorted(set(data["categories"][test].tolist())):
        category_indices = test[data["categories"][test] == category]
        eligible_by_axis = {
            axis_number: category_indices[
                data["mask"][category_indices, axis_number]
                & (data["support"][category_indices, axis_number] >= minimum_support)
            ]
            for axis_number in range(len(data["axis_ids"]))
        }
        for axis_number, axis_id in enumerate(data["axis_ids"]):
            candidates = eligible_by_axis[axis_number]
            if len(candidates) < minimum_candidates:
                continue
            axis = taxonomy[str(axis_id)]
            for sign, pole in ((-1, axis["negative_pole"]), (1, axis["positive_pole"])):
                for strength in retrieval["query_strengths"]:
                    constraint = {
                        "axis_id": str(axis_id), "axis_number": axis_number,
                        "direction_sign": sign, "pole": str(pole), "strength": float(strength),
                    }
                    relevance = query_relevance(data["values"][candidates], [constraint], maximum)
                    if int(np.sum(relevance > 0)) < minimum_relevant:
                        continue
                    signature = f"single|{category}|{axis_id}|{sign}|{strength}"
                    queries.append(
                        {
                            "query_id": _query_id(signature), "partition": "single_axis",
                            "category": str(category), "constraints": [constraint],
                            "candidate_indices": candidates.tolist(),
                        }
                    )
        if int(retrieval["multi_axis_max_constraints"]) >= 2:
            for left, right in itertools.combinations(range(len(data["axis_ids"])), 2):
                candidates = np.intersect1d(eligible_by_axis[left], eligible_by_axis[right])
                if len(candidates) < minimum_candidates:
                    continue
                axes = [taxonomy[str(data["axis_ids"][left])], taxonomy[str(data["axis_ids"][right])]]
                for left_sign, right_sign in itertools.product((-1, 1), repeat=2):
                    constraints = []
                    for axis_number, axis, sign in ((left, axes[0], left_sign), (right, axes[1], right_sign)):
                        constraints.append(
                            {
                                "axis_id": str(data["axis_ids"][axis_number]), "axis_number": axis_number,
                                "direction_sign": sign,
                                "pole": str(axis["negative_pole"] if sign < 0 else axis["positive_pole"]),
                                "strength": 1.0,
                            }
                        )
                    relevance = query_relevance(data["values"][candidates], constraints, maximum)
                    if int(np.sum(relevance > 0)) < minimum_relevant:
                        continue
                    signature = "multi|" + str(category) + "|" + "|".join(
                        f"{item['axis_id']}:{item['direction_sign']}" for item in constraints
                    )
                    queries.append(
                        {
                            "query_id": _query_id(signature), "partition": "multi_axis",
                            "category": str(category), "constraints": constraints,
                            "candidate_indices": candidates.tolist(),
                        }
                    )
    return queries


def _render_query(query: dict[str, Any], template: str) -> str:
    phrases = [template.format(pole=item["pole"]) for item in query["constraints"]]
    return " and ".join(phrases)


def _fashionclip_text(prompts: list[str]) -> np.ndarray:
    import torch
    from transformers import AutoProcessor, CLIPModel

    encoder = load_experiment()["image_encoders"]["fashionclip"]
    model_id = str(encoder["model_id"])
    revision = str(encoder["revision"])
    processor = AutoProcessor.from_pretrained(model_id, revision=revision, local_files_only=True)
    model = CLIPModel.from_pretrained(model_id, revision=revision, local_files_only=True).eval()
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model.to(device)
    rows = []
    for start in range(0, len(prompts), 64):
        inputs = {key: value.to(device) for key, value in processor(text=prompts[start:start + 64], padding=True, return_tensors="pt").items()}
        with torch.inference_mode():
            output = model.get_text_features(**inputs)
            features = output if isinstance(output, torch.Tensor) else output.pooler_output
        rows.append(features.float().cpu().numpy())
    matrix = np.concatenate(rows, axis=0).astype(np.float32)
    return matrix / np.clip(np.linalg.norm(matrix, axis=1, keepdims=True), 1e-12, None)


def _open_text(prompts: list[str]) -> np.ndarray:
    from sentence_transformers import SentenceTransformer

    encoder = load_experiment()["open_vector_baseline"]["text_encoder"]
    model = SentenceTransformer(
        str(encoder["model_id"]), revision=str(encoder["revision"]),
        local_files_only=True, device="cpu",
    )
    return model.encode(prompts, batch_size=64, show_progress_bar=False, normalize_embeddings=True).astype(np.float32)


def _structured_score(
    prediction: np.ndarray,
    decisions: np.ndarray | None,
    constraints: list[dict[str, Any]],
    unknown_penalty: float,
    coverage_aware: bool = False,
) -> np.ndarray:
    contributions, supported = [], []
    for item in constraints:
        axis_number = int(item["axis_number"])
        values = np.clip(
            int(item["direction_sign"]) * prediction[:, axis_number] / max(float(item["strength"]), 1e-12),
            -1.0, 1.0,
        )
        if decisions is None:
            known = np.ones(len(values), dtype=bool)
        else:
            known = decisions[:, axis_number].astype(bool)
        contributions.append(np.where(known, values, unknown_penalty))
        supported.append(known.astype(float))
    score = np.mean(np.stack(contributions, axis=1), axis=1)
    if coverage_aware:
        coverage = np.mean(np.stack(supported, axis=1), axis=1)
        score = score * coverage - (1.0 - coverage) * abs(unknown_penalty)
    return score.astype(np.float32)


def _mean_metrics(rows: list[dict[str, Any]], cutoffs: list[int]) -> dict[str, Any]:
    keys = [f"ndcg@{k}" for k in cutoffs] + [f"recall@{k}" for k in cutoffs] + ["pairwise_accuracy"]
    output = {"queries": len(rows)}
    for key in keys:
        values = [float(row[key]) for row in rows if row.get(key) is not None]
        output[key] = float(np.mean(values)) if values else None
    return output


def run_coldstart_retrieval() -> dict[str, Any]:
    config = load_experiment()
    retrieval = config["retrieval"]
    data = _load_matrices()
    with np.load(PATHS.artifacts / "selective_predictions.npz", allow_pickle=False) as arrays:
        selective_ids = np.asarray(arrays["product_ids"]).astype(str)
        selective_axes = np.asarray(arrays["axis_ids"]).astype(str)
        prediction = np.asarray(arrays["prediction"], dtype=np.float32)
        decisions = {
            key: np.asarray(arrays[f"decision_{key}"], dtype=bool)
            for key in ("confidence_only", "recoverability_only", "product", "learned_calibrator")
        }
    if not np.array_equal(selective_ids, data["product_ids"]) or not np.array_equal(selective_axes, data["axis_ids"]):
        raise RuntimeError("Selective prediction matrices do not align with target matrices")
    queries = generate_queries(data, config)
    if not queries:
        raise RuntimeError("No retrieval queries satisfy the data-driven support criteria")
    query_export = []
    prompts = [_render_query(query, str(retrieval["fashionclip_query_template"])) for query in queries]
    fashion_text = _fashionclip_text(prompts)
    open_text = _open_text(prompts)
    with np.load(Path(config["inputs"]["fashionclip_embeddings"]), allow_pickle=False) as arrays:
        image_ids = np.asarray(arrays["asins"]).astype(str)
        image_vectors = np.asarray(arrays["image"], dtype=np.float32)
    image_lookup = {value: image_vectors[index] for index, value in enumerate(image_ids)}
    aligned_image = np.stack([image_lookup[value] for value in data["product_ids"]])
    open_path = PATHS.artifacts / "open_384d_predictions.npz"
    open_lookup = {}
    if open_path.is_file():
        with np.load(open_path, allow_pickle=False) as arrays:
            open_ids = np.asarray(arrays["product_ids"]).astype(str)
            open_predictions = np.asarray(arrays["prediction"], dtype=np.float32)
        open_lookup = {value: open_predictions[index] for index, value in enumerate(open_ids)}
    vlm_prediction = None
    vlm_mask = None
    vlm_path = PATHS.artifacts / "qwen_vlm_zero_shot.npz"
    if vlm_path.is_file():
        with np.load(vlm_path, allow_pickle=False) as arrays:
            vlm_ids = np.asarray(arrays["product_ids"]).astype(str)
            vlm_axes = np.asarray(arrays["axis_ids"]).astype(str)
            candidate_prediction = np.asarray(arrays["prediction"], dtype=np.float32)
            candidate_mask = np.asarray(arrays["visual_mask"], dtype=bool)
        if np.array_equal(vlm_ids, data["product_ids"]) and np.array_equal(vlm_axes, data["axis_ids"]):
            vlm_prediction, vlm_mask = candidate_prediction, candidate_mask
    cutoffs = [int(value) for value in retrieval["k"]]
    maximum = float(retrieval["maximum_relevance"])
    seed = int(retrieval["random_seed"])
    unknown_neutral = float(retrieval["unknown_penalties"][0])
    unknown_mild = float(retrieval["unknown_penalties"][-1])
    per_method: dict[str, list[dict[str, Any]]] = defaultdict(list)
    per_query_rows = []
    for query_number, query in enumerate(queries):
        candidates = np.asarray(query["candidate_indices"], dtype=int)
        relevance = query_relevance(data["values"][candidates], query["constraints"], maximum)
        random_scores = np.asarray(
            [int(hashlib.sha256(f"{seed}:{query['query_id']}:{data['product_ids'][value]}".encode()).hexdigest()[:16], 16) / 16**16 for value in candidates],
            dtype=np.float64,
        )
        score_map = {
            "random": random_scores,
            "category_only": np.zeros(len(candidates), dtype=np.float32),
            "fashionclip_taxonomy_zero_shot": aligned_image[candidates] @ fashion_text[query_number],
            "structured_no_abstention": _structured_score(prediction[candidates], None, query["constraints"], 0.0),
            "confidence_selective_u0": _structured_score(prediction[candidates], decisions["confidence_only"][candidates], query["constraints"], unknown_neutral),
            "recoverability_selective_u0": _structured_score(prediction[candidates], decisions["recoverability_only"][candidates], query["constraints"], unknown_neutral),
            "product_selective_u0": _structured_score(prediction[candidates], decisions["product"][candidates], query["constraints"], unknown_neutral),
            "proposed_calibrator_u0": _structured_score(prediction[candidates], decisions["learned_calibrator"][candidates], query["constraints"], unknown_neutral),
            "proposed_calibrator_u1": _structured_score(prediction[candidates], decisions["learned_calibrator"][candidates], query["constraints"], unknown_mild),
            "proposed_unknown_coverage_u2": _structured_score(prediction[candidates], decisions["learned_calibrator"][candidates], query["constraints"], unknown_mild, coverage_aware=True),
        }
        if open_lookup and all(data["product_ids"][value] in open_lookup for value in candidates):
            score_map["open_384d_current_split"] = np.stack([open_lookup[data["product_ids"][value]] for value in candidates]) @ open_text[query_number]
        if vlm_prediction is not None and vlm_mask is not None:
            score_map["qwen_vlm_zero_shot_u0"] = _structured_score(
                vlm_prediction[candidates], vlm_mask[candidates], query["constraints"], unknown_neutral
            )
        for method, scores in score_map.items():
            metrics = ranking_metrics(relevance, np.asarray(scores), cutoffs)
            row = {
                "query_id": query["query_id"], "partition": query["partition"],
                "category": query["category"], "method": method, **metrics,
            }
            per_method[method].append(row)
            per_query_rows.append(row)
        query_export.append(
            {
                "query_id": query["query_id"], "partition": query["partition"],
                "category": query["category"],
                "constraints": [{key: value for key, value in item.items() if key != "axis_number"} for item in query["constraints"]],
                "rendered_interface_text": prompts[query_number],
                "candidate_product_ids": data["product_ids"][candidates].tolist(),
                "relevance": relevance.tolist(),
                "ground_truth_source": "held-out buyer-review pseudo-target; not physical touch ground truth",
            }
        )
    method_summary = {}
    for method, rows in per_method.items():
        method_summary[method] = {
            "overall": _mean_metrics(rows, cutoffs),
            "cold_start": _mean_metrics(rows, cutoffs),
            "same_category": _mean_metrics(rows, cutoffs),
            "single_axis": _mean_metrics([row for row in rows if row["partition"] == "single_axis"], cutoffs),
            "multi_axis": _mean_metrics([row for row in rows if row["partition"] == "multi_axis"], cutoffs),
        }
    query_path = PATHS.artifacts / "coldstart_retrieval_queries.jsonl"
    row_path = PATHS.artifacts / "coldstart_retrieval_per_query.jsonl"
    results_path = PATHS.artifacts / "phase10_retrieval_results.json"
    write_jsonl(query_path, query_export)
    write_jsonl(row_path, per_query_rows)
    unavailable = {
        "popularity": "No leakage-safe pre-split popularity field was available.",
        "naive_image_review_fusion": "Not applicable to the cold-start-only candidate protocol; no candidate review is available at inference.",
    }
    if vlm_prediction is None:
        unavailable["qwen_vlm_zero_shot"] = "No aligned image-only Qwen VLM cache was available."
    results = {
        "status": "complete", "phase": 10, "generated_at": utc_now(),
        "protocol": "review-cold-start, family-held-out, same-category candidates, hidden test-review relevance",
        "queries": len(queries),
        "query_partitions": {
            "single_axis": sum(row["partition"] == "single_axis" for row in queries),
            "multi_axis": sum(row["partition"] == "multi_axis" for row in queries),
        },
        "methods": method_summary,
        "unavailable_baselines": unavailable,
        "limitations": [
            "Held-out buyer-review relevance is selective subjective evidence, not physical tactile ground truth.",
            "Candidate-axis pairs without held-out support are excluded rather than treated as neutral.",
            "All quantitative queries are generated from test support and taxonomy configuration; interface text does not define ground truth.",
        ],
    }
    write_json(results_path, results)
    manifest = {
        "status": "complete", "phase": 10, "generated_at": utc_now(),
        "queries": len(queries), "query_partitions": results["query_partitions"],
        "outputs": {
            "results": str(results_path), "results_sha256": sha256_file(results_path),
            "queries": str(query_path), "queries_sha256": sha256_file(query_path),
            "per_query": str(row_path), "per_query_sha256": sha256_file(row_path),
        },
    }
    write_json(PATHS.manifests / "phase10_retrieval.json", manifest)
    _write_report(results, cutoffs)
    return manifest


def _write_report(results: dict[str, Any], cutoffs: list[int]) -> None:
    primary = 10 if 10 in cutoffs else cutoffs[0]
    lines = [
        "# Phase 10 — Review-Cold-Start Tactile Retrieval", "",
        f"Data-generated queries: {results['queries']} (single={results['query_partitions']['single_axis']}, multi={results['query_partitions']['multi_axis']}). All candidates are held-out test families from the same category.", "",
        f"| Method | NDCG@{primary} | Recall@{primary} | Pairwise |", "|---|---:|---:|---:|",
    ]
    for method, partitions in results["methods"].items():
        values = partitions["overall"]
        def show(value: Any) -> str:
            return "—" if value is None else f"{float(value):.3f}"
        lines.append(f"| {method} | {show(values[f'ndcg@{primary}'])} | {show(values[f'recall@{primary}'])} | {show(values['pairwise_accuracy'])} |")
    lines.extend(
        [
            "", "## UNKNOWN boundary", "",
            "U0 assigns zero contribution to abstained constraints, U1 uses the configured mild penalty, and U2 additionally scales by supported-constraint coverage. UNKNOWN is never scored as a confirmed mismatch.",
        ]
    )
    (PATHS.reports / "phase10_coldstart_retrieval.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
