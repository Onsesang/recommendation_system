#!/usr/bin/env python3
"""Build a deterministic, review-complete dense-500 vLLM precision audit."""

from __future__ import annotations

import argparse
import csv
import json
import math
import random
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from audit_app.build_manifest import DEFAULT_IMAGE_ROOT, DEFAULT_PRODUCT_METADATA, load_product_metadata
from material_span.common import ROOT, load_json, read_jsonl, sha256_file
from material_span.simple_m0_m1 import SEOYOUNG_TRAIN, infer_category


DEFAULT_ROOT = ROOT / "data" / "vllm" / "dense_500" / "v2"
DEFAULT_OUTPUT = ROOT / "audit_app" / "data" / "vllm_dense_500_200"
FIELDS = [
    "span_id", "review_id", "asin", "review", "quote", "qwen_accepted",
    "qwen_claim", "qwen_scope", "qwen_property_status", "qwen_intensity",
    "qwen_sentiment", "qwen_evidence_basis", "qwen_visual_observability",
    "qwen_rejection_reason", "human_accepted", "human_claim", "human_scope",
    "human_property_status", "human_visual_observability", "annotator_id", "comment",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--vllm-root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--items", type=int, default=200)
    parser.add_argument("--rejected", type=int, default=80)
    parser.add_argument("--seed", type=int, default=20260813)
    parser.add_argument("--trials", type=int, default=20_000)
    parser.add_argument("--product-metadata", type=Path, default=DEFAULT_PRODUCT_METADATA)
    parser.add_argument("--image-root", type=Path, default=DEFAULT_IMAGE_ROOT)
    return parser.parse_args()


def density_bin(count: int) -> str:
    if count <= 1:
        return "1_user"
    if count <= 3:
        return "2_3_users"
    return "4plus_users"


def balanced_targets(values: list[str], total: int) -> dict[str, int]:
    counts = Counter(values)
    labels = sorted(counts)
    weights = {label: math.sqrt(counts[label]) for label in labels}
    weight_sum = sum(weights.values())
    raw = {label: total * weights[label] / weight_sum for label in labels}
    targets = {label: int(raw[label]) for label in labels}
    remainder = total - sum(targets.values())
    for label in sorted(labels, key=lambda value: (-(raw[value] - targets[value]), value))[:remainder]:
        targets[label] += 1
    return targets


def selection_score(
    rows: list[dict[str, Any]],
    category_targets: dict[bool, dict[str, int]],
    density_targets: dict[bool, dict[str, int]],
) -> tuple[int, int, int, int, tuple[str, ...]]:
    category_error = 0
    missing_categories = 0
    for accepted in (True, False):
        actual = Counter(row["audit_category"] for row in rows if row["accepted"] is accepted)
        category_error += sum(
            abs(actual[label] - target)
            for label, target in category_targets[accepted].items()
        )
        missing_categories += sum(
            actual[label] == 0 for label in category_targets[accepted]
        )
    density_error = 0
    for accepted in (True, False):
        target = density_targets[accepted]
        actual = Counter(row["audit_density_bin"] for row in rows if row["accepted"] is accepted)
        density_error += sum(abs(actual[label] - target[label]) for label in target)
    fingerprint = tuple(sorted(row["span_id"] for row in rows))
    return (
        missing_categories * 100 + category_error + density_error,
        missing_categories,
        category_error,
        density_error,
        fingerprint,
    )


def choose_review_complete(
    rows: list[dict[str, Any]], total: int, rejected_target: int, seed: int, trials: int
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[row["review_id"]].append(row)
    reject_groups = [group for group in grouped.values() if any(row["accepted"] is False for row in group)]
    accept_groups = [group for group in grouped.values() if all(row["accepted"] is True for row in group)]
    accepted_target = total - rejected_target
    category_targets = {
        accepted: balanced_targets(
            [row["audit_category"] for row in rows if row["accepted"] is accepted],
            accepted_target if accepted else rejected_target,
        )
        for accepted in (True, False)
    }
    density_targets = {
        accepted: balanced_targets(
            [row["audit_density_bin"] for row in rows if row["accepted"] is accepted],
            accepted_target if accepted else rejected_target,
        )
        for accepted in (True, False)
    }
    category_counts = Counter(row["audit_category"] for row in rows)
    density_counts = Counter(row["audit_density_bin"] for row in rows)

    def rarity(group: list[dict[str, Any]]) -> float:
        values = []
        for row in group:
            category_weight = math.sqrt(max(category_counts.values()) / category_counts[row["audit_category"]])
            density_weight = math.sqrt(max(density_counts.values()) / density_counts[row["audit_density_bin"]])
            values.append(category_weight * density_weight)
        return max(values)

    def ordered(pool: list[list[dict[str, Any]]], trial: int) -> list[list[dict[str, Any]]]:
        if trial % 3 == 0:
            shuffled = pool.copy()
            rng.shuffle(shuffled)
            return shuffled
        # Efraimidis-Spirakis weighted ordering; rare category/density strata appear earlier.
        return sorted(
            pool,
            key=lambda group: rng.random() ** (1.0 / rarity(group)),
            reverse=True,
        )

    rng = random.Random(seed)
    best: tuple[tuple[int, int, int, int, tuple[str, ...]], list[list[dict[str, Any]]]] | None = None
    for trial in range(trials):
        rejected_pool = ordered(reject_groups, trial)
        chosen: list[list[dict[str, Any]]] = []
        item_count = rejected_count = 0
        for group in rejected_pool:
            group_rejected = sum(row["accepted"] is False for row in group)
            if rejected_count + group_rejected > rejected_target or item_count + len(group) > total:
                continue
            if rng.random() < 0.60 or rejected_count + group_rejected == rejected_target:
                chosen.append(group)
                item_count += len(group)
                rejected_count += group_rejected
                if rejected_count == rejected_target:
                    break
        if rejected_count != rejected_target:
            continue
        accepted_pool = ordered(accept_groups, trial)
        for group in accepted_pool:
            if item_count + len(group) <= total:
                chosen.append(group)
                item_count += len(group)
                if item_count == total:
                    break
        if item_count != total:
            continue
        flat = [row for group in chosen for row in group]
        if sum(row["accepted"] is True for row in flat) != accepted_target:
            continue
        score = selection_score(flat, category_targets, density_targets)
        if best is None or score < best[0]:
            best = (score, chosen)
    if best is None:
        raise RuntimeError(f"Could not select exactly {total} items with {rejected_target} rejects")
    selected = [row for group in best[1] for row in group]
    selected_reviews = {row["review_id"] for row in selected}
    selected = [row for row in rows if row["review_id"] in selected_reviews]
    selected.sort(key=lambda row: (row["audit_category"], row["review_id"], row["review_text"].find(row["quote"]), row["span_id"]))
    return selected, {
        "seed": seed,
        "trials": trials,
        "target_items": total,
        "target_accepted": accepted_target,
        "target_rejected": rejected_target,
        "actual_items": len(selected),
        "actual_accepted": sum(row["accepted"] is True for row in selected),
        "actual_rejected": sum(row["accepted"] is False for row in selected),
        "reviews": len(selected_reviews),
        "category_counts": dict(Counter(row["audit_category"] for row in selected)),
        "density_bin_counts": dict(Counter(row["audit_density_bin"] for row in selected)),
        "category_targets": {str(key): value for key, value in category_targets.items()},
        "density_targets": {str(key): value for key, value in density_targets.items()},
        "selection_score": list(best[0][:4]),
    }


def main() -> None:
    args = parse_args()
    verification_path = args.vllm_root / "semantic_verifications.jsonl"
    input_path = args.vllm_root / "semantic_verification_input.jsonl"
    rows = [row for row in read_jsonl(verification_path) if row.get("status") == "success"]
    if len(rows) != len(read_jsonl(input_path)):
        raise RuntimeError("All verification inputs must pass schema before audit sampling")
    input_by_id = {row["span_id"]: row for row in read_jsonl(input_path)}
    accepted_users: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        if row.get("accepted") is True:
            accepted_users[row["asin"]].add(str(row.get("user_id") or row["review_id"]))
    metadata = {row["asin"]: row for row in load_json(SEOYOUNG_TRAIN)}
    for row in rows:
        title = str(metadata.get(row["asin"], {}).get("title", ""))
        row["audit_category"] = infer_category(title)
        row["audit_evidence_users"] = len(accepted_users[row["asin"]])
        row["audit_density_bin"] = density_bin(row["audit_evidence_users"])
    selected, summary = choose_review_complete(rows, args.items, args.rejected, args.seed, args.trials)

    args.output_root.mkdir(parents=True, exist_ok=True)
    csv_path = args.output_root / "human_semantic_audit.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        for row in selected:
            writer.writerow({
                "span_id": row["span_id"], "review_id": row["review_id"], "asin": row["asin"],
                "review": row["review_text"], "quote": row["quote"], "qwen_accepted": row["accepted"],
                "qwen_claim": row["claim"], "qwen_scope": row["scope"],
                "qwen_property_status": row["property_status"], "qwen_intensity": row["intensity"],
                "qwen_sentiment": row["sentiment"], "qwen_evidence_basis": row["evidence_basis"],
                "qwen_visual_observability": row["visual_observability"],
                "qwen_rejection_reason": row["rejection_reason"], "human_accepted": "",
                "human_claim": "", "human_scope": "", "human_property_status": "",
                "human_visual_observability": "", "annotator_id": "", "comment": "",
            })

    wanted_asins = {row["asin"] for row in selected}
    products = load_product_metadata(args.product_metadata, wanted_asins)
    review_counts = Counter(row["review_id"] for row in selected)
    items = []
    for index, row in enumerate(selected):
        product = products.get(row["asin"], {})
        meta = metadata.get(row["asin"], {})
        local_image = args.image_root / f"{row['asin']}.jpg"
        images = product.get("images") or []
        remote_image = next((image.get("url", "") for image in images if image.get("variant") == "MAIN"), images[0].get("url", "") if images else "")
        source = input_by_id[row["span_id"]]
        items.append({
            "index": index, "span_id": row["span_id"], "review_id": row["review_id"],
            "review_span_total": review_counts[row["review_id"]], "audit_cohort": "vllm_dense_500_stratified",
            "extraction_sources": source.get("extraction_sources", []), "asin": row["asin"],
            "product_title": meta.get("title") or product.get("title", ""), "review": row["review_text"],
            "quote": row["quote"], "audit_category": row["audit_category"],
            "audit_evidence_users": row["audit_evidence_users"], "audit_density_bin": row["audit_density_bin"],
            "qwen": {key: row[key] for key in ("accepted", "claim", "scope", "property_status", "intensity", "sentiment", "evidence_basis", "visual_observability", "rejection_reason")},
            "image": {"local": local_image.is_file(), "remote_url": remote_image, "api_url": f"/api/image/{row['asin']}"},
        })
    manifest = {
        "schema_version": 2, "dataset_version": "vllm_dense_500_stratified_200_review_complete",
        "source_csv": str(csv_path), "source_csv_sha256": sha256_file(csv_path),
        "verification_source": str(verification_path), "verification_source_sha256": sha256_file(verification_path),
        "image_root": str(args.image_root), "item_count": len(items),
        "review_count": len(review_counts), "unique_products": len(wanted_asins),
        "local_image_count": sum(item["image"]["local"] for item in items),
        "sample": summary, "items": items,
    }
    items_path = args.output_root / "items.json"
    items_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (args.output_root / "annotations.json").write_text(
        json.dumps(
            {"schema_version": 1, "revision": 0, "updated_at": None, "annotations": {}},
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (args.output_root / "missing_spans.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "revision": 0,
                "updated_at": None,
                "missing_spans": {},
                "review_checks": {},
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"output": str(args.output_root), **summary, "unique_products": len(wanted_asins), "local_images": manifest["local_image_count"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
