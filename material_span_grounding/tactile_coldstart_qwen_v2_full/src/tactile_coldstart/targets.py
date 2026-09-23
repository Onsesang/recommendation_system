from __future__ import annotations

import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import numpy as np

from .common import (
    PATHS, load_experiment, load_taxonomy, read_json, sha256_file, symbolic_score,
    utc_now, write_json, write_jsonl,
)
from .diagnostics import enrich_groundings


def _distribution(values: list[float], bins: list[float]) -> list[float]:
    counts = Counter(min(bins, key=lambda item: abs(item - value)) for value in values)
    total = max(len(values), 1)
    return [counts[value] / total for value in bins]


def _agreement(distribution: list[float]) -> tuple[float, float]:
    probabilities = np.asarray([value for value in distribution if value > 0], dtype=float)
    entropy = float(-(probabilities * np.log(probabilities)).sum()) if len(probabilities) else 0.0
    normalized = entropy / math.log(float(len(distribution))) if len(probabilities) > 1 and len(distribution) > 1 else 0.0
    return 1.0 - normalized, entropy


def build_targets() -> dict[str, Any]:
    config = load_experiment()
    taxonomy = load_taxonomy()
    active = read_json(PATHS.artifacts / "active_axes.json")["active_axes"]
    products, rows = enrich_groundings()
    bins = [float(value) for value in config["targets"]["score_bins"]]
    minimum_confidence = float(config["targets"]["minimum_mapping_confidence"])
    eligible = [
        row for row in rows
        if row.get("status") == "success" and row.get("mappable")
        and row.get("axis_id") in active and float(row.get("confidence", 0.0)) >= minimum_confidence
    ]
    reviewer_spans: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in eligible:
        reviewer_spans[(row["family_id"], row["reviewer_key"], row["axis_id"])].append(row)
    reviewer_records = []
    by_product_axis: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for (family_id, reviewer, axis_id), values in reviewer_spans.items():
        scores = [symbolic_score(row, taxonomy) for row in values]
        record = {
            "product_id": family_id,
            "reviewer_hash": hashlib_sha(reviewer),
            "axis_id": axis_id,
            "value": float(np.mean(scores)),
            "span_count": len(values),
            "review_count": len({row["review_id"] for row in values}),
            "mean_mapping_confidence": float(np.mean([float(row["confidence"]) for row in values])),
            "span_ids": [row["span_id"] for row in values],
        }
        reviewer_records.append(record)
        by_product_axis[(family_id, axis_id)].append(record)
    write_jsonl(PATHS.artifacts / "reviewer_axis_targets.jsonl", reviewer_records)

    product_ids = [str(row["product_id"]) for row in products]
    axis_ids = list(active)
    value_matrix = np.full((len(product_ids), len(axis_ids)), np.nan, dtype=np.float32)
    mask_matrix = np.zeros_like(value_matrix, dtype=np.uint8)
    support_matrix = np.zeros_like(value_matrix, dtype=np.int16)
    agreement_matrix = np.full_like(value_matrix, np.nan, dtype=np.float32)
    product_index = {value: index for index, value in enumerate(product_ids)}
    axis_index = {value: index for index, value in enumerate(axis_ids)}
    records = []
    for product_id in product_ids:
        for axis_id in axis_ids:
            reviewer_rows = by_product_axis.get((product_id, axis_id), [])
            if not reviewer_rows:
                records.append(
                    {
                        "product_id": product_id,
                        "axis_id": axis_id,
                        "target_mean": None,
                        "target_distribution": None,
                        "support_reviewers": 0,
                        "support_spans": 0,
                        "agreement": None,
                        "dispersion": None,
                        "entropy": None,
                        "mean_mapping_confidence": None,
                        "mask": 0,
                        "source": "review_unobserved",
                    }
                )
                continue
            values = [float(row["value"]) for row in reviewer_rows]
            distribution = _distribution(values, bins)
            agreement, entropy = _agreement(distribution)
            mean = float(np.mean(values))
            record = {
                "product_id": product_id,
                "axis_id": axis_id,
                "target_mean": mean,
                "target_distribution": distribution,
                "support_reviewers": len(reviewer_rows),
                "support_spans": sum(int(row["span_count"]) for row in reviewer_rows),
                "agreement": agreement,
                "dispersion": float(np.std(values)),
                "entropy": entropy,
                "mean_mapping_confidence": float(np.mean([row["mean_mapping_confidence"] for row in reviewer_rows])),
                "mask": 1,
                "source": "review_pseudo",
            }
            records.append(record)
            i, j = product_index[product_id], axis_index[axis_id]
            value_matrix[i, j] = mean
            mask_matrix[i, j] = 1
            support_matrix[i, j] = len(reviewer_rows)
            agreement_matrix[i, j] = agreement
    records_path = PATHS.artifacts / "product_axis_targets.jsonl"
    vectors_path = PATHS.artifacts / "product_axis_targets.npz"
    write_jsonl(records_path, records)
    np.savez_compressed(
        vectors_path,
        product_ids=np.asarray(product_ids),
        axis_ids=np.asarray(axis_ids),
        values=value_matrix,
        mask=mask_matrix,
        support=support_matrix,
        agreement=agreement_matrix,
    )
    manifest = {
        "status": "complete" if axis_ids else "gate_failed_no_active_axes",
        "phase": 5,
        "generated_at": utc_now(),
        "products": len(product_ids),
        "axes": axis_ids,
        "reviewer_axis_records": len(reviewer_records),
        "observed_product_axis_pairs": int(mask_matrix.sum()),
        "unobserved_product_axis_pairs": int(mask_matrix.size - mask_matrix.sum()),
        "primary_target_coding": config["targets"].get("primary_coding", "ordinal_with_intensity"),
        "human_validation_status": "skipped_by_user_pending",
        "outputs": {
            "records": str(records_path),
            "records_sha256": sha256_file(records_path),
            "vectors": str(vectors_path),
            "vectors_sha256": sha256_file(vectors_path),
        },
    }
    write_json(PATHS.manifests / "phase5_targets.json", manifest)
    (PATHS.reports / "phase5_targets.md").write_text(
        f"# Phase 5 — Reviewer-first Targets\n\nActive axes: `{', '.join(axis_ids) or 'none'}`\n\n"
        f"Observed product-axis pairs: {int(mask_matrix.sum()):,}/{mask_matrix.size:,}. "
        "Missing pairs have mask=0 and are excluded from loss. Reviewer disagreement is retained as distribution, dispersion, and entropy.\n",
        encoding="utf-8",
    )
    return manifest


def hashlib_sha(value: str) -> str:
    import hashlib
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]
