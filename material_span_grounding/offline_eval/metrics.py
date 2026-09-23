from __future__ import annotations

import math
from typing import Any, Iterable

import numpy as np


def ranking_metrics(
    ranked_items: list[str], relevant_items: Iterable[str], k: int
) -> dict[str, float]:
    if k <= 0:
        raise ValueError("k must be positive")
    relevant = set(relevant_items)
    if not relevant:
        raise ValueError("relevant_items must not be empty")
    top = ranked_items[:k]
    hits = [1.0 if item in relevant else 0.0 for item in top]
    hit_count = float(sum(hits))
    first_rank = next(
        (index + 1 for index, item in enumerate(ranked_items) if item in relevant), None
    )
    dcg = sum(hit / math.log2(index + 2) for index, hit in enumerate(hits))
    ideal_hits = min(len(relevant), k)
    idcg = sum(1.0 / math.log2(index + 2) for index in range(ideal_hits))
    precision_sum = 0.0
    seen_hits = 0
    for index, hit in enumerate(hits, 1):
        if hit:
            seen_hits += 1
            precision_sum += seen_hits / index
    average_precision = precision_sum / min(len(relevant), k)
    return {
        "precision": hit_count / k,
        "recall": hit_count / len(relevant),
        "hit_rate": float(hit_count > 0),
        "ndcg": dcg / idcg if idcg else 0.0,
        "mrr": 1.0 / first_rank if first_rank is not None else 0.0,
        "map": average_precision,
        "first_relevant_rank": float(first_rank or 0),
    }


def aggregate_ranking_metrics(
    per_case: list[dict[str, float]], k: int
) -> dict[str, float | int]:
    names = ("precision", "recall", "hit_rate", "ndcg", "mrr", "map")
    result: dict[str, float | int] = {"cases": len(per_case)}
    for name in names:
        result[f"{name}@{k}" if name != "mrr" else "mrr"] = (
            float(np.mean([row[name] for row in per_case])) if per_case else 0.0
        )
    return result


def bootstrap_delta(
    baseline: list[float], treatment: list[float], *, seed: int, samples: int = 5000
) -> dict[str, float]:
    first = np.asarray(baseline, dtype=np.float64)
    second = np.asarray(treatment, dtype=np.float64)
    if first.shape != second.shape or first.ndim != 1:
        raise ValueError("Paired metric arrays must have the same one-dimensional shape")
    if not len(first):
        return {
            "delta": 0.0,
            "ci95_low": 0.0,
            "ci95_high": 0.0,
            "probability_positive": 0.0,
        }
    difference = second - first
    rng = np.random.default_rng(seed)
    draws = np.empty(samples, dtype=np.float64)
    for start in range(0, samples, 250):
        size = min(250, samples - start)
        indices = rng.integers(0, len(difference), size=(size, len(difference)))
        draws[start : start + size] = difference[indices].mean(axis=1)
    return {
        "delta": float(difference.mean()),
        "ci95_low": float(np.quantile(draws, 0.025)),
        "ci95_high": float(np.quantile(draws, 0.975)),
        "probability_positive": float(np.mean(draws > 0)),
    }


def metric_key(name: str, k: int) -> str:
    return name if name == "mrr" else f"{name}@{k}"


def attach_named_metrics(row: dict[str, Any], values: dict[str, float], k: int) -> None:
    for name in ("precision", "recall", "hit_rate", "ndcg", "map"):
        row[f"{name}@{k}"] = values[name]
    row["mrr"] = values["mrr"]
