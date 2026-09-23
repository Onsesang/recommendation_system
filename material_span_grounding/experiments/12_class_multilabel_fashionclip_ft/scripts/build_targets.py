#!/usr/bin/env python3
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]


def rows(path: Path):
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                yield json.loads(line)


def main() -> int:
    config = json.loads((ROOT / "config.json").read_text())
    grounding_path = ROOT / "artifacts" / "class_groundings.jsonl"
    products = json.loads(Path(config["product_file"]).read_text())
    product_ids = [str(row["product_id"]) for row in products]
    alias_to_product = {}
    for product in products:
        product_id = str(product["product_id"])
        alias_to_product[product_id] = product_id
        for alias in product.get("alias_product_ids", []):
            alias_to_product[str(alias)] = product_id
    classes = list(config["classes"])
    class_index = {name: index for index, name in enumerate(classes)}
    opposite = {}
    for left, right in config["exclusive_pairs"]:
        opposite[left], opposite[right] = right, left

    # Multiple spans from one reviewer are collapsed before product aggregation.
    reviewer_evidence: dict[tuple[str, str, str], list[tuple[float, float, str]]] = defaultdict(list)
    minimum = float(config["minimum_confidence"])
    for row in rows(grounding_path):
        source_asin = str(row["asin"])
        product_id = alias_to_product.get(source_asin)
        if product_id is None:
            continue
        reviewer_id = str(row.get("user_id") or row.get("review_id"))
        for item in row.get("class_labels", []):
            confidence = float(item["confidence"])
            if confidence < minimum:
                continue
            class_id = str(item["id"])
            value = 1.0 if item["polarity"] == "present" else 0.0
            reviewer_evidence[(product_id, reviewer_id, class_id)].append((value, confidence, "explicit"))
            # A present atomic class supplies a negative only for its declared
            # incompatible counterpart. Absence never implies the counterpart.
            if value == 1.0 and class_id in opposite:
                reviewer_evidence[(product_id, reviewer_id, opposite[class_id])].append((0.0, confidence, "exclusive_pair"))

    reviewer_values: dict[tuple[str, str], list[tuple[float, float]]] = defaultdict(list)
    reviewer_rows = []
    for (product_id, reviewer_id, class_id), evidence in reviewer_evidence.items():
        weights = np.asarray([item[1] for item in evidence], dtype=np.float64)
        values = np.asarray([item[0] for item in evidence], dtype=np.float64)
        value = float(np.average(values, weights=weights))
        confidence = float(np.mean(weights))
        reviewer_values[(product_id, class_id)].append((value, confidence))
        reviewer_rows.append({
            "product_id": product_id, "reviewer_id": reviewer_id,
            "class_id": class_id, "value": value, "confidence": confidence,
            "evidence_count": len(evidence),
        })

    values = np.zeros((len(product_ids), len(classes)), dtype=np.float32)
    mask = np.zeros_like(values, dtype=np.uint8)
    support = np.zeros_like(values, dtype=np.int32)
    agreement = np.full_like(values, np.nan, dtype=np.float32)
    product_rows = []
    for product_number, product_id in enumerate(product_ids):
        for class_id in classes:
            evidence = reviewer_values.get((product_id, class_id), [])
            if not evidence:
                continue
            observed = np.asarray([item[0] for item in evidence], dtype=np.float32)
            confidence = np.asarray([item[1] for item in evidence], dtype=np.float32)
            target = float(np.average(observed, weights=confidence))
            class_number = class_index[class_id]
            values[product_number, class_number] = target
            mask[product_number, class_number] = 1
            support[product_number, class_number] = len(observed)
            agreement_value = float(1.0 - 2.0 * min(target, 1.0 - target))
            agreement[product_number, class_number] = agreement_value
            product_rows.append({
                "product_id": product_id, "class_id": class_id,
                "target_probability": target, "mask": 1,
                "reviewer_support": len(observed), "agreement": agreement_value,
            })

    artifacts = ROOT / "artifacts"
    with (artifacts / "reviewer_class_targets.jsonl").open("w", encoding="utf-8") as handle:
        for row in reviewer_rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    with (artifacts / "product_class_targets.jsonl").open("w", encoding="utf-8") as handle:
        for row in product_rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    np.savez_compressed(
        artifacts / "product_class_targets.npz",
        product_ids=np.asarray(product_ids), classes=np.asarray(classes),
        values=values, mask=mask, support=support, agreement=agreement,
    )
    positives = ((values >= 0.5) & mask.astype(bool)).sum(axis=0)
    negatives = ((values < 0.5) & mask.astype(bool)).sum(axis=0)
    manifest = {
        "status": "complete", "products": len(product_ids),
        "classes": classes, "observed_pairs": int(mask.sum()),
        "positive_by_class": dict(zip(classes, map(int, positives))),
        "negative_by_class": dict(zip(classes, map(int, negatives))),
        "reviewer_first": True, "unobserved_is_negative": False,
    }
    (ROOT / "manifests").mkdir(exist_ok=True)
    (ROOT / "manifests" / "build_targets.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
