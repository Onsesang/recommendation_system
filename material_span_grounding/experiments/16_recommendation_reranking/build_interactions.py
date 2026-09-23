#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pandas as pd

from common import ARTIFACTS, CONFIG_PATH, ROOT, atomic_json, read_json, sha256


def _atomic_parquet(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
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
    profiles_path = ARTIFACTS / "product_tactile_profiles.parquet"
    profiles = pd.read_parquet(profiles_path)
    catalog = set(profiles["item_id"].astype(str))
    official_frames = {}
    raw_counts = {}
    for split, relative in config["official_dataset"]["files"].items():
        path = ROOT / relative
        frame = pd.read_csv(path, dtype={"user_id": str, "parent_asin": str})
        frame.rename(columns={"parent_asin": "item_id"}, inplace=True)
        frame["split"] = split
        official_frames[split] = frame
        raw_counts[split] = {"rows": len(frame), "users": int(frame["user_id"].nunique()), "items": int(frame["item_id"].nunique())}

    eligible_frames = {split: frame[frame["item_id"].isin(catalog)].copy() for split, frame in official_frames.items()}
    events = pd.concat(eligible_frames.values(), ignore_index=True)
    events.sort_values(["split", "user_id", "timestamp", "item_id"], inplace=True)
    _atomic_parquet(events[["user_id", "item_id", "rating", "timestamp", "split"]], ARTIFACTS / "recommendation_splits.parquet")

    histories = {}
    train_events = eligible_frames["train"]
    train_users = set(train_events["user_id"])
    validation_targets = eligible_frames["validation"]
    validation_cases = validation_targets[validation_targets["user_id"].isin(train_users)].copy()
    histories["validation"] = train_events

    pretest_events = pd.concat([eligible_frames["train"], eligible_frames["validation"]], ignore_index=True)
    pretest_users = set(pretest_events["user_id"])
    test_targets = eligible_frames["test"]
    test_cases = test_targets[test_targets["user_id"].isin(pretest_users)].copy()
    histories["test"] = pretest_events

    case_frames = []
    temporal_violations = {}
    target_in_history = {}
    for split, targets in (("validation", validation_cases), ("test", test_cases)):
        history = histories[split]
        selected_users = set(targets["user_id"])
        selected_history = history[history["user_id"].isin(selected_users)].copy()
        counts = selected_history.groupby("user_id").size()
        positive_counts = selected_history[selected_history["rating"] >= 4].groupby("user_id").size()
        last_time = selected_history.groupby("user_id")["timestamp"].max()
        target_lookup = targets.set_index("user_id")
        temporal_violations[split] = int(sum(last_time[user] > int(target_lookup.loc[user, "timestamp"]) for user in selected_users))
        history_pairs = set(zip(selected_history["user_id"], selected_history["item_id"]))
        target_in_history[split] = int(sum((row.user_id, row.item_id) in history_pairs for row in targets.itertuples()))
        cases = targets[["user_id", "item_id", "rating", "timestamp"]].copy()
        cases.rename(columns={"item_id": "target_item", "rating": "target_rating", "timestamp": "target_timestamp"}, inplace=True)
        cases["split"] = split
        cases["history_count"] = cases["user_id"].map(counts).astype(int)
        cases["positive_rating_history_count"] = cases["user_id"].map(positive_counts).fillna(0).astype(int)
        case_frames.append(cases)
    cases = pd.concat(case_frames, ignore_index=True)
    cases.sort_values(["split", "user_id"], inplace=True)
    _atomic_parquet(cases, ARTIFACTS / "evaluation_cases.parquet")

    all_official = pd.concat(official_frames.values(), ignore_index=True)
    all_official_items = set(all_official["item_id"])
    all_official_users = set(all_official["user_id"])
    eligible_users = set(events["user_id"])
    manifest = {
        "status": "complete",
        "data_source": "McAuley-Lab/Amazon-Reviews-2023 official benchmark/0core/last_out",
        "data_semantics": "review/rating interaction treated as implicit positive; not click and not assumed purchase",
        "split_protocol": "official leave-last-out files, unchanged; train history for validation and train+validation history for test",
        "item_id": "parent_asin",
        "catalog": {
            "eligible_items": len(catalog),
            "official_items": len(all_official_items),
            "item_coverage": len(catalog) / len(all_official_items),
            "all_tactile_parents_found_in_official": catalog <= all_official_items,
            "profile_path": str(profiles_path),
            "profile_sha256": sha256(profiles_path),
        },
        "raw": raw_counts,
        "eligible_interactions": {split: len(frame) for split, frame in eligible_frames.items()},
        "eligible_interactions_total": len(events),
        "official_interactions_total": len(all_official),
        "interaction_coverage": len(events) / len(all_official),
        "official_users_total": len(all_official_users),
        "users_with_any_eligible_interaction": len(eligible_users),
        "validation": {
            "raw_users": int(official_frames["validation"]["user_id"].nunique()),
            "target_in_catalog": len(validation_targets),
            "target_coverage": len(validation_targets) / len(official_frames["validation"]),
            "eligible_users_with_train_history": len(validation_cases),
        },
        "test": {
            "raw_users": int(official_frames["test"]["user_id"].nunique()),
            "target_in_catalog": len(test_targets),
            "target_coverage": len(test_targets) / len(official_frames["test"]),
            "eligible_users_with_pretest_history": len(test_cases),
            "target_rating_at_least_4": int((test_cases["rating"] >= 4).sum()),
        },
        "temporal_leakage_checks": {
            "history_after_target": temporal_violations,
            "target_already_in_history": target_in_history,
        },
        "outputs": {
            "events": str(ARTIFACTS / "recommendation_splits.parquet"),
            "cases": str(ARTIFACTS / "evaluation_cases.parquet"),
        },
    }
    if any(temporal_violations.values()) or any(target_in_history.values()):
        raise RuntimeError(f"official split leakage detected: {manifest['temporal_leakage_checks']}")
    atomic_json(ARTIFACTS / "interaction_manifest.json", manifest)
    print(json.dumps({key: manifest[key] for key in ("catalog", "eligible_interactions", "validation", "test", "temporal_leakage_checks")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
