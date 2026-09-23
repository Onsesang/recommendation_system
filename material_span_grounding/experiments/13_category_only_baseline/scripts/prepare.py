#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

import numpy as np

from common import CONFIG_PATH, ROOT, atomic_json, load_config, pairwise_overlap, read_json, sha256, source_hashes


def main() -> int:
    config = load_config()
    paths = {name: Path(value) for name, value in config["paths"].items()}
    data_config = config["data"]
    metadata_rows = read_json(paths["product_metadata"])
    product_id_field = data_config["product_id_field"]
    family_id_field = data_config["family_id_field"]
    category_field = data_config["category_field"]

    metadata: dict[str, dict[str, str]] = {}
    for row in metadata_rows:
        product_id = str(row[product_id_field])
        assert product_id not in metadata, f"duplicate metadata product: {product_id}"
        # Only these three fields are retained. Titles, paths, reviews and brands are never exposed.
        metadata[product_id] = {
            "product_id": product_id,
            "family_id": str(row[family_id_field]),
            "category": str(row[category_field]),
        }

    split_document = read_json(paths["split_manifest"])
    split = {name: [str(value) for value in split_document["splits"][name]] for name in ("train", "development", "test")}
    expected_counts = data_config["expected_split_counts"]
    assert {name: len(ids) for name, ids in split.items()} == expected_counts
    product_sets = {name: set(ids) for name, ids in split.items()}
    product_overlap = pairwise_overlap(product_sets)
    assert all(value == 0 for value in product_overlap.values()), product_overlap

    all_split_ids = set().union(*product_sets.values())
    assert len(all_split_ids) == data_config["expected_products"]
    assert all_split_ids <= metadata.keys(), "split product is missing from metadata"
    family_sets = {
        name: {metadata[product_id]["family_id"] for product_id in ids}
        for name, ids in split.items()
    }
    family_overlap = pairwise_overlap(family_sets)
    assert all(value == 0 for value in family_overlap.values()), family_overlap
    if "families" in split_document:
        assert family_sets == {name: set(split_document["families"][name]) for name in family_sets}

    with np.load(paths["v3_targets"], allow_pickle=False) as targets:
        target_ids = targets["product_ids"].astype(str)
        classes = targets["classes"].astype(str).tolist()
        assert classes == data_config["expected_classes"]
        assert set(target_ids.tolist()) == all_split_ids
        target_index = {product_id: number for number, product_id in enumerate(target_ids)}
        selected_ids = split["train"] + split["development"]
        selected_indices = np.asarray([target_index[product_id] for product_id in selected_ids], dtype=np.int64)
        values = targets["values"][selected_indices].astype(np.float32)
        masks = targets["mask"][selected_indices].astype(np.uint8)

    train_categories = sorted({metadata[product_id]["category"] for product_id in split["train"]})
    unknown_token = data_config["unknown_token"]
    assert unknown_token not in train_categories
    category_vocabulary = [unknown_token, *train_categories]
    category_to_id = {category: number for number, category in enumerate(category_vocabulary)}
    category_ids = np.asarray(
        [category_to_id.get(metadata[product_id]["category"], 0) for product_id in selected_ids],
        dtype=np.int64,
    )
    split_codes = np.concatenate(
        [np.zeros(len(split["train"]), dtype=np.uint8), np.ones(len(split["development"]), dtype=np.uint8)]
    )
    unknown_counts = {
        name: sum(metadata[product_id]["category"] not in category_to_id for product_id in split[name])
        for name in ("development", "test")
    }

    artifacts = ROOT / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    dataset_path = artifacts / "train_development_only.npz"
    np.savez_compressed(
        dataset_path,
        product_ids=np.asarray(selected_ids),
        category_ids=category_ids,
        values=values,
        mask=masks,
        split_codes=split_codes,
        classes=np.asarray(classes),
    )
    manifest = {
        "status": "complete",
        "purpose": "Leakage barrier: this artifact contains train/development only; no locked-test labels.",
        "source_hashes": source_hashes(config),
        "config_sha256": sha256(CONFIG_PATH),
        "dataset_sha256": sha256(dataset_path),
        "retained_metadata_fields": [product_id_field, family_id_field, category_field],
        "predictive_input_fields": [category_field],
        "category_field": category_field,
        "category_vocabulary": category_vocabulary,
        "category_vocabulary_size_including_unk": len(category_vocabulary),
        "category_vocabulary_built_from": "train only",
        "unknown_category_counts": unknown_counts,
        "dataset_counts": {name: len(ids) for name, ids in split.items()},
        "family_counts": {name: len(values) for name, values in family_sets.items()},
        "product_overlap": product_overlap,
        "family_overlap": family_overlap,
        "classes": classes,
        "locked_test_labels_in_prepared_artifact": False,
        "qwen_grounding_executed": False,
    }
    atomic_json(artifacts / "preparation_manifest.json", manifest)
    print(f"prepared={dataset_path}")
    print(f"vocabulary={category_vocabulary}")
    print(f"unknown_counts={unknown_counts}")
    print(f"family_overlap={family_overlap}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
