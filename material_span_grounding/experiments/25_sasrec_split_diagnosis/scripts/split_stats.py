#!/usr/bin/env python3
"""How much a collaborative model can learn and reach under each split (no training)."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common25 as C
import protocols as P


def describe(split: P.Split) -> dict:
    train_len = split.train.lengths()
    fit = split.refit or split.train
    trainable_test = np.zeros(split.n_items, dtype=bool)
    trainable_test[P.trainable_items(fit)] = True
    trainable_val = np.zeros(split.n_items, dtype=bool)
    trainable_val[P.trainable_items(split.train)] = True
    recommendable = np.load(C.RECOMMENDABLE_MASK)
    out = {
        "train_events": int(train_len.sum()),
        "train_users_ge2": int((train_len >= 2).sum()),
        "train_pairs": int(np.clip(train_len - 1, 0, None).sum()),
        "mean_train_len_users_ge1": float(train_len[train_len > 0].mean()),
        "trainable_items": int(trainable_val.sum()),
        "trainable_items_for_test_model": int(trainable_test.sum()),
        "universe_items": int(split.universe.sum()),
    }
    for name, ev, trainable in (("validation", split.validation, trainable_val),
                                ("test", split.test, trainable_test)):
        hist = ev.history.lengths()[ev.users]
        rec_target = recommendable[ev.target]
        out[name] = {
            "users": int(ev.users.size),
            "mean_history": float(hist.mean()),
            "median_history": float(np.median(hist)),
            "target_warm_rate": float(trainable[ev.target].mean()),
            "target_recommendable_rate": float(rec_target.mean()),
            "rec_target_users": int(rec_target.sum()),
            "rec_target_warm_rate": float(trainable[ev.target][rec_target].mean()) if rec_target.any() else None,
        }
    return out


def main() -> int:
    table = {}
    for data in ("all", "rec"):
        for protocol in ("loo", "tsp", "uh"):
            split = P.build(protocol, data)
            table[split.name] = describe(split)
            print(split.name, table[split.name], flush=True)
    C.write_json(C.RESULTS / "split_stats.json", table)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
