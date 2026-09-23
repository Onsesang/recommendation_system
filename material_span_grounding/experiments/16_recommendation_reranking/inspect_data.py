#!/usr/bin/env python3
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq

from common import ARTIFACTS, CONFIG_PATH, ROOT, atomic_json, read_json, sha256


def main() -> int:
    config = read_json(CONFIG_PATH)
    official = config["official_dataset"]
    sources = {}
    all_recommendation_ids: set[str] = set()
    for split, relative in official["files"].items():
        path = ROOT / relative
        actual_hash = sha256(path)
        if actual_hash != official["expected_sha256"][split]:
            raise ValueError(f"official {split} SHA-256 mismatch: {actual_hash}")
        frame = pd.read_csv(path, dtype={"user_id": str, "parent_asin": str})
        required = {"user_id", "parent_asin", "rating", "timestamp"}
        if set(frame.columns) != required:
            raise ValueError(f"unexpected {split} columns: {list(frame.columns)}")
        all_recommendation_ids.update(frame["parent_asin"].astype(str))
        sources[split] = {
            "path": str(path),
            "sha256": actual_hash,
            "rows": len(frame),
            "users": int(frame["user_id"].nunique()),
            "items": int(frame["parent_asin"].nunique()),
            "rating_counts": {str(k): int(v) for k, v in sorted(frame["rating"].value_counts().items())},
            "minimum_timestamp": int(frame["timestamp"].min()),
            "maximum_timestamp": int(frame["timestamp"].max()),
        }

    metadata_path = Path(config["tactile_product_metadata"])
    metadata = read_json(metadata_path)
    child_ids = {str(row["product_id"]) for row in metadata}
    parent_ids = {str(row["parent_asin"]) for row in metadata}
    child_counts = Counter(str(row["parent_asin"]) for row in metadata)
    local_path = Path(config["local_interaction_cache"])
    local_schema = pq.ParquetFile(local_path).schema_arrow
    local_frame = pd.read_parquet(local_path, columns=["user_id", "asin", "rating", "timestamp"])
    raw_state = read_json(Path(config["raw_reviews_dataset"]) / "full" / "state.json")
    report = {
        "status": "complete",
        "official_source": {
            "repository": official["repository"],
            "revision": official["revision"],
            "protocol": official["protocol"],
            "semantics": "review/rating implicit interactions; not clicks and not assumed purchases",
            "item_id_column": "parent_asin",
            "splits": sources,
        },
        "raw_reviews": {
            "path": config["raw_reviews_dataset"],
            "dataset_state": raw_state,
            "fields_confirmed": ["rating", "title", "text", "images", "asin", "parent_asin", "user_id", "timestamp", "helpful_vote", "verified_purchase"],
            "verified_purchase_available": True,
        },
        "local_interaction_cache": {
            "path": str(local_path),
            "sha256": sha256(local_path),
            "rows": len(local_frame),
            "users": int(local_frame["user_id"].nunique()),
            "items": int(local_frame["asin"].nunique()),
            "schema": str(local_schema),
            "used_for_primary": False,
        },
        "tactile_products": {
            "metadata_path": str(metadata_path),
            "metadata_sha256": sha256(metadata_path),
            "representation": "product_id is review child ASIN; parent_asin is explicit and product_family_id generally supplies family grouping",
            "child_asin_count": len(child_ids),
            "parent_asin_count": len(parent_ids),
            "parents_with_multiple_children": sum(value > 1 for value in child_counts.values()),
            "maximum_children_per_parent": max(child_counts.values()),
        },
        "id_overlap": {
            "tactile_child_ids_count": len(child_ids),
            "recommendation_parent_ids_count": len(all_recommendation_ids),
            "exact_child_to_recommendation_overlap": len(child_ids & all_recommendation_ids),
            "explicit_parent_mapping_overlap": len(parent_ids & all_recommendation_ids),
            "unmatched_tactile_parent_ids": len(parent_ids - all_recommendation_ids),
            "unmatched_recommendation_ids": len(all_recommendation_ids - parent_ids),
            "mapping_rule": "aggregate available child Last2 continuous probability vectors by explicit parent_asin arithmetic mean",
        },
    }
    atomic_json(ARTIFACTS / "data_overlap_report.json", report)
    print(json.dumps(report["id_overlap"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
