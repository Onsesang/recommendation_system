#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

from common import ARTIFACTS, CONFIG_PATH, atomic_json, read_json, sha256
from recommender_core import history_for_split, load_cases, load_events


def atomic_parquet(frame: pd.DataFrame, path: Path) -> None:
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    os.close(descriptor)
    try:
        frame.to_parquet(temporary, index=False)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main() -> int:
    config = read_json(CONFIG_PATH)
    classes = read_json(ARTIFACTS / "tactile_profile_manifest.json")["classes"]
    products = pd.read_parquet(ARTIFACTS / "product_tactile_profiles.parquet")
    events = load_events()
    product_columns = ["item_id", "category", *classes]
    categories, tactile = [], []
    leakage = {}
    for split in ("validation", "test"):
        cases = load_cases(split)
        users = set(cases["user_id"])
        history = history_for_split(events, split)
        history = history[history["user_id"].isin(users)].merge(products[product_columns], on="item_id", how="inner", validate="many_to_one")
        target_pairs = set(zip(cases["user_id"], cases["target_item"]))
        leakage[split] = sum((row.user_id, row.item_id) in target_pairs for row in history.itertuples())
        category_counts = history.groupby(["user_id", "category"]).size().rename("category_count").reset_index()
        totals = history.groupby("user_id").size().rename("history_count")
        category_counts["preference"] = category_counts["category_count"] / category_counts["user_id"].map(totals)
        category_counts["profile_split"] = split
        categories.append(category_counts)
        all_profile = history.groupby("user_id")[classes].mean()
        all_profile.columns = [f"all_{column}" for column in classes]
        positive = history[history["rating"] >= 4].groupby("user_id")[classes].mean()
        positive.columns = [f"rating4_{column}" for column in classes]
        result = all_profile.join(positive, how="left")
        result["history_count"] = totals
        result["rating4_history_count"] = history[history["rating"] >= 4].groupby("user_id").size()
        result["rating4_history_count"] = result["rating4_history_count"].fillna(0).astype(int)
        result["profile_split"] = split
        result.reset_index(inplace=True)
        tactile.append(result)
    category_frame = pd.concat(categories, ignore_index=True)
    tactile_frame = pd.concat(tactile, ignore_index=True)
    category_path = ARTIFACTS / "user_category_profiles.parquet"
    tactile_path = ARTIFACTS / "user_tactile_profiles.parquet"
    atomic_parquet(category_frame, category_path)
    atomic_parquet(tactile_frame, tactile_path)
    if any(leakage.values()):
        raise RuntimeError(f"target leakage in profiles: {leakage}")
    manifest = {
        "status": "complete", "classes": classes,
        "category_definition": config["category_profile"],
        "primary_tactile_definition": config["tactile_profile"],
        "sensitivity_tactile_definition": "mean of history items whose rating >= 4; missing if none",
        "target_leakage_rows": leakage,
        "category_rows": len(category_frame), "tactile_users": len(tactile_frame),
        "outputs": {
            "category": {"path": str(category_path), "sha256": sha256(category_path)},
            "tactile": {"path": str(tactile_path), "sha256": sha256(tactile_path)},
        },
    }
    atomic_json(ARTIFACTS / "user_profile_manifest.json", manifest)
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
