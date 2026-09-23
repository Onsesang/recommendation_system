from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np

from .baselines import _load_tactile_index
from .common import read_jsonl, save_json, write_jsonl
from .metrics import (
    aggregate_ranking_metrics,
    attach_named_metrics,
    bootstrap_delta,
    ranking_metrics,
)
from .protocol import DEFAULT_OUTPUT


def _tactile_case(
    case: dict[str, Any], ranked: list[str], tactile: dict[str, np.ndarray], k: int
) -> dict[str, float | int | None]:
    history = [tactile[item] for item in case["train_items"] if item in tactile]
    recommended = [tactile[item] for item in ranked[:k] if item in tactile]
    result: dict[str, float | int | None] = {
        "tactile_history_items": len(history),
        "tactile_recommended_items": len(recommended),
        "tactile_item_coverage": len(recommended) / k,
        "tactile_match": None,
        "target_tactile_match": None,
    }
    if not history:
        return result
    profile = np.mean(np.stack(history), axis=0)
    profile /= max(float(np.linalg.norm(profile)), 1e-12)
    if recommended:
        result["tactile_match"] = float(
            np.mean([float(profile @ vector) for vector in recommended])
        )
    targets = [tactile[item] for item in case["test_items"] if item in tactile]
    if targets:
        result["target_tactile_match"] = float(
            np.mean([float(profile @ vector) for vector in targets])
        )
    return result


def _cohort_summary(rows: list[dict[str, Any]], k: int) -> dict[str, Any]:
    if not rows:
        return {"cases": 0}
    base = aggregate_ranking_metrics(
        [
            {
                "precision": row[f"precision@{k}"],
                "recall": row[f"recall@{k}"],
                "hit_rate": row[f"hit_rate@{k}"],
                "ndcg": row[f"ndcg@{k}"],
                "mrr": row["mrr"],
                "map": row[f"map@{k}"],
            }
            for row in rows
        ],
        k,
    )
    tactile_matches = [row["tactile_match"] for row in rows if row["tactile_match"] is not None]
    target_matches = [
        row["target_tactile_match"]
        for row in rows
        if row["target_tactile_match"] is not None
    ]
    base.update(
        {
            f"tactile_match@{k}": float(np.mean(tactile_matches)) if tactile_matches else None,
            f"tactile_match_eligible_cases@{k}": len(tactile_matches),
            f"tactile_item_coverage@{k}": float(
                np.mean([row["tactile_item_coverage"] for row in rows])
            ),
            "tactile_profile_coverage": float(
                np.mean([row["tactile_history_items"] > 0 for row in rows])
            ),
            "target_tactile_match": float(np.mean(target_matches)) if target_matches else None,
            "target_tactile_coverage": len(target_matches) / len(rows),
        }
    )
    base["tactile_match_status"] = (
        "reportable"
        if base["tactile_profile_coverage"] >= 0.5
        and base[f"tactile_item_coverage@{k}"] >= 0.5
        else "insufficient_coverage"
    )
    return base


