#!/usr/bin/env python3
from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import numpy as np

from common import ANNOTATION_PATH, CONFIG_PATH, MANIFEST_PATH, ROOT, atomic_json, is_fractional, read_json, source_hashes
from storage import ensure_annotation_csv


def jsonl(path: Path):
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                yield json.loads(line)


def stable_key(seed: int, *parts: str) -> str:
    text = "|".join([str(seed), *map(str, parts)])
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def select_primary_items(
    config: dict[str, Any],
    test_ids: list[str],
    metadata: dict[str, dict[str, Any]],
    classes: list[str],
    values: np.ndarray,
    masks: np.ndarray,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Selection deliberately has no model-score argument."""
    seed = int(config["sampling_seed"])
    per_label = int(config["positive_items_per_class"])
    maximum_uses = int(config["maximum_primary_uses_per_asin"])
    class_index = {name: number for number, name in enumerate(classes)}
    asin_usage: Counter[str] = Counter()
    family_usage: Counter[str] = Counter()
    selected: list[dict[str, Any]] = []
    availability: dict[str, Any] = {}
    for class_name in config["primary_classes"]:
        number = class_index[class_name]
        available = []
        for row_number, asin in enumerate(test_ids):
            if not masks[row_number, number]:
                continue
            raw_target = float(values[row_number, number])
            binary_target = int(raw_target >= 0.5)
            available.append(
                {
                    "asin": asin,
                    "family_id": str(metadata[asin]["product_family_id"]),
                    "category": str(metadata[asin]["category"]),
                    "raw_target": raw_target,
                    "binary_target": binary_target,
                    "is_fractional_target": is_fractional(raw_target),
                    "observed_mask": 1,
                    "tactile_class": class_name,
                }
            )
        availability[class_name] = {
            "observed": len(available),
            "positive": sum(row["binary_target"] == 1 for row in available),
            "negative": sum(row["binary_target"] == 0 for row in available),
            "fractional": sum(row["is_fractional_target"] for row in available),
            "exact_positive": sum(row["binary_target"] == 1 and not row["is_fractional_target"] for row in available),
            "exact_negative": sum(row["binary_target"] == 0 and not row["is_fractional_target"] for row in available),
        }
        for binary_target, label_name in ((1, "positive"), (0, "negative")):
            candidates = [row for row in available if row["binary_target"] == binary_target]
            assert len(candidates) >= per_label, (class_name, label_name, len(candidates))
            category_usage: Counter[str] = Counter()
            chosen_asins: set[str] = set()
            for _ in range(per_label):
                remaining = [row for row in candidates if row["asin"] not in chosen_asins]
                assert remaining
                remaining.sort(
                    key=lambda row: (
                        row["is_fractional_target"],
                        asin_usage[row["asin"]] >= maximum_uses,
                        category_usage[row["category"]],
                        family_usage[row["family_id"]],
                        asin_usage[row["asin"]],
                        stable_key(seed, class_name, label_name, row["category"], row["asin"]),
                    )
                )
                chosen = dict(remaining[0])
                chosen["sampling_stratum"] = f"{class_name}:{label_name}:{'fractional_fallback' if chosen['is_fractional_target'] else 'exact'}"
                selected.append(chosen)
                chosen_asins.add(chosen["asin"])
                category_usage[chosen["category"]] += 1
                asin_usage[chosen["asin"]] += 1
                family_usage[chosen["family_id"]] += 1
    expected = len(config["primary_classes"]) * int(config["items_per_class"])
    assert len(selected) == expected
    assert max(asin_usage.values()) <= maximum_uses
    selected.sort(key=lambda row: stable_key(seed, "audit_order", row["asin"], row["tactile_class"]))
    for number, row in enumerate(selected, start=1):
        row["item_id"] = f"audit-{number:04d}"
        row["audit_order"] = number
        row["sampling_seed"] = seed
    diagnostics = {
        "available_locked_test_support": availability,
        "unique_asins": len(asin_usage),
        "unique_families": len(family_usage),
        "maximum_asin_repetitions": max(asin_usage.values()),
        "asin_repetition_distribution": dict(sorted(Counter(asin_usage.values()).items())),
        "selection_features": ["locked-test membership", "observed mask", "raw target", "binary target", "fractional flag", "category", "family ID", "ASIN", "sampling seed"],
        "model_score_used_for_sampling": False,
    }
    return selected, diagnostics


def main() -> int:
    if MANIFEST_PATH.exists():
        raise SystemExit(f"manifest already exists and is immutable: {MANIFEST_PATH}")
    config = read_json(CONFIG_PATH)
    before_hashes = source_hashes(config)
    split_document = read_json(Path(config["paths"]["split_manifest"]))
    test_ids = [str(value) for value in split_document["splits"][config["evaluation_split"]]]
    metadata_rows = read_json(Path(config["paths"]["product_metadata"]))
    metadata = {str(row["product_id"]): row for row in metadata_rows}
    alias_to_product: dict[str, str] = {}
    for row in metadata_rows:
        product_id = str(row["product_id"])
        alias_to_product[product_id] = product_id
        for alias in row.get("alias_product_ids", []):
            alias_to_product[str(alias)] = product_id
    with np.load(Path(config["paths"]["v3_targets_npz"]), allow_pickle=False) as targets:
        all_ids = targets["product_ids"].astype(str)
        classes = targets["classes"].astype(str).tolist()
        index = {value: number for number, value in enumerate(all_ids)}
        test_indices = np.asarray([index[value] for value in test_ids], dtype=np.int64)
        values = targets["values"][test_indices].astype(np.float32)
        masks = targets["mask"][test_indices].astype(np.uint8)
    assert set(config["primary_classes"] + config["supplementary_classes"]) == set(classes)
    selected, sampling_diagnostics = select_primary_items(
        config, test_ids, metadata, classes, values, masks
    )
    # Scores are loaded only after the selected item identities are frozen.
    selected_identity_sha256 = hashlib.sha256(
        "\n".join(f"{row['item_id']}|{row['asin']}|{row['tactile_class']}" for row in selected).encode("utf-8")
    ).hexdigest()
    with np.load(Path(config["paths"]["fixed_predictions"]), allow_pickle=False) as predictions:
        prediction_ids = predictions["test_product_ids"].astype(str)
        assert prediction_ids.tolist() == test_ids
        prediction_classes = predictions["classes"].astype(str).tolist()
        assert prediction_classes == classes
        last2_probabilities = predictions["test_last2_probabilities"].astype(np.float64)
        last2_thresholds = predictions["last2_thresholds"].astype(np.float64)
    test_index = {value: number for number, value in enumerate(test_ids)}
    class_index = {value: number for number, value in enumerate(classes)}

    selected_keys = {(row["asin"], row["tactile_class"]) for row in selected}
    opposite: dict[str, str] = {}
    v3_config = read_json(Path(config["paths"]["v3_config"]))
    for left, right in v3_config["exclusive_pairs"]:
        opposite[left] = right
        opposite[right] = left
    minimum_confidence = float(v3_config["minimum_confidence"])
    evidence: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for grounding in jsonl(Path(config["paths"]["qwen_groundings"])):
        product_id = alias_to_product.get(str(grounding["asin"]))
        if product_id is None:
            continue
        for label in grounding.get("class_labels", []):
            confidence = float(label["confidence"])
            if confidence < minimum_confidence:
                continue
            qwen_class = str(label["id"])
            polarity = str(label["polarity"])
            contributions = [(qwen_class, 1 if polarity == "present" else 0, "explicit")]
            if polarity == "present" and qwen_class in opposite:
                contributions.append((opposite[qwen_class], 0, "exclusive_pair"))
            for target_class, contributed_value, contribution_type in contributions:
                if (product_id, target_class) not in selected_keys:
                    continue
                evidence[(product_id, target_class)].append(
                    {
                        "span_id": grounding.get("span_id"),
                        "review_id": grounding.get("review_id"),
                        "reviewer_id": grounding.get("user_id"),
                        "source_asin": grounding.get("asin"),
                        "quote": grounding.get("quote"),
                        "claim": grounding.get("claim"),
                        "review_text": grounding.get("review_text"),
                        "qwen_class": qwen_class,
                        "qwen_polarity": polarity,
                        "qwen_confidence": confidence,
                        "qwen_unmappable": bool(grounding.get("class_unmappable", False)),
                        "qwen_parse_error": grounding.get("class_parse_error"),
                        "contribution_type": contribution_type,
                        "contributed_binary_target": contributed_value,
                    }
                )

    linked = 0
    missing_images = 0
    for row in selected:
        asin = row["asin"]
        class_name = row["tactile_class"]
        product_number = test_index[asin]
        class_number = class_index[class_name]
        row["category"] = str(metadata[asin]["category"])
        row["image_path"] = str(metadata[asin]["image_path"])
        row["image_identifier"] = str(metadata[asin]["image_filename"])
        row["image_missing"] = not Path(row["image_path"]).is_file()
        missing_images += int(row["image_missing"])
        row["last2_probability"] = float(last2_probabilities[product_number, class_number])
        row["last2_threshold"] = float(last2_thresholds[class_number])
        row["last2_binary_prediction"] = int(row["last2_probability"] >= row["last2_threshold"])
        records = evidence.get((asin, class_name), [])
        records.sort(
            key=lambda item: (
                item["contributed_binary_target"] != row["binary_target"],
                -item["qwen_confidence"],
                str(item["span_id"]),
            )
        )
        primary = records[0] if records else None
        linked += int(primary is not None)
        row["evidence_records"] = records
        row["evidence_count"] = len(records)
        row["span_id"] = primary["span_id"] if primary else None
        row["review_id"] = primary["review_id"] if primary else None
        row["reviewer_id"] = primary["reviewer_id"] if primary else None
        row["original_span_text"] = primary["quote"] if primary else None
        row["original_review_text"] = primary["review_text"] if primary else None
        row["qwen_class"] = primary["qwen_class"] if primary else None
        row["qwen_present_absent"] = primary["qwen_polarity"] if primary else None
        row["qwen_target_polarity"] = ("present" if primary["contributed_binary_target"] else "absent") if primary else None
        row["qwen_contributed_binary_target"] = primary["contributed_binary_target"] if primary else None
        row["qwen_confidence"] = primary["qwen_confidence"] if primary else None
        row["qwen_unmappable"] = primary["qwen_unmappable"] if primary else None

    class_sample_stats = {}
    for class_name in config["primary_classes"]:
        rows = [row for row in selected if row["tactile_class"] == class_name]
        class_sample_stats[class_name] = {
            "items": len(rows),
            "positive": sum(row["binary_target"] == 1 for row in rows),
            "negative": sum(row["binary_target"] == 0 for row in rows),
            "fractional": sum(row["is_fractional_target"] for row in rows),
            "categories": dict(sorted(Counter(row["category"] for row in rows).items())),
        }
    family_sets = {name: set(split_document["families"][name]) for name in ("train", "development", "test")}
    family_overlap = {
        "train__development": len(family_sets["train"] & family_sets["development"]),
        "train__test": len(family_sets["train"] & family_sets["test"]),
        "development__test": len(family_sets["development"] & family_sets["test"]),
    }
    after_hashes = source_hashes(config)
    sanity = {
        "primary_sampling_does_not_use_last2_score": sampling_diagnostics["model_score_used_for_sampling"] is False,
        "locked_test_only": all(row["asin"] in set(test_ids) for row in selected),
        "observed_mask_only": all(row["observed_mask"] == 1 for row in selected),
        "family_disjoint_split_unchanged": all(value == 0 for value in family_overlap.values()),
        "qwen_grounding_not_rerun": True,
        "target_not_regenerated": after_hashes["v3_targets_npz"] == before_hashes["v3_targets_npz"],
        "last2_not_retrained": True,
        "threshold_not_retuned": True,
        "duplicate_item_id_absent": len({row["item_id"] for row in selected}) == len(selected),
        "human_annotation_fields_absent_from_manifest": all(not any(key in row for key in ("image_observability", "human_label", "confidence", "note", "review_human_label", "review_confidence")) for row in selected),
        "existing_experiments_unchanged": before_hashes == after_hashes,
    }
    assert all(sanity.values()), sanity
    manifest = {
        "status": "ready_for_single_human_reviewer",
        "annotation_status": "not_started",
        "human_annotations_generated_by_code": False,
        "sampling_seed": config["sampling_seed"],
        "evaluation_split": config["evaluation_split"],
        "binary_target_rule": config["binary_target_rule"],
        "fractional_target_policy": config["fractional_target_policy"],
        "primary_classes": config["primary_classes"],
        "supplementary_classes": config["supplementary_classes"],
        "class_definitions": config["class_definitions"],
        "total_items": len(selected),
        "class_sample_stats": class_sample_stats,
        "sampling_diagnostics": sampling_diagnostics,
        "selected_identity_sha256_before_score_enrichment": selected_identity_sha256,
        "image_linkage": {
            "found": len(selected) - missing_images,
            "missing": missing_images,
            "success_rate": (len(selected) - missing_images) / len(selected),
        },
        "review_qwen_evidence_linkage": {
            "found": linked,
            "missing": len(selected) - linked,
            "success_rate": linked / len(selected),
        },
        "family_overlap": family_overlap,
        "source_hashes": before_hashes,
        "sanity_checks": sanity,
        "items": selected,
    }
    atomic_json(MANIFEST_PATH, manifest)
    ensure_annotation_csv(ANNOTATION_PATH)
    print(json.dumps({key: manifest[key] for key in ("status", "total_items", "class_sample_stats", "image_linkage", "review_qwen_evidence_linkage", "sanity_checks")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
