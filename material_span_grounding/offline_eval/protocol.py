from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .common import ROOT, save_json, sha256_file, stable_id, write_jsonl


DEFAULT_INTERACTIONS = Path(
    "/home/user/onsesang/seoyoung/data/interim/recommendation_interactions.parquet"
)
DEFAULT_OUTPUT = ROOT / "data/recommendation_eval/temporal_v1"


def _user_cohort(train_length: int) -> str:
    if train_length <= 2:
        return "sparse_history"
    if train_length <= 5:
        return "medium_history"
    return "rich_history"


def _item_cohort(count: int) -> str:
    if count == 0:
        return "cold_start"
    if count <= 5:
        return "long_tail_1_5"
    if count <= 20:
        return "mid_tail_6_20"
    return "head_21_plus"


def build_temporal_protocol(
    *,
    interactions_path: Path = DEFAULT_INTERACTIONS,
    output_root: Path = DEFAULT_OUTPUT,
    min_user_positives: int = 4,
    positive_rating: float = 4.0,
    negatives_per_case: int = 100,
    max_eval_users: int | None = None,
    seed: int = 20260813,
) -> dict[str, Any]:
    if min_user_positives < 3:
        raise ValueError("min_user_positives must be at least 3 for train/validation/test")
    if negatives_per_case < 1:
        raise ValueError("negatives_per_case must be positive")
    interactions_path = Path(interactions_path)
    output_root = Path(output_root)
    frame = pd.read_parquet(
        interactions_path, columns=["user_id", "asin", "rating", "timestamp"]
    )
    source_rows = len(frame)
    frame = frame[
        frame["user_id"].notna()
        & frame["asin"].notna()
        & (frame["rating"].astype(float) >= positive_rating)
    ].copy()
    frame["user_id"] = frame["user_id"].astype(str)
    frame["asin"] = frame["asin"].astype(str)
    frame["timestamp"] = frame["timestamp"].astype("int64")
    frame.sort_values(["user_id", "timestamp", "asin"], inplace=True)
    # Repeated reviews/purchases of one item are one positive; preserve the last time.
    frame.drop_duplicates(["user_id", "asin"], keep="last", inplace=True)

    sequences = {
        str(user): list(zip(values["asin"].tolist(), values["timestamp"].tolist()))
        for user, values in frame.groupby("user_id", sort=True)
    }
    eligible_users = sorted(
        user for user, sequence in sequences.items() if len(sequence) >= min_user_positives
    )
    if max_eval_users is not None and len(eligible_users) > max_eval_users:
        eligible_users.sort(key=lambda user: stable_id(user, seed))
        eligible_users = sorted(eligible_users[:max_eval_users])
    eligible_set = set(eligible_users)

    train_events: list[tuple[int, str]] = []
    heldout: dict[str, tuple[list[tuple[str, int]], tuple[str, int], tuple[str, int]]] = {}
    for user, sequence in sequences.items():
        if user in eligible_set:
            training, validation, test = sequence[:-2], sequence[-2], sequence[-1]
            heldout[user] = (training, validation, test)
            train_events.extend((timestamp, item) for item, timestamp in training)
        else:
            train_events.extend((timestamp, item) for item, timestamp in sequence)

    train_events.sort(key=lambda event: (event[0], event[1]))
    universe = sorted(frame["asin"].unique().tolist())
    preliminary = []
    for user in eligible_users:
        training, validation, test = heldout[user]
        preliminary.append((int(test[1]), user, training, validation, test))
    preliminary.sort(key=lambda row: (row[0], stable_id(row[1], seed)))

    cases = []
    skipped_small_pool = 0
    temporal_counts: Counter[str] = Counter()
    temporal_items: set[str] = set()
    event_index = 0
    for test_timestamp, user, training, validation, test in preliminary:
        while event_index < len(train_events) and train_events[event_index][0] < test_timestamp:
            _, event_item = train_events[event_index]
            temporal_counts[event_item] += 1
            temporal_items.add(event_item)
            event_index += 1
        observed = {item for item, _ in sequences[user]}
        target = test[0]
        # Never sample a negative item that had not entered the train catalog by
        # this user's test time. The positive target is added explicitly and can
        # therefore form a true cold-start case when its temporal count is zero.
        pool = sorted(item for item in temporal_items if item not in observed)
        if len(pool) < negatives_per_case:
            skipped_small_pool += 1
            continue
        weights = np.sqrt(
            np.array([temporal_counts.get(item, 0) + 1 for item in pool], dtype=np.float64)
        )
        weights /= weights.sum()
        case_id = stable_id(user, seed)
        rng = np.random.default_rng(int(case_id[:16], 16))
        negatives = rng.choice(
            np.asarray(pool, dtype=object),
            size=negatives_per_case,
            replace=False,
            p=weights,
        ).tolist()
        candidates = [target, *negatives]
        rng.shuffle(candidates)
        candidate_train_counts = [int(temporal_counts.get(item, 0)) for item in candidates]
        target_count = int(temporal_counts.get(target, 0))
        cases.append(
            {
                "case_id": case_id,
                "train_items": [item for item, _ in training],
                "validation_item": validation[0],
                "test_items": [target],
                "candidates": candidates,
                "candidate_train_counts": candidate_train_counts,
                "test_timestamp": test_timestamp,
                "user_cohort": _user_cohort(len(training)),
                "target_item_train_count": target_count,
                "target_item_cohort": _item_cohort(target_count),
            }
        )

    output_root.mkdir(parents=True, exist_ok=True)
    cases_path = output_root / "cases.jsonl"
    counts_path = output_root / "train_item_counts.json"
    write_jsonl(cases_path, cases)
    final_train_counts = Counter(item for _, item in train_events)
    save_json(counts_path, dict(final_train_counts))
    manifest = {
        "status": "complete",
        "protocol_version": "temporal_leave_two_out_v2",
        "source": str(interactions_path),
        "source_sha256": sha256_file(interactions_path),
        "source_rows": source_rows,
        "positive_rows_after_dedup": len(frame),
        "positive_rating_threshold": positive_rating,
        "min_user_positives": min_user_positives,
        "split": "per-user chronological; last=test, penultimate=validation, earlier=train",
        "eligible_users_before_candidate_check": len(eligible_users),
        "evaluation_cases": len(cases),
        "skipped_small_candidate_pool": skipped_small_pool,
        "item_universe": len(universe),
        "negatives_per_case": negatives_per_case,
        "negative_sampling": (
            "without replacement from items observed before each test timestamp; "
            "sqrt(case-temporal train popularity + 1)"
        ),
        "popularity_scoring": "candidate counts use train events strictly before each test timestamp",
        "candidate_set_size": negatives_per_case + 1,
        "seed": seed,
        "user_id_storage": "SHA-256-derived case_id only; raw user_id not written",
        "cases_sha256": sha256_file(cases_path),
        "train_counts_sha256": sha256_file(counts_path),
        "target_item_cohorts": dict(Counter(row["target_item_cohort"] for row in cases)),
        "user_cohorts": dict(Counter(row["user_cohort"] for row in cases)),
        "leakage_notes": {
            "interaction_split": (
                "validation/test interactions of evaluation users are excluded; popularity and "
                "candidate catalogs use only train events strictly before each case timestamp"
            ),
            "current_tactile_targets": (
                "diagnostic only: current review-derived item targets were built without a global "
                "recommendation time cutoff"
            ),
        },
    }
    save_json(output_root / "manifest.json", manifest)
    return manifest