def evaluate_predictions(
    *,
    predictions: dict[str, Path],
    protocol_root: Path = DEFAULT_OUTPUT,
    output_root: Path | None = None,
    k: int = 10,
    baseline: str | None = "popularity",
    bootstrap_samples: int = 5000,
    seed: int = 20260813,
) -> dict[str, Any]:
    if k <= 0:
        raise ValueError("k must be positive")
    protocol_root = Path(protocol_root)
    output_root = Path(output_root or protocol_root / "results")
    cases = read_jsonl(protocol_root / "cases.jsonl")
    case_by_id = {row["case_id"]: row for row in cases}
    tactile, _ = _load_tactile_index()
    evaluated: dict[str, list[dict[str, Any]]] = {}

    for model_name, prediction_path in predictions.items():
        prediction_rows = read_jsonl(Path(prediction_path))
        prediction_by_id = {row["case_id"]: row for row in prediction_rows}
        if len(prediction_by_id) != len(prediction_rows):
            raise ValueError(f"{model_name}: duplicate case_id in predictions")
        missing = set(case_by_id) - set(prediction_by_id)
        extra = set(prediction_by_id) - set(case_by_id)
        if missing or extra:
            raise ValueError(
                f"{model_name}: prediction case mismatch missing={len(missing)} extra={len(extra)}"
            )
        model_rows = []
        for case in cases:
            ranked = [str(item) for item in prediction_by_id[case["case_id"]]["ranked_items"]]
            if len(set(ranked)) != len(ranked):
                raise ValueError(f"{model_name}/{case['case_id']}: duplicate ranked item")
            invalid = set(ranked) - set(case["candidates"])
            if invalid:
                raise ValueError(
                    f"{model_name}/{case['case_id']}: ranked items outside candidate set"
                )
            missing_candidates = set(case["candidates"]) - set(ranked)
            if missing_candidates or len(ranked) != len(case["candidates"]):
                raise ValueError(
                    f"{model_name}/{case['case_id']}: predictions must rank every candidate"
                )
            values = ranking_metrics(ranked, case["test_items"], k)
            row: dict[str, Any] = {
                "case_id": case["case_id"],
                "target_item_cohort": case["target_item_cohort"],
                "user_cohort": case["user_cohort"],
            }
            attach_named_metrics(row, values, k)
            row.update(_tactile_case(case, ranked, tactile, k))
            model_rows.append(row)
        evaluated[model_name] = model_rows
        write_jsonl(output_root / f"per_case_{model_name}.jsonl", model_rows)

    summaries = {}
    for model_name, rows in evaluated.items():
        by_item: dict[str, list[dict[str, Any]]] = defaultdict(list)
        by_user: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            by_item[row["target_item_cohort"]].append(row)
            by_user[row["user_cohort"]].append(row)
        summaries[model_name] = {
            "overall": _cohort_summary(rows, k),
            "by_target_item_cohort": {
                name: _cohort_summary(values, k) for name, values in sorted(by_item.items())
            },
            "by_user_cohort": {
                name: _cohort_summary(values, k) for name, values in sorted(by_user.items())
            },
        }

    comparisons = {}
    if baseline and baseline in evaluated:
        metric_names = (f"recall@{k}", f"ndcg@{k}", "mrr", f"tactile_match@{k}")
        base_by_id = {row["case_id"]: row for row in evaluated[baseline]}
        for model_name, rows in evaluated.items():
            if model_name == baseline:
                continue
            model_comparison = {}
            for metric in metric_names:
                source_key = "tactile_match" if metric.startswith("tactile_match") else metric
                pairs = [
                    (base_by_id[row["case_id"]].get(source_key), row.get(source_key))
                    for row in rows
                ]
                valid = [(a, b) for a, b in pairs if a is not None and b is not None]
                if not valid:
                    model_comparison[metric] = {"paired_cases": 0, "status": "not_available"}
                    continue
                delta = bootstrap_delta(
                    [float(pair[0]) for pair in valid],
                    [float(pair[1]) for pair in valid],
                    seed=seed,
                    samples=bootstrap_samples,
                )
                model_comparison[metric] = {"paired_cases": len(valid), **delta}
            comparisons[f"{model_name}_minus_{baseline}"] = model_comparison

    payload = {
        "status": "complete",
        "k": k,
        "cases": len(cases),
        "models": summaries,
        "paired_bootstrap": comparisons,
        "interpretation_contract": {
            "ranking_metrics": "computed on the identical stored candidate set for every model",
            "tactile_match": (
                "mean cosine between the user's train-history tactile profile and top-K items that "
                "have review-derived targets"
            ),
            "tactile_warning": (
                "Do not compare TactileMatch without tactile_profile_coverage and "
                "tactile_item_coverage@K. N/A means the current tactile catalog is too sparse."
            ),
            "score_direction": "higher is better",
        },
    }
    save_json(output_root / "metrics.json", payload)
    return payload
