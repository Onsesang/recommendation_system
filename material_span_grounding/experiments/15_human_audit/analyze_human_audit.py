#!/usr/bin/env python3
"""Analyze completed human-audit rows without tuning any model threshold."""
from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

import numpy as np
from sklearn.metrics import average_precision_score, roc_auc_score

from common import ANNOTATION_PATH, CONFIG_PATH, MANIFEST_PATH, RESULTS_PATH, atomic_json, read_json, source_hashes
from storage import ensure_annotation_csv, read_annotations


def _rate(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def _classification_metrics(y_true: Iterable[int], y_pred: Iterable[int], scores: Iterable[float] | None = None) -> dict[str, Any]:
    truth = np.asarray(list(y_true), dtype=np.int64)
    predicted = np.asarray(list(y_pred), dtype=np.int64)
    support = int(truth.size)
    if support == 0:
        return {
            "support": 0,
            "positive_support": 0,
            "negative_support": 0,
            "auroc": None,
            "average_precision": None,
            "accuracy": None,
            "precision": None,
            "recall": None,
            "f1": None,
        }
    tp = int(np.sum((truth == 1) & (predicted == 1)))
    tn = int(np.sum((truth == 0) & (predicted == 0)))
    fp = int(np.sum((truth == 0) & (predicted == 1)))
    fn = int(np.sum((truth == 1) & (predicted == 0)))
    precision = _rate(tp, tp + fp)
    recall = _rate(tp, tp + fn)
    f1 = (2 * precision * recall / (precision + recall)) if precision is not None and recall is not None and precision + recall else None
    auroc = None
    average_precision = None
    score_values = None if scores is None else np.asarray(list(scores), dtype=np.float64)
    if score_values is not None and len(np.unique(truth)) == 2:
        auroc = float(roc_auc_score(truth, score_values))
        average_precision = float(average_precision_score(truth, score_values))
    return {
        "support": support,
        "positive_support": int(np.sum(truth == 1)),
        "negative_support": int(np.sum(truth == 0)),
        "auroc": auroc,
        "average_precision": average_precision,
        "accuracy": _rate(tp + tn, support),
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "confusion": {"true_positive": tp, "true_negative": tn, "false_positive": fp, "false_negative": fn},
    }


def _human_binary(row: dict[str, Any]) -> int:
    return 1 if row["annotation"]["human_label"] == "present" else 0


def _eligible(rows: list[dict[str, Any]], observability: set[str]) -> list[dict[str, Any]]:
    return [
        row
        for row in rows
        if not row["item"]["image_missing"]
        and row["annotation"]["image_observability"] in observability
        and row["annotation"]["human_label"] in {"present", "absent"}
    ]


def _last2_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return _classification_metrics(
        (_human_binary(row) for row in rows),
        (int(row["item"]["last2_binary_prediction"]) for row in rows),
        (float(row["item"]["last2_probability"]) for row in rows),
    )


def _pseudo_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    metrics = _classification_metrics(
        (_human_binary(row) for row in rows),
        (int(row["item"]["binary_target"]) for row in rows),
    )
    metrics["agreement"] = metrics["accuracy"]
    return metrics


def _observability(rows: list[dict[str, Any]], classes: list[str]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for class_name in ["overall", *classes]:
        subset = rows if class_name == "overall" else [row for row in rows if row["item"]["tactile_class"] == class_name]
        counts = Counter(row["annotation"]["image_observability"] for row in subset)
        total = len(subset)
        output[class_name] = {
            "completed": total,
            "yes": counts["yes"],
            "partial": counts["partial"],
            "no": counts["no"],
            "strict_observability_rate": _rate(counts["yes"], total),
            "inclusive_observability_rate": _rate(counts["yes"] + counts["partial"], total),
        }
    return output


def _model_comparison(rows: list[dict[str, Any]], classes: list[str], observability: set[str]) -> dict[str, Any]:
    eligible = _eligible(rows, observability)
    per_class = {}
    for class_name in classes:
        subset = [row for row in eligible if row["item"]["tactile_class"] == class_name]
        per_class[class_name] = {
            "last2_vs_human": _last2_metrics(subset),
            "pseudo_label_vs_human_image_label": _pseudo_metrics(subset),
        }
    return {
        "observability_filter": sorted(observability),
        "threshold_source": "existing development-selected Last2 thresholds; never tuned on human-audit data",
        "last2_vs_human": _last2_metrics(eligible),
        "pseudo_label_vs_human_image_label": _pseudo_metrics(eligible),
        "per_class": per_class,
    }


def _review_comparison(rows: list[dict[str, Any]], classes: list[str]) -> dict[str, Any]:
    clear_mapping = {"present_evidence": 1, "absent_or_opposite_evidence": 0}
    all_reviewed = [row for row in rows if row["annotation"].get("review_human_label")]
    exclusion_counts = Counter(
        row["annotation"]["review_human_label"]
        for row in all_reviewed
        if row["annotation"]["review_human_label"] not in clear_mapping
    )
    clear = [
        row
        for row in all_reviewed
        if row["annotation"]["review_human_label"] in clear_mapping
        and row["item"].get("qwen_contributed_binary_target") in (0, 1)
    ]

    def compute(subset: list[dict[str, Any]]) -> dict[str, Any]:
        metrics = _classification_metrics(
            (clear_mapping[row["annotation"]["review_human_label"]] for row in subset),
            (int(row["item"]["qwen_contributed_binary_target"]) for row in subset),
        )
        metrics["agreement"] = metrics["accuracy"]
        return metrics

    return {
        "reviewed_items": len(all_reviewed),
        "clear_binary_items_with_linked_qwen": len(clear),
        "excluded_nonbinary_review_judgments": dict(sorted(exclusion_counts.items())),
        "missing_qwen_link_among_clear_review_judgments": sum(
            row["annotation"]["review_human_label"] in clear_mapping
            and row["item"].get("qwen_contributed_binary_target") not in (0, 1)
            for row in all_reviewed
        ),
        "overall": compute(clear),
        "per_class": {
            class_name: compute([row for row in clear if row["item"]["tactile_class"] == class_name])
            for class_name in classes
        },
    }


def _disagreements(rows: list[dict[str, Any]], limit: int) -> dict[str, list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    names = {(1, 1): "clean_success", (0, 0): "clean_negative", (1, 0): "false_negative", (0, 1): "false_positive"}
    for row in _eligible(rows, {"yes"}):
        human = _human_binary(row)
        model = int(row["item"]["last2_binary_prediction"])
        item = row["item"]
        groups[names[(human, model)]].append(
            {
                "item_id": item["item_id"],
                "asin": item["asin"],
                "tactile_class": item["tactile_class"],
                "category": item["category"],
                "human_label": row["annotation"]["human_label"],
                "model_probability": item["last2_probability"],
                "threshold": item["last2_threshold"],
                "original_review": item.get("original_review_text"),
            }
        )
    for values in groups.values():
        values.sort(key=lambda value: (value["tactile_class"], value["asin"]))
    return {name: groups[name][:limit] for name in ("clean_success", "clean_negative", "false_negative", "false_positive")}


def main() -> int:
    if not MANIFEST_PATH.exists():
        raise SystemExit(f"missing manifest: {MANIFEST_PATH}")
    ensure_annotation_csv(ANNOTATION_PATH)
    config = read_json(CONFIG_PATH)
    manifest = read_json(MANIFEST_PATH)
    annotation_map = read_annotations(ANNOTATION_PATH)
    item_map = {item["item_id"]: item for item in manifest["items"]}
    unknown = sorted(set(annotation_map) - set(item_map))
    if unknown:
        raise ValueError(f"annotation CSV contains unknown item_id values: {unknown[:5]}")
    completed_rows = [
        {"item": item_map[item_id], "annotation": annotation}
        for item_id, annotation in annotation_map.items()
        if annotation.get("completed", "").lower() == "true"
    ]
    classes = config["primary_classes"]
    total = int(manifest["total_items"])
    completed = len(completed_rows)
    status = "not_started" if completed == 0 else ("complete" if completed == total else "in_progress")
    class_distribution = {}
    for class_name in classes:
        manifest_subset = [item for item in manifest["items"] if item["tactile_class"] == class_name]
        completed_subset = [row for row in completed_rows if row["item"]["tactile_class"] == class_name]
        class_distribution[class_name] = {
            "manifest": len(manifest_subset),
            "completed": len(completed_subset),
            "target_positive": sum(int(item["binary_target"]) == 1 for item in manifest_subset),
            "target_negative": sum(int(item["binary_target"]) == 0 for item in manifest_subset),
            "fractional_target": sum(bool(item["is_fractional_target"]) for item in manifest_subset),
        }
    current_hashes = source_hashes(config)
    results = {
        "status": status,
        "actual_human_results_available": completed > 0,
        "notice": "No human annotations have been fabricated; metrics reflect only rows saved through the audit UI.",
        "total_manifest_items": total,
        "completed_items": completed,
        "remaining_items": total - completed,
        "missing_image_count": int(manifest["image_linkage"]["missing"]),
        "class_distribution": class_distribution,
        "target_distribution": {
            "positive": sum(int(item["binary_target"]) == 1 for item in manifest["items"]),
            "negative": sum(int(item["binary_target"]) == 0 for item in manifest["items"]),
            "fractional": sum(bool(item["is_fractional_target"]) for item in manifest["items"]),
        },
        "observability": _observability(completed_rows, classes),
        "primary_yes_only": _model_comparison(completed_rows, classes, {"yes"}),
        "sensitivity_yes_or_partial": _model_comparison(completed_rows, classes, {"yes", "partial"}),
        "qwen_vs_human_review": _review_comparison(completed_rows, classes),
        "disagreement_examples": _disagreements(completed_rows, int(config["analysis"]["disagreement_examples_per_type"])),
        "integrity": {
            "manifest_source_hashes_unchanged": current_hashes == manifest["source_hashes"],
            "current_source_hashes": current_hashes,
            "manifest_source_hashes": manifest["source_hashes"],
            "duplicate_annotation_item_id_absent": len(annotation_map) == len(set(annotation_map)),
            "threshold_retuned_on_human_data": False,
        },
    }
    atomic_json(RESULTS_PATH, results)
    print(f"status={status} completed={completed}/{total} output={RESULTS_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
