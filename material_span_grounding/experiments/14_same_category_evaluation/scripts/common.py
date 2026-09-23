from __future__ import annotations

import csv
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Iterable

import numpy as np
from sklearn.metrics import f1_score, precision_score, recall_score


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config.json"


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, indent=2, ensure_ascii=False, allow_nan=False)
            handle.write("\n")
        os.replace(temporary_name, path)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)


def atomic_csv(path: Path, fieldnames: list[str], rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        os.replace(temporary_name, path)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def source_hashes(config: dict[str, Any]) -> dict[str, str]:
    return {name: sha256(Path(path)) for name, path in config["paths"].items()}


def sigmoid(logits: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-np.clip(logits, -80.0, 80.0)))


def pairwise_accuracy(positive_scores: np.ndarray, negative_scores: np.ndarray) -> float:
    comparison = positive_scores[:, None] - negative_scores[None, :]
    return float(((comparison > 0).sum() + 0.5 * (comparison == 0).sum()) / comparison.size)


def average_precision_tie_safe(truth: np.ndarray, scores: np.ndarray) -> float:
    """Non-interpolated AP with equal-score samples handled as one threshold group."""
    truth = truth.astype(np.int64)
    positive = int(truth.sum())
    if positive == 0:
        raise ValueError("average precision requires at least one positive")
    order = np.argsort(-scores, kind="mergesort")
    sorted_scores = scores[order]
    sorted_truth = truth[order]
    group_end = np.r_[np.flatnonzero(np.diff(sorted_scores) != 0), len(scores) - 1]
    cumulative_positive = np.cumsum(sorted_truth)[group_end]
    retrieved = group_end + 1
    previous_positive = np.r_[0, cumulative_positive[:-1]]
    recall_increment = (cumulative_positive - previous_positive) / positive
    precision = cumulative_positive / retrieved
    return float(np.sum(recall_increment * precision))


def cell_metrics(
    truth: np.ndarray,
    scores: np.ndarray,
    threshold: float,
    reliable_positive: int,
    reliable_negative: int,
) -> dict[str, Any]:
    truth = truth.astype(bool)
    observed = len(truth)
    positive = int(truth.sum())
    negative = observed - positive
    prevalence = positive / observed if observed else None
    if observed == 0:
        reason = "no_observed_pairs"
    elif positive == 0:
        reason = "negative_only"
    elif negative == 0:
        reason = "positive_only"
    else:
        reason = None
    valid = reason is None
    prediction = scores >= threshold
    row: dict[str, Any] = {
        "observed": observed,
        "positive": positive,
        "negative": negative,
        "prevalence": prevalence,
        "threshold": float(threshold),
        "precision": float(precision_score(truth, prediction, zero_division=0)) if observed else None,
        "recall": float(recall_score(truth, prediction, zero_division=0)) if observed else None,
        "f1": float(f1_score(truth, prediction, zero_division=0)) if observed else None,
        "valid": valid,
        "skip_reason": reason,
        "reliable_support": bool(valid and positive >= reliable_positive and negative >= reliable_negative),
        "pair_count": positive * negative,
    }
    if valid:
        positive_scores = scores[truth]
        negative_scores = scores[~truth]
        auc = pairwise_accuracy(positive_scores, negative_scores)
        ap = average_precision_tie_safe(truth, scores)
        lift = ap - prevalence
        row.update(
            {
                "auroc": auc,
                "average_precision": ap,
                "ap_lift": lift,
                "normalized_ap_lift": lift / (1.0 - prevalence),
                "pairwise_accuracy": auc,
                "probability_range": float(scores.max() - scores.min()),
            }
        )
    else:
        row.update(
            {
                "auroc": None,
                "average_precision": None,
                "ap_lift": None,
                "normalized_ap_lift": None,
                "pairwise_accuracy": None,
                "probability_range": float(scores.max() - scores.min()) if observed else None,
            }
        )
    return row


def aggregate_cells(rows: list[dict[str, Any]], reliable_only: bool = False) -> dict[str, Any]:
    selected = [row for row in rows if row["valid"] and (row["reliable_support"] or not reliable_only)]
    if not selected:
        return {
            "valid_cells": 0,
            "observed": 0,
            "positive": 0,
            "negative": 0,
            "positive_negative_pairs": 0,
            "macro_cell_auroc": None,
            "pair_weighted_auroc": None,
            "macro_category_average_precision": None,
            "macro_category_prevalence": None,
            "macro_category_ap_lift": None,
            "macro_category_normalized_ap_lift": None,
            "pairwise_accuracy": None,
        }
    pair_counts = np.asarray([row["pair_count"] for row in selected], dtype=np.float64)
    aurocs = np.asarray([row["auroc"] for row in selected], dtype=np.float64)
    return {
        "valid_cells": len(selected),
        "observed": int(sum(row["observed"] for row in selected)),
        "positive": int(sum(row["positive"] for row in selected)),
        "negative": int(sum(row["negative"] for row in selected)),
        "positive_negative_pairs": int(pair_counts.sum()),
        "macro_cell_auroc": float(np.mean(aurocs)),
        "pair_weighted_auroc": float(np.average(aurocs, weights=pair_counts)),
        "macro_category_average_precision": float(np.mean([row["average_precision"] for row in selected])),
        "macro_category_prevalence": float(np.mean([row["prevalence"] for row in selected])),
        "macro_category_ap_lift": float(np.mean([row["ap_lift"] for row in selected])),
        "macro_category_normalized_ap_lift": float(np.mean([row["normalized_ap_lift"] for row in selected])),
        "pairwise_accuracy": float(np.average([row["pairwise_accuracy"] for row in selected], weights=pair_counts)),
    }


def percentile_interval(values: list[float], confidence_level: float) -> dict[str, Any]:
    array = np.asarray(values, dtype=np.float64)
    alpha = (1.0 - confidence_level) / 2.0
    return {
        "lower": float(np.quantile(array, alpha)),
        "upper": float(np.quantile(array, 1.0 - alpha)),
        "bootstrap_mean": float(array.mean()),
        "valid_replicates": len(values),
    }
