#!/usr/bin/env python3
"""PART B - aggregate review-level pseudo-labels to product level and audit them.

The aggregation rule is fixed in config.json and uses training-pool statistics
only; no evaluation split is inspected here.
"""
from __future__ import annotations

import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import ROOT, load_config  # noqa: E402

RESULTS = ROOT / "results" / "fabricvst_taxonomy_retraining"


def iter_jsonl(path: Path):
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                yield json.loads(line)


def write_table(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    config = load_config()
    RESULTS.mkdir(parents=True, exist_ok=True)
    rules = config["retraining"]["aggregation"]
    attributes = config["retraining"]["attribute_groups"]["A_fabricvst_24"]
    min_confidence = float(rules["min_confidence"])
    min_evidence = int(rules["min_evidence_count"])
    margin = float(rules["margin"])

    labels_path = ROOT / "artifacts" / "qwen_fabricvst_labels.jsonl"
    rows = list(iter_jsonl(labels_path))
    print(f"review label rows: {len(rows)}", flush=True)

    # ---- review-level distribution ---------------------------------------
    review_counts = {name: {"positive": 0, "negative": 0} for name in attributes}
    parse_errors = 0
    unmapped = 0
    evidence_total = evidence_verbatim = 0
    for row in rows:
        if row.get("parse_error"):
            parse_errors += 1
        if row.get("unmapped"):
            unmapped += 1
        for name, payload in row["attributes"].items():
            if name not in review_counts:
                continue
            review_counts[name][payload["label"]] += 1
            if payload.get("evidence"):
                evidence_total += 1
                evidence_verbatim += int(bool(payload.get("evidence_verbatim")))

    # ---- product-level aggregation ---------------------------------------
    per_product: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        per_product[row["asin"]].append(row)

    # Reviews filtered out before Qwen contribute no evidence, exactly like a
    # review Qwen read and found nothing in.
    all_reviews = list(iter_jsonl(Path(config["retraining"]["review_pool"])))
    reviews_per_product: dict[str, int] = defaultdict(int)
    for row in all_reviews:
        reviews_per_product[row["asin"]] += 1

    image_root = Path(config["retraining"]["image_root"])
    products = sorted(set(per_product) | {row["asin"] for row in all_reviews})
    values = np.zeros((len(products), len(attributes)), dtype=np.float32)
    mask = np.zeros((len(products), len(attributes)), dtype=np.float32)
    confidences = np.zeros((len(products), len(attributes)), dtype=np.float32)

    product_rows = []
    for p_index, asin in enumerate(products):
        labelled = per_product.get(asin, [])
        record = {
            "product_id": asin,
            "image_id": asin,
            "image_exists": int((image_root / f"{asin}.jpg").is_file()),
            "review_count": reviews_per_product.get(asin, 0),
            "reviews_labelled": len(labelled),
        }
        for a_index, name in enumerate(attributes):
            positive_weight = negative_weight = 0.0
            positive_n = negative_n = 0
            for row in labelled:
                payload = row["attributes"].get(name)
                if not payload or payload["confidence"] < min_confidence:
                    continue
                if payload["label"] == "positive":
                    positive_weight += payload["confidence"]
                    positive_n += 1
                else:
                    negative_weight += payload["confidence"]
                    negative_n += 1
            known = positive_n + negative_n
            total_weight = positive_weight + negative_weight
            if known < min_evidence or total_weight <= 0:
                label, confidence = "unknown", 0.0
            else:
                score = (positive_weight - negative_weight) / total_weight
                if score > margin:
                    label, confidence = "positive", abs(score)
                elif score < -margin:
                    label, confidence = "negative", abs(score)
                else:
                    label, confidence = "unknown", 0.0
            if label != "unknown":
                mask[p_index, a_index] = 1.0
                values[p_index, a_index] = 1.0 if label == "positive" else 0.0
                confidences[p_index, a_index] = confidence
            record[f"{name}__positive"] = positive_n
            record[f"{name}__negative"] = negative_n
            record[f"{name}__unknown"] = record["review_count"] - known
            record[f"{name}__label"] = label
            record[f"{name}__confidence"] = round(confidence, 4)
        product_rows.append(record)

    write_table(RESULTS / "product_level_labels.csv", product_rows)
    np.savez(
        ROOT / "artifacts" / "product_fabricvst_targets.npz",
        product_ids=np.asarray(products),
        attributes=np.asarray(attributes),
        values=values,
        mask=mask,
        confidences=confidences,
    )

    # ---- quality inspection ----------------------------------------------
    split = json.loads(Path(config["retraining"]["split_manifest"]).read_text())["splits"]
    index = {value: number for number, value in enumerate(products)}
    train_index = np.asarray([index[v] for v in split["train"] if v in index], dtype=int)

    distribution = []
    for a_index, name in enumerate(attributes):
        observed = mask[:, a_index] > 0
        positives = int(values[observed, a_index].sum())
        train_observed = mask[train_index, a_index] > 0
        train_positive = int(values[train_index][train_observed, a_index].sum())
        distribution.append({
            "attribute": name,
            "review_positive": review_counts[name]["positive"],
            "review_negative": review_counts[name]["negative"],
            "product_positive": positives,
            "product_negative": int(observed.sum()) - positives,
            "product_unknown": int(len(products) - observed.sum()),
            "known_ratio": round(float(observed.mean()), 4),
            "positive_ratio_among_known": round(float(positives / max(int(observed.sum()), 1)), 4),
            "train_known": int(train_observed.sum()),
            "train_positive": train_positive,
            "train_positive_ratio": round(float(train_positive / max(int(train_observed.sum()), 1)), 4),
        })
    write_table(RESULTS / "qwen_label_distribution.csv", distribution)

    sparse = [row["attribute"] for row in distribution if row["known_ratio"] < 0.05]
    skewed = [
        row["attribute"] for row in distribution
        if row["known_ratio"] >= 0.05 and (row["positive_ratio_among_known"] > 0.95 or row["positive_ratio_among_known"] < 0.05)
    ]
    summary = {
        "review_rows": len(rows),
        "parse_errors": parse_errors,
        "reviews_with_no_attribute": unmapped,
        "evidence_spans": evidence_total,
        "evidence_verbatim_fraction": round(evidence_verbatim / max(evidence_total, 1), 4),
        "products": len(products),
        "products_with_image": int(sum(row["image_exists"] for row in product_rows)),
        "aggregation_rule": rules,
        "sparse_attributes_known_ratio_below_5pct": sparse,
        "severely_skewed_attributes": skewed,
    }
    (RESULTS / "label_quality_summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))
    print("\nattribute distribution (product level):")
    for row in distribution:
        print(
            f"  {row['attribute']:>16} known={row['known_ratio']:.3f} "
            f"pos_ratio={row['positive_ratio_among_known']:.3f} "
            f"P={row['product_positive']:5d} N={row['product_negative']:5d} U={row['product_unknown']:5d}"
        )
    (ROOT / "manifests" / "04_aggregate_labels.json").write_text(
        json.dumps({"status": "complete", "results": str(RESULTS)}, indent=2) + "\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
