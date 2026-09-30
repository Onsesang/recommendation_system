#!/usr/bin/env python3
"""Candidate recall when first-stage lists are merged (rec view, data=all runs).

A target is retrieved by the union of list A (top-a) and list B (top-b) iff its rank in A
is <= a or its rank in B is <= b; all lists use the same seen-item exclusion and the same
recommendable-only ranking, so ranks are directly combinable.  Budget stays 500.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common25 as C
import protocols as P


def main() -> int:
    recommendable = np.load(C.RECOMMENDABLE_MASK)
    out = {}
    for protocol in ("loo", "tsp", "uh"):
        split = P.build(protocol, "all")
        fit = split.refit or split.train
        warm = np.zeros(split.n_items, dtype=bool)
        warm[P.trainable_items(fit)] = True
        content = np.load(C.CACHE / "ranks" / f"content_knn_{protocol}-all.npy")
        per_seed = []
        for path in sorted((C.CACHE / "ranks").glob(f"{protocol}-all-bce-s*.npz")):
            z = np.load(path)
            sel = recommendable[z["targets"]]
            s, p = z["sasrec_rank_rec"][sel], z["popularity_rank_rec"][sel]
            assert s.size == content.size
            w = warm[z["targets"][sel]]
            combos = {
                "sasrec@500": s <= 500,
                "popularity@500": p <= 500,
                "content@500": content <= 500,
                "sasrec@250+content@250": (s <= 250) | (content <= 250),
                "popularity@250+content@250": (p <= 250) | (content <= 250),
                "sasrec@200+pop@100+content@200": (s <= 200) | (p <= 100) | (content <= 200),
            }
            per_seed.append({k: {"all": float(v.mean()), "warm": float(v[w].mean()),
                                 "cold": float(v[~w].mean())} for k, v in combos.items()})
        out[protocol] = {k: {g: float(np.mean([r[k][g] for r in per_seed])) for g in ("all", "warm", "cold")}
                         for k in per_seed[0]}
        out[protocol]["seeds"] = len(per_seed)
        print(protocol, out[protocol], flush=True)
    C.write_json(C.RESULTS / "union_candidates.json", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
