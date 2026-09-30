#!/usr/bin/env python3
"""Build one event table carrying both official split labels and the recommendable flag.

Sources (all pinned):
  * Amazon Reviews'23 Amazon_Fashion 0core/last_out  -> column ``loo``
  * Amazon Reviews'23 Amazon_Fashion 0core/timestamp -> column ``tsp``
  * exp16 item_metadata.parquet (iid 0..825,868, same ids as exp16/17/24)
  * recommendable_fashion_v1/items.parquet (``source_iid`` = exp16 iid)

Both splits contain the same 2,474,375 (user, parent_asin) events; this script
checks that before joining them.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common25 as C

SPLITS = {"loo": C.PROJECT / "data/amazon_fashion_0core_last_out",
          "tsp": C.PROJECT / "data/amazon_fashion_0core_timestamp"}
LABEL = {"train": 0, "valid": 1, "test": 2}


def read_split(folder: Path) -> pd.DataFrame:
    parts = []
    for name, code in LABEL.items():
        frame = pd.read_csv(folder / f"Amazon_Fashion.{name}.csv",
                            dtype={"user_id": str, "parent_asin": str})
        frame["label"] = np.int8(code)
        parts.append(frame)
    return pd.concat(parts, ignore_index=True)


def main() -> int:
    loo = read_split(SPLITS["loo"])
    tsp = read_split(SPLITS["tsp"])
    key = ["user_id", "parent_asin", "timestamp"]
    assert not loo.duplicated(["user_id", "parent_asin"]).any()
    merged = loo.merge(tsp[key + ["label"]], on=key, how="outer",
                       suffixes=("_loo", "_tsp"), indicator=True)
    assert (merged["_merge"] == "both").all(), merged["_merge"].value_counts()

    meta = pd.read_parquet(C.ITEM_METADATA, columns=["iid", "parent_asin", "category", "title"])
    asin_to_iid = pd.Series(meta["iid"].to_numpy(), index=meta["parent_asin"])
    merged["iid"] = merged["parent_asin"].map(asin_to_iid)
    assert merged["iid"].notna().all(), "event on an item missing from item_metadata"
    merged["iid"] = merged["iid"].astype(np.int64)
    merged["uid"] = pd.factorize(merged["user_id"], sort=True)[0].astype(np.int64)

    rec = pd.read_parquet(C.RECOMMENDABLE / "items.parquet", columns=["source_iid"])
    recommendable = np.zeros(len(meta), dtype=bool)
    recommendable[rec["source_iid"].to_numpy()] = True

    events = pd.DataFrame({
        "uid": merged["uid"], "iid": merged["iid"],
        "ts": merged["timestamp"].astype(np.int64),
        "loo": merged["label_loo"].astype(np.int8), "tsp": merged["label_tsp"].astype(np.int8),
        "rec": recommendable[merged["iid"].to_numpy()],
    }).sort_values(["uid", "ts", "iid"], kind="mergesort").reset_index(drop=True)
    events.to_parquet(C.EVENTS, index=False)
    np.save(C.RECOMMENDABLE_MASK, recommendable)

    # the absolute cut points the official timestamp split used
    cut = {name: {"min_ts": int(events.loc[events.tsp == code, "ts"].min()),
                  "max_ts": int(events.loc[events.tsp == code, "ts"].max())}
           for name, code in LABEL.items()}
    summary = {
        "events": len(events), "users": int(events.uid.nunique()),
        "items_catalog": len(meta), "items_recommendable": int(recommendable.sum()),
        "events_on_recommendable": int(events.rec.sum()),
        "loo_counts": events.loo.value_counts().sort_index().tolist(),
        "tsp_counts": events.tsp.value_counts().sort_index().tolist(),
        "tsp_ranges": cut,
    }
    C.write_json(C.RESULTS / "prepare_summary.json", summary)
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
