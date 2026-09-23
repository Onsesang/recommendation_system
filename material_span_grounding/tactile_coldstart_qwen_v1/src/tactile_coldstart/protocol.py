from __future__ import annotations

import random
from collections import defaultdict
from pathlib import Path
from typing import Any

from .common import (
    PATHS, load_experiment, load_taxonomy, read_json, read_jsonl, sha256_file,
    utc_now, write_json,
)


def document_taxonomy() -> dict[str, Any]:
    taxonomy = load_taxonomy()
    config = load_experiment()
    path = PATHS.configs / "tactile_axes.yaml"
    manifest = {
        "status": "complete",
        "phase": 1,
        "generated_at": utc_now(),
        "taxonomy_version": taxonomy["version"],
        "candidate_axes": [str(axis["id"]) for axis in taxonomy["axes"]],
        "axis_count": len(taxonomy["axes"]),
        "taxonomy": str(path),
        "taxonomy_sha256": sha256_file(path),
        "selection_policy": config["diagnostics"],
        "active_axis_selection_deferred_to_phase3": True,
    }
    write_json(PATHS.manifests / "phase1_taxonomy.json", manifest)
    lines = [
        "# Phase 1 — Configurable Tactile Taxonomy", "",
        f"Taxonomy version: `{taxonomy['version']}`. Candidate axes are declarative; the active subset is selected only by Phase 3 diagnostics.", "",
        "| Axis | Negative pole | Positive pole | Definition |", "|---|---|---|---|",
    ]
    for axis in taxonomy["axes"]:
        lines.append(f"| {axis['id']} | {axis['negative_pole']} | {axis['positive_pole']} | {axis['definition']} |")
    (PATHS.reports / "phase1_taxonomy.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return manifest


def build_protocol() -> dict[str, Any]:
    config = load_experiment()
    taxonomy = load_taxonomy()
    inputs = {key: Path(value) for key, value in config["inputs"].items() if key != "image_root"}
    missing = [str(path) for path in inputs.values() if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"Missing protocol inputs: {missing}")
    verifications = read_jsonl(inputs["semantic_verifications"])
    reviews = read_jsonl(inputs["reviews"])
    product_master = read_json(inputs["product_master"])
    verification_manifest = read_json(inputs["verification_manifest"])
    accepted = [row for row in verifications if row.get("accepted") is True]

    by_category: dict[str, list[str]] = defaultdict(list)
    for row in product_master:
        by_category[str(row["category"])].append(str(row["product_id"]))
    ratios = config["experiment"]["ratios"]
    split_manifests = []
    for seed in config["experiment"]["split_seeds"]:
        rng = random.Random(int(seed))
        splits = {"train": [], "development": [], "test": []}
        for category, product_ids in sorted(by_category.items()):
            values = sorted(product_ids)
            rng.shuffle(values)
            count = len(values)
            development_count = max(1, round(count * float(ratios["development"]))) if count >= 3 else 0
            test_count = max(1, round(count * float(ratios["test"]))) if count >= 3 else 0
            train_count = count - development_count - test_count
            splits["train"].extend(values[:train_count])
            splits["development"].extend(values[train_count:train_count + development_count])
            splits["test"].extend(values[train_count + development_count:])
        for values in splits.values():
            values.sort()
        flattened = sum(splits.values(), [])
        if len(flattened) != len(set(flattened)):
            raise RuntimeError("Product family leakage in split")
        payload = {
            "seed": int(seed),
            "unit": "deduplicated_product_family",
            "splits": splits,
            "counts": {name: len(values) for name, values in splits.items()},
            "independent_final_test": False,
            "warning": "All current 465 families were previously available during prototype development; use as feasibility splits only.",
        }
        path = PATHS.manifests / f"family_split_{seed}.json"
        write_json(path, payload)
        split_manifests.append({"path": str(path), "sha256": sha256_file(path), "counts": payload["counts"]})

    manifest = {
        "status": "complete",
        "phase": 0,
        "generated_at": utc_now(),
        "experiment": config["experiment"],
        "taxonomy_version": taxonomy["version"],
        "semantic_labeler": config["semantic_labeler"],
        "source": {
            "reviews": len(reviews),
            "review_products": len({str(row["asin"]) for row in reviews}),
            "verification_rows": len(verifications),
            "accepted_claims": len(accepted),
            "rejected_claims": len(verifications) - len(accepted),
            "product_families": len(product_master),
            "qwen_manifest_model": verification_manifest.get("model"),
            "qwen_manifest_model_path": verification_manifest.get("model_path"),
        },
        "input_hashes": {key: sha256_file(path) for key, path in inputs.items()},
        "splits": split_manifests,
        "leakage_policy": {
            "test_reviews_hidden_from_training": True,
            "review_unobserved_is_not_neutral": True,
            "existing_70_product_test_is_not_independent_final_test": True,
        },
    }
    write_json(PATHS.manifests / "phase0_protocol.json", manifest)
    report = f"""# Phase 0 — Protocol Freeze\n\n- Reviews: {len(reviews):,}\n- Exact span verification rows: {len(verifications):,}\n- Qwen-accepted claims: {len(accepted):,}\n- Deduplicated visible product families: {len(product_master):,}\n- Qwen: `{config['semantic_labeler']['model_id']}` / `{config['semantic_labeler']['snapshot']}`\n- Taxonomy: `{taxonomy['version']}`\n\n## Leakage boundary\n\nCurrent family splits are feasibility splits. The prior 70-product test has already been inspected, and all current families existed during prototype development. A paper-level independent Amazon test requires newly sampled, previously unused product families. Test reviews in these feasibility splits are nevertheless hidden from model training, calibration, and query construction.\n"""
    (PATHS.reports / "phase0_protocol.md").write_text(report, encoding="utf-8")
    return manifest
