#!/usr/bin/env python3
"""Data-side factors behind weak SASRec retrieval (no model needed).

  duplicates   is a cold target really a relisting of a product the model did learn?
               (another parent_asin with the same normalised title that is trainable)
  popularity   training count of test targets
  leakage      share of training events that happen after the user's test target
  category     does the target's category appear in the user's history?
  kcore        how big Amazon_Fashion stays if filtered to 5-core like published benchmarks
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common25 as C
import protocols as P

NON_WORD = re.compile(r"[^a-z0-9]+")


def normalise(title: str) -> str:
    return NON_WORD.sub(" ", str(title).lower()).strip()


def kcore(events: pd.DataFrame, k: int) -> pd.DataFrame:
    frame = events[["uid", "iid"]]
    while True:
        users = frame["uid"].map(frame["uid"].value_counts())
        items = frame["iid"].map(frame["iid"].value_counts())
        keep = (users >= k) & (items >= k)
        if keep.all():
            return frame
        frame = frame[keep]


def main() -> int:
    meta = pd.read_parquet(C.ITEM_METADATA, columns=["iid", "title", "category"]).sort_values("iid")
    title_key = pd.factorize(meta["title"].map(normalise))[0]
    category = meta["category"].to_numpy()
    recommendable = np.load(C.RECOMMENDABLE_MASK)
    events = pd.read_parquet(C.EVENTS)
    out = {"catalog": {
        "items": len(meta),
        "items_sharing_title_with_another": float(pd.Series(title_key).duplicated(keep=False).mean()),
        "distinct_titles": int(title_key.max() + 1),
    }}

    for data in ("all", "rec"):
        for protocol in ("loo", "tsp", "uh"):
            split = P.build(protocol, data)
            fit = split.refit or split.train
            trainable = np.zeros(split.n_items, dtype=bool)
            trainable[P.trainable_items(fit)] = True
            count = np.bincount(fit.flat, minlength=split.n_items)
            warm_titles = np.zeros(title_key.max() + 1, dtype=bool)
            warm_titles[title_key[trainable]] = True
            ev = split.test
            target = ev.target
            cold = ~trainable[target]
            relisted = cold & warm_titles[title_key[target]]
            hist_cats = [set(category[ev.history.row(u)]) for u in ev.users]
            same_cat = np.array([category[t] in cats for t, cats in zip(target, hist_cats)])
            buckets = pd.Series(pd.cut(count[target], [-1, 0, 1, 4, 19, np.inf],
                             labels=["0", "1", "2-4", "5-19", "20+"])).value_counts(normalize=True)
            entry = {
                "users": int(target.size),
                "target_cold": float(cold.mean()),
                "cold_target_with_warm_same_title": float(relisted.mean()),
                "warm_ceiling_if_relistings_merged": float((~cold | relisted).mean()),
                "target_train_count_share": {k: float(v) for k, v in buckets.sort_index().items()},
                "target_category_in_history": float(same_cat.mean()),
                "target_recommendable": float(recommendable[target].mean()),
            }
            if protocol == "loo":
                # training events that happen after the user's own test target
                target_ts = events[events["loo"] == 2].set_index("uid")["ts"]
                t = target_ts.reindex(ev.users).to_numpy()
                train_ts = np.sort(events.loc[events["loo"] == 0, "ts"].to_numpy())
                after = 1 - np.searchsorted(train_ts, t, side="right") / train_ts.size
                entry["train_events_after_target_mean_share"] = float(after.mean())
                entry["users_with_any_train_event_after_target"] = float((after > 0).mean())
            out[split.name] = entry
            print(split.name, entry, flush=True)

    for data in ("all", "rec"):
        frame = events if data == "all" else events[events["rec"]]
        core = kcore(frame, 5)
        out[f"5core-{data}"] = {"events": len(core), "users": int(core.uid.nunique()),
                               "items": int(core.iid.nunique())}
        print(f"5core-{data}", out[f"5core-{data}"], flush=True)
    C.write_json(C.RESULTS / "factor_stats.json", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
