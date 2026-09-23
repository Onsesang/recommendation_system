#!/usr/bin/env python3
"""Build a review-complete v2 audit set from recall-oriented extraction."""

from __future__ import annotations

import argparse
import csv
import json
import random
from collections import defaultdict
from pathlib import Path

from audit_app.build_manifest import (
    DEFAULT_IMAGE_ROOT,
    DEFAULT_PRODUCT_METADATA,
    load_product_metadata,
)
from material_span.common import ROOT, read_jsonl, sha256_file


DEFAULT_V2_ROOT = ROOT / "data" / "v2"
DEFAULT_OLD_AUDIT = (
    ROOT / "experiments" / "02_semantic_verification" / "human_semantic_audit.csv"
)
DEFAULT_OUTPUT_ROOT = ROOT / "audit_app" / "data" / "v2"

FIELDS = [
    "span_id",
    "review_id",
    "asin",
    "review",
    "quote",
    "qwen_accepted",
    "qwen_claim",
    "qwen_scope",
    "qwen_property_status",
    "qwen_intensity",
    "qwen_sentiment",
    "qwen_evidence_basis",
    "qwen_visual_observability",
    "qwen_rejection_reason",
    "human_accepted",
    "human_claim",
    "human_scope",
    "human_property_status",
    "human_visual_observability",
    "annotator_id",
    "comment",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--v2-root", type=Path, default=DEFAULT_V2_ROOT)
    parser.add_argument("--old-audit", type=Path, default=DEFAULT_OLD_AUDIT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--product-metadata", type=Path, default=DEFAULT_PRODUCT_METADATA)
    parser.add_argument("--image-root", type=Path, default=DEFAULT_IMAGE_ROOT)
    parser.add_argument("--recovered-reviews", type=int, default=30)
    parser.add_argument(
        "--target-items",
        type=int,
        default=None,
        help="Select exactly this many spans while keeping every selected review complete.",
    )
    parser.add_argument("--sample-seed", type=int, default=20260809)
    return parser.parse_args()


def select_review_complete_sample(
    rows: list[dict],
    target_items: int,
    recovered: set[str],
    input_by_id: dict[str, dict],
    seed: int,
    trials: int = 20_000,
) -> tuple[list[dict], dict[str, int]]:
    """Choose an exact-size, review-complete, approximately stratified sample."""
    if target_items <= 0:
        raise ValueError("target-items must be positive")
    if target_items > len(rows):
        raise ValueError(
            f"target-items ({target_items}) exceeds available spans ({len(rows)})"
        )
    if target_items == len(rows):
        return rows, {
            "target_items": target_items,
            "new_v2_items": sum(
                "v1" not in input_by_id[row["span_id"]].get("extraction_sources", [])
                for row in rows
            ),
            "qwen_rejected_items": sum(row.get("accepted") is not True for row in rows),
            "recovered_items": sum(row["review_id"] in recovered for row in rows),
        }

    grouped: dict[str, list[dict]] = defaultdict(list)
    review_order: list[str] = []
    for row in rows:
        if row["review_id"] not in grouped:
            review_order.append(row["review_id"])
        grouped[row["review_id"]].append(row)

    def group_stats(review_id: str) -> tuple[int, int, int, int]:
        group = grouped[review_id]
        return (
            len(group),
            sum(
                "v1"
                not in input_by_id[row["span_id"]].get("extraction_sources", [])
                for row in group
            ),
            sum(row.get("accepted") is not True for row in group),
            len(group) if review_id in recovered else 0,
        )

    stats = {review_id: group_stats(review_id) for review_id in review_order}
    total_new = sum(value[1] for value in stats.values())
    total_rejected = sum(value[2] for value in stats.values())
    total_recovered = sum(value[3] for value in stats.values())
    targets = (
        round(total_new * target_items / len(rows)),
        round(total_rejected * target_items / len(rows)),
        round(total_recovered * target_items / len(rows)),
    )

    rng = random.Random(seed)
    best: tuple[tuple[int, int, int, int, tuple[int, ...]], set[str]] | None = None
    rank = {review_id: index for index, review_id in enumerate(review_order)}
    for _ in range(trials):
        shuffled = review_order.copy()
        rng.shuffle(shuffled)
        selected: set[str] = set()
        item_count = 0
        for review_id in shuffled:
            size = stats[review_id][0]
            if item_count + size <= target_items:
                selected.add(review_id)
                item_count += size
                if item_count == target_items:
                    break
        if item_count != target_items:
            continue
        actual = tuple(
            sum(stats[review_id][index] for review_id in selected)
            for index in (1, 2, 3)
        )
        deviations = tuple(abs(value - target) for value, target in zip(actual, targets))
        score = (
            deviations[0] * 3 + deviations[1] * 2 + deviations[2] * 2,
            *deviations,
            tuple(sorted(rank[review_id] for review_id in selected)),
        )
        if best is None or score < best[0]:
            best = (score, selected)
            if score[:4] == (0, 0, 0, 0):
                break
    if best is None:
        raise ValueError(
            f"Could not form a review-complete sample of exactly {target_items} spans"
        )

    selected_ids = best[1]
    sampled = [row for row in rows if row["review_id"] in selected_ids]
    actual_new = sum(
        "v1" not in input_by_id[row["span_id"]].get("extraction_sources", [])
        for row in sampled
    )
    actual_rejected = sum(row.get("accepted") is not True for row in sampled)
    actual_recovered = sum(row["review_id"] in recovered for row in sampled)
    return sampled, {
        "target_items": target_items,
        "sample_seed": seed,
        "new_v2_items": actual_new,
        "new_v2_target": targets[0],
        "qwen_rejected_items": actual_rejected,
        "qwen_rejected_target": targets[1],
        "recovered_items": actual_recovered,
        "recovered_target": targets[2],
    }


def main() -> None:
    args = parse_args()
    verification_path = args.v2_root / "semantic_verifications.jsonl"
    verification_input_path = args.v2_root / "semantic_verification_input.jsonl"
    v2_extraction_path = args.v2_root / "span_extractions.jsonl"
    if not verification_path.is_file():
        raise SystemExit(f"Missing {verification_path}; run recall verification first")
    verifications = [
        row
        for row in read_jsonl(verification_path)
        if row.get("status") == "success"
    ]
    input_by_id = {
        row["span_id"]: row for row in read_jsonl(verification_input_path)
    }
    v2_extractions = read_jsonl(v2_extraction_path)
    v1_extractions = {
        row["review_id"]: row
        for row in read_jsonl(ROOT / "data" / "output" / "span_extractions.jsonl")
    }
    with args.old_audit.open(encoding="utf-8", newline="") as handle:
        old_rows = list(csv.DictReader(handle))
    old_review_order = list(dict.fromkeys(row["review_id"] for row in old_rows))
    accepted_reviews = {
        row["review_id"] for row in verifications if row.get("accepted") is True
    }
    recovered_pool = sorted(
        review["review_id"]
        for review in v2_extractions
        if review["review_id"] in accepted_reviews
        and not v1_extractions.get(review["review_id"], {}).get("evidence")
    )
    recovered = recovered_pool[: args.recovered_reviews]
    selected_reviews = old_review_order + [
        review_id for review_id in recovered if review_id not in set(old_review_order)
    ]
    review_rank = {review_id: index for index, review_id in enumerate(selected_reviews)}
    selected_rows = [
        row for row in verifications if row["review_id"] in review_rank
    ]
    selected_rows.sort(
        key=lambda row: (
            review_rank[row["review_id"]],
            row["review_text"].find(row["quote"]),
            row["span_id"],
        )
    )
    sample_summary = None
    if args.target_items is not None:
        selected_rows, sample_summary = select_review_complete_sample(
            selected_rows,
            args.target_items,
            set(recovered),
            input_by_id,
            args.sample_seed,
        )

    args.output_root.mkdir(parents=True, exist_ok=True)
    audit_csv_path = args.output_root / "human_semantic_audit.csv"
    with audit_csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        for row in selected_rows:
            writer.writerow(
                {
                    "span_id": row["span_id"],
                    "review_id": row["review_id"],
                    "asin": row["asin"],
                    "review": row["review_text"],
                    "quote": row["quote"],
                    "qwen_accepted": row["accepted"],
                    "qwen_claim": row["claim"],
                    "qwen_scope": row["scope"],
                    "qwen_property_status": row["property_status"],
                    "qwen_intensity": row["intensity"],
                    "qwen_sentiment": row["sentiment"],
                    "qwen_evidence_basis": row["evidence_basis"],
                    "qwen_visual_observability": row["visual_observability"],
                    "qwen_rejection_reason": row["rejection_reason"],
                    "human_accepted": "",
                    "human_claim": "",
                    "human_scope": "",
                    "human_property_status": "",
                    "human_visual_observability": "",
                    "annotator_id": "",
                    "comment": "",
                }
            )

    wanted_asins = {row["asin"] for row in selected_rows}
    products = load_product_metadata(args.product_metadata, wanted_asins)
    review_counts: dict[str, int] = {}
    for row in selected_rows:
        review_counts[row["review_id"]] = review_counts.get(row["review_id"], 0) + 1
    items = []
    for index, row in enumerate(selected_rows):
        product = products.get(row["asin"], {})
        local_image = args.image_root / f"{row['asin']}.jpg"
        images = product.get("images") or []
        remote_image = next(
            (image.get("url", "") for image in images if image.get("variant") == "MAIN"),
            images[0].get("url", "") if images else "",
        )
        source = input_by_id.get(row["span_id"], {})
        items.append(
            {
                "index": index,
                "span_id": row["span_id"],
                "review_id": row["review_id"],
                "review_span_total": review_counts[row["review_id"]],
                "audit_cohort": "recovered_from_v1_empty"
                if row["review_id"] in recovered
                else "v1_audit_review",
                "extraction_sources": source.get("extraction_sources", []),
                "asin": row["asin"],
                "product_title": product.get("title", ""),
                "review": row["review_text"],
                "quote": row["quote"],
                "qwen": {
                    "accepted": row["accepted"],
                    "claim": row["claim"],
                    "scope": row["scope"],
                    "property_status": row["property_status"],
                    "intensity": row["intensity"],
                    "sentiment": row["sentiment"],
                    "evidence_basis": row["evidence_basis"],
                    "visual_observability": row["visual_observability"],
                    "rejection_reason": row["rejection_reason"],
                },
                "image": {
                    "local": local_image.is_file(),
                    "remote_url": remote_image,
                    "api_url": f"/api/image/{row['asin']}",
                },
            }
        )
    manifest = {
        "schema_version": 2,
        "dataset_version": "recall_v2_audit_100_review_complete"
        if args.target_items == 100
        else "recall_v2_two_lens_review_complete",
        "source_csv": str(audit_csv_path),
        "source_csv_sha256": sha256_file(audit_csv_path),
        "verification_source": str(verification_path),
        "verification_source_sha256": sha256_file(verification_path),
        "image_root": str(args.image_root),
        "item_count": len(items),
        "review_count": len({item["review_id"] for item in items}),
        "old_audit_review_count": len(
            {item["review_id"] for item in items if item["audit_cohort"] == "v1_audit_review"}
        ),
        "recovered_review_count": len(
            {
                item["review_id"]
                for item in items
                if item["audit_cohort"] == "recovered_from_v1_empty"
            }
        ),
        "recovered_review_ids": sorted(
            {
                item["review_id"]
                for item in items
                if item["audit_cohort"] == "recovered_from_v1_empty"
            }
        ),
        "sample": sample_summary,
        "unique_products": len(wanted_asins),
        "local_image_count": sum(item["image"]["local"] for item in items),
        "items": items,
    }
    items_path = args.output_root / "items.json"
    items_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "items": len(items),
                "reviews": manifest["review_count"],
                "old_audit_reviews": manifest["old_audit_review_count"],
                "recovered_reviews": manifest["recovered_review_count"],
                "new_v2": sum(
                    "v1" not in item.get("extraction_sources", []) for item in items
                ),
                "accepted": sum(item["qwen"]["accepted"] for item in items),
                "rejected": sum(not item["qwen"]["accepted"] for item in items),
                "output": str(items_path),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
