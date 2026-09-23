#!/usr/bin/env python3
"""Split the 200-span review-complete audit into two disjoint 100-span sets."""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path

from material_span.common import ROOT, sha256_file


SOURCE_ROOT = ROOT / "audit_app" / "data" / "vllm_dense_500_200"
OUTPUTS = {
    "annotator_a": ROOT / "audit_app" / "data" / "vllm_dense_500_200_a",
    "annotator_b": ROOT / "audit_app" / "data" / "vllm_dense_500_200_b",
}


def exact_partition(items: list[dict]) -> set[str]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for item in items:
        grouped[item["review_id"]].append(item)
    states: dict[tuple[int, int], list[str]] = {(0, 0): []}
    for review_id, group in sorted(grouped.items()):
        size = len(group)
        rejected = sum(item["qwen"]["accepted"] is False for item in group)
        for (item_count, reject_count), selected in list(states.items())[::-1]:
            key = (item_count + size, reject_count + rejected)
            if key[0] <= 100 and key[1] <= 40 and key not in states:
                states[key] = selected + [review_id]
    if (100, 40) not in states:
        raise RuntimeError("No review-complete 100/100 split with 60 accepted and 40 rejected")
    return set(states[(100, 40)])


def ensure_unused(output_root: Path) -> None:
    annotation_path = output_root / "annotations.json"
    if not annotation_path.exists():
        return
    document = json.loads(annotation_path.read_text(encoding="utf-8"))
    if document.get("annotations"):
        raise RuntimeError(f"Refusing to overwrite existing judgments in {output_root}")


def write_split(
    name: str,
    output_root: Path,
    items: list[dict],
    source_manifest: dict,
    csv_by_span: dict[str, dict],
    fieldnames: list[str],
) -> dict:
    ensure_unused(output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    split_items = []
    for index, item in enumerate(items):
        split_items.append({**item, "index": index, "audit_assignment": name})
    csv_path = output_root / "human_semantic_audit.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for item in split_items:
            writer.writerow(csv_by_span[item["span_id"]])
    manifest = {
        **{key: value for key, value in source_manifest.items() if key != "items"},
        "dataset_version": f"vllm_dense_500_stratified_100_{name}_review_complete",
        "assignment": name,
        "parent_manifest": str(SOURCE_ROOT / "items.json"),
        "parent_manifest_sha256": sha256_file(SOURCE_ROOT / "items.json"),
        "source_csv": str(csv_path),
        "source_csv_sha256": sha256_file(csv_path),
        "item_count": len(split_items),
        "review_count": len({item["review_id"] for item in split_items}),
        "unique_products": len({item["asin"] for item in split_items}),
        "local_image_count": sum(item["image"]["local"] for item in split_items),
        "assignment_counts": {
            "accepted": sum(item["qwen"]["accepted"] is True for item in split_items),
            "rejected": sum(item["qwen"]["accepted"] is False for item in split_items),
        },
        "items": split_items,
    }
    (output_root / "items.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (output_root / "annotations.json").write_text(
        json.dumps(
            {"schema_version": 1, "revision": 0, "updated_at": None, "annotations": {}},
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (output_root / "missing_spans.json").write_text(
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
    return {
        "assignment": name,
        "root": str(output_root),
        "items": len(split_items),
        "reviews": manifest["review_count"],
        "products": manifest["unique_products"],
        **manifest["assignment_counts"],
    }


def main() -> None:
    source_manifest = json.loads((SOURCE_ROOT / "items.json").read_text(encoding="utf-8"))
    items = source_manifest["items"]
    with (SOURCE_ROOT / "human_semantic_audit.csv").open(
        encoding="utf-8", newline=""
    ) as handle:
        reader = csv.DictReader(handle)
        fieldnames = reader.fieldnames or []
        csv_by_span = {row["span_id"]: row for row in reader}
    a_reviews = exact_partition(items)
    a_items = [item for item in items if item["review_id"] in a_reviews]
    b_items = [item for item in items if item["review_id"] not in a_reviews]
    summaries = [
        write_split("annotator_a", OUTPUTS["annotator_a"], a_items, source_manifest, csv_by_span, fieldnames),
        write_split("annotator_b", OUTPUTS["annotator_b"], b_items, source_manifest, csv_by_span, fieldnames),
    ]
    a_ids = {item["span_id"] for item in a_items}
    b_ids = {item["span_id"] for item in b_items}
    if a_ids & b_ids or a_ids | b_ids != {item["span_id"] for item in items}:
        raise RuntimeError("Split overlap or coverage failure")
    print(json.dumps({"status": "complete", "assignments": summaries}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

