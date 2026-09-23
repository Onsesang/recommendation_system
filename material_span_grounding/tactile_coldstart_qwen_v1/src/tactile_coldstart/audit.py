from __future__ import annotations

import csv
import hashlib
import math
from collections import defaultdict
from typing import Any

from .common import PATHS, load_experiment, read_jsonl, sha256_file, utc_now, write_json
from .diagnostics import diagnostic_family_ids, product_lookup


def export_human_audit() -> dict[str, Any]:
    config = load_experiment()
    allowed = diagnostic_family_ids(config)
    _, lookup = product_lookup(config)
    rows = [
        row for row in read_jsonl(PATHS.artifacts / "axis_groundings.jsonl")
        if row.get("status") == "success" and str(row.get("asin")) in lookup
        and str(lookup[str(row["asin"])]["product_id"]) in allowed
    ]
    sample_size = min(int(config["diagnostics"]["audit_sample_size"]), len(rows))
    strata: dict[tuple[str, str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        key = (
            str(row.get("axis_id") or "unmappable"),
            str(row.get("direction") or "none"),
            str(row.get("intensity") or "none"),
            str(row.get("property_status") or "unknown"),
            str(row.get("scope") or "unknown"),
        )
        strata[key].append(row)
    for values in strata.values():
        values.sort(key=lambda row: hashlib.sha256(str(row["span_id"]).encode()).hexdigest())
    selected = []
    ordered_keys = sorted(strata)
    cursor = 0
    while len(selected) < sample_size and ordered_keys:
        key = ordered_keys[cursor % len(ordered_keys)]
        if strata[key]:
            selected.append(strata[key].pop(0))
        else:
            ordered_keys.remove(key)
            cursor -= 1
        cursor += 1
    path = PATHS.artifacts / "human_axis_audit.csv"
    fields = [
        "span_id", "exact_span", "review_context", "qwen_mappable", "qwen_axis_id",
        "qwen_direction", "qwen_intensity", "qwen_scope", "qwen_confidence",
        "human_mappable", "human_axis_id", "human_direction", "human_intensity",
        "human_scope", "annotator_id", "notes",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in selected:
            writer.writerow(
                {
                    "span_id": row["span_id"],
                    "exact_span": row["quote"],
                    "review_context": row["review_text"],
                    "qwen_mappable": row["mappable"],
                    "qwen_axis_id": row.get("axis_id"),
                    "qwen_direction": row.get("direction"),
                    "qwen_intensity": row.get("intensity"),
                    "qwen_scope": row.get("scope"),
                    "qwen_confidence": row.get("confidence"),
                }
            )
    manifest = {
        "status": "annotation_support_complete",
        "phase": 4,
        "generated_at": utc_now(),
        "sample_size": len(selected),
        "sampling": "deterministic round-robin over axis/direction/intensity/property-status/scope strata",
        "human_labels_complete": False,
        "limitation": "Human labels require external annotator work and were not fabricated by the pipeline.",
        "output": str(path),
        "output_sha256": sha256_file(path),
    }
    write_json(PATHS.manifests / "phase4_human_audit.json", manifest)
    (PATHS.reports / "phase4_human_audit.md").write_text(
        f"# Phase 4 — Human Audit Support\n\nExported {len(selected):,} stratified spans to `{path}`. "
        "Human labels are intentionally blank. The downstream run remains a pseudo-label experiment until independent annotations are completed.\n",
        encoding="utf-8",
    )
    return manifest


def evaluate_human_audit() -> dict[str, Any]:
    from sklearn.metrics import accuracy_score, cohen_kappa_score, f1_score

    config = load_experiment()
    path = PATHS.artifacts / "human_axis_audit.csv"
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    annotated = [row for row in rows if str(row.get("human_mappable", "")).strip()]
    if not annotated:
        result = {
            "status": "pending_human_annotation", "phase": 4,
            "generated_at": utc_now(), "annotated": 0, "sample_size": len(rows),
            "metrics": None,
            "limitation": "No human labels are present; metrics were not fabricated.",
        }
        write_json(PATHS.artifacts / "phase4_human_audit_metrics.json", result)
        return result
    truth_mappable = [str(row["human_mappable"]).strip().casefold() in {"1", "true", "yes", "y"} for row in annotated]
    predicted_mappable = [str(row["qwen_mappable"]).strip().casefold() in {"1", "true", "yes", "y"} for row in annotated]
    jointly_mappable = [index for index, value in enumerate(truth_mappable) if value and predicted_mappable[index]]
    human_axis = [annotated[index]["human_axis_id"] for index in jointly_mappable]
    qwen_axis = [annotated[index]["qwen_axis_id"] for index in jointly_mappable]
    human_direction = [annotated[index]["human_direction"] for index in jointly_mappable]
    qwen_direction = [annotated[index]["qwen_direction"] for index in jointly_mappable]
    intensity_order = [str(value) for value in config["diagnostics"]["audit_intensity_order"]]
    intensity_index = {value: index for index, value in enumerate(intensity_order)}
    intensity_pairs = [
        index for index in jointly_mappable
        if annotated[index]["human_intensity"] in intensity_index and annotated[index]["qwen_intensity"] in intensity_index
    ]
    source = {str(row["span_id"]): row for row in read_jsonl(PATHS.artifacts / "axis_groundings.jsonl")}
    exact_preserved = [row["exact_span"] == str(source.get(str(row["span_id"]), {}).get("quote", "")) for row in annotated]
    intensity_kappa = (
        float(
            cohen_kappa_score(
                [intensity_index[annotated[index]["human_intensity"]] for index in intensity_pairs],
                [intensity_index[annotated[index]["qwen_intensity"]] for index in intensity_pairs],
                weights="quadratic",
            )
        ) if len(intensity_pairs) >= 2 else None
    )
    if intensity_kappa is not None and not math.isfinite(intensity_kappa):
        intensity_kappa = None
    metrics = {
        "unmappable_detection_f1": float(f1_score(truth_mappable, predicted_mappable, pos_label=False, zero_division=0)),
        "mappable_detection_f1": float(f1_score(truth_mappable, predicted_mappable, pos_label=True, zero_division=0)),
        "axis_macro_f1": float(f1_score(human_axis, qwen_axis, average="macro", zero_division=0)) if human_axis else None,
        "polarity_accuracy": float(accuracy_score(human_direction, qwen_direction)) if human_direction else None,
        "intensity_weighted_kappa": intensity_kappa,
        "exact_span_preservation": float(sum(exact_preserved) / len(exact_preserved)),
    }
    result = {
        "status": "complete", "phase": 4, "generated_at": utc_now(),
        "annotated": len(annotated), "sample_size": len(rows), "metrics": metrics,
    }
    write_json(PATHS.artifacts / "phase4_human_audit_metrics.json", result)
    return result
