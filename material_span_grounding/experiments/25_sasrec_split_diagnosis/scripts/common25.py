#!/usr/bin/env python3
"""Paths and constants shared by experiment 25 (SASRec retrieval / split diagnosis)."""
from __future__ import annotations

import json
from pathlib import Path

EXP = Path(__file__).resolve().parents[1]
PROJECT = EXP.parents[1]
ITEM_METADATA = PROJECT / "experiments/16_strong_recommender_tactile/data/item_metadata.parquet"
RECOMMENDABLE = PROJECT / "data/recommendable_fashion_v1"

CACHE = EXP / "cache"
RESULTS = EXP / "results"
LOGS = EXP / "logs"
CHECKPOINTS = EXP / "checkpoints"
for _d in (CACHE, RESULTS, LOGS, CHECKPOINTS):
    _d.mkdir(parents=True, exist_ok=True)

EVENTS = CACHE / "events.parquet"
RECOMMENDABLE_MASK = CACHE / "recommendable_mask.npy"

# exp16b/17b/24 SASRec recipe, unchanged unless a run says otherwise
SEED = 20260917
MAXLEN = 50
DIM = 64
LAYERS = 2
HEADS = 2
DROPOUT = 0.2
BATCH = 256
MIN_HISTORY = 3
K_GRID = [10, 20, 100, 500]


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, default=float))
