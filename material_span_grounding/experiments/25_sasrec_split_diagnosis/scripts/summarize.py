#!/usr/bin/env python3
"""Collect every finished run into one table with breakdowns and bootstrap intervals."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common25 as C
import protocols as P

BOOT = 1000


def ndcg(r):
    return np.where(r <= 10, 1 / np.log2(r + 1), 0.0)


def boot_ci(values: np.ndarray, seed=C.SEED) -> tuple[float, float]:
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, values.size, size=(BOOT, values.size))
    draws = values[idx].mean(1)
    return float(np.percentile(draws, 2.5)), float(np.percentile(draws, 97.5))


def block(ranks: np.ndarray, pop: np.ndarray) -> dict:
    out = {"users": int(ranks.size)}
    if ranks.size == 0:
        return out
    for k in (10, 100, 500):
        hit = (ranks <= k).astype(float)
        out[f"R@{k}"] = float(hit.mean())
        out[f"R@{k}_ci"] = boot_ci(hit)
        out[f"pop_R@{k}"] = float((pop <= k).mean())
    n = ndcg(ranks)
    out["NDCG@10"] = float(n.mean())
    out["NDCG@10_ci"] = boot_ci(n)
    out["pop_NDCG@10"] = float(ndcg(pop).mean())
    diff = n - ndcg(pop)
    out["NDCG@10_minus_pop_ci"] = boot_ci(diff)
    diff500 = (ranks <= 500).astype(float) - (pop <= 500)
    out["R@500_minus_pop_ci"] = boot_ci(diff500)
    return out


def main() -> int:
    recommendable = np.load(C.RECOMMENDABLE_MASK)
    splits, rows, detail = {}, [], {}
    for path in sorted((C.RESULTS / "runs").glob("*.json")):
        run = json.loads(path.read_text())
        a = run["args"]
        key = (a["protocol"], a["data"])
        if key not in splits:
            s = P.build(*key)
            fit = s.refit or s.train
            warm = np.zeros(s.n_items, dtype=bool)
            warm[P.trainable_items(fit)] = True
            splits[key] = (s, warm)
        split, warm = splits[key]
        z = np.load(C.CACHE / "ranks" / f"{run['tag']}.npz")
        assert np.array_equal(z["users"], split.test.users)
        target = z["targets"]
        hist = split.test.history.lengths()[z["users"]]
        rec_t = recommendable[target]
        views = {
            # the question the user asked: targets we can actually recommend, ranked among them
            "rec_view": (z["sasrec_rank_rec"][rec_t], z["popularity_rank_rec"][rec_t], rec_t),
            "main_view": (z["sasrec_rank_main"], z["popularity_rank_main"], np.ones_like(rec_t)),
        }
        d = {"tag": run["tag"], "best_epoch": run["best_epoch"],
             "top500_pop_overlap": run["sasrec_top500_popularity_overlap"]}
        for vname, (sr, pr, sel) in views.items():
            d[vname] = block(sr, pr)
            w = warm[target][sel]
            d[vname + "_warm"] = block(sr[w], pr[w])
            d[vname + "_cold"] = block(sr[~w], pr[~w])
            h = hist[sel]
            d[vname + "_by_history"] = {
                name: block(sr[m], pr[m]) for name, m in (
                    ("3", h == 3), ("4", h == 4), ("5-9", (h >= 5) & (h <= 9)), ("10+", h >= 10))}
            d[vname + "_warm_share"] = float(w.mean())
        detail[run["tag"]] = d
        rv = d["rec_view"]
        rows.append({
            "tag": run["tag"], "protocol": a["protocol"], "data": a["data"], "loss": a["loss"],
            "seed": a["seed"], "epoch": run["best_epoch"], "users": rv["users"],
            "warm%": 100 * d["rec_view_warm_share"],
            "R@10": rv["R@10"], "NDCG@10": rv["NDCG@10"], "R@100": rv["R@100"], "R@500": rv["R@500"],
            "pop_R@10": rv["pop_R@10"], "pop_NDCG@10": rv["pop_NDCG@10"], "pop_R@500": rv["pop_R@500"],
            "warm_R@500": d["rec_view_warm"].get("R@500"),
            "cold_R@500": d["rec_view_cold"].get("R@500"),
            "overlap": d["top500_pop_overlap"],
            "main_R@500(all targets)": d["main_view"]["R@500"],
            "main_NDCG@10(all targets)": d["main_view"]["NDCG@10"],
        })
    table = pd.DataFrame(rows)
    C.write_json(C.RESULTS / "summary.json", {"rows": rows, "detail": detail})
    pd.set_option("display.width", 300)
    print(table.round(4).to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
