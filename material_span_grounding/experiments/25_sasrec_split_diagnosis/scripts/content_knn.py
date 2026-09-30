#!/usr/bin/env python3
"""Can item content reach the cold targets that ID-based SASRec cannot?

No training: the user query is the mean L2-normalised image feature (exp16 SMORE
image_feat.npy, 512-d) of the user's history, every item is scored by cosine, seen items
removed, ranked over recommendable items (same "rec view" as summarize.py).
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import torch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common25 as C
import protocols as P

FEATURES = C.PROJECT / "experiments/16_strong_recommender_tactile/data/smore/image_feat.npy"


@torch.inference_mode()
def main() -> int:
    device = torch.device("cuda")
    feats = np.load(FEATURES, mmap_mode="r")
    catalog = torch.empty(feats.shape, dtype=torch.float16, device=device)
    for i in range(0, feats.shape[0], 100_000):
        block = torch.as_tensor(np.asarray(feats[i:i + 100_000]), device=device)
        catalog[i:i + 100_000] = torch.nn.functional.normalize(block, dim=1).half()
    has_feature = (catalog.float().norm(dim=1) > 0).cpu().numpy()
    recommendable = np.load(C.RECOMMENDABLE_MASK)
    excluded = torch.as_tensor(~recommendable, device=device)
    index = torch.arange(catalog.shape[0], device=device)
    out = {"items_with_feature": float(has_feature.mean())}
    for protocol in ("loo", "tsp", "uh"):
        split = P.build(protocol, "all")
        fit = split.refit or split.train
        warm = np.zeros(split.n_items, dtype=bool)
        warm[P.trainable_items(fit)] = True
        ev = split.test
        keep = recommendable[ev.target]
        users, targets = ev.users[keep], ev.target[keep]
        ranks = np.zeros(users.size, dtype=np.int64)
        for b in range(0, users.size, 256):
            u = users[b:b + 256]
            q = torch.stack([catalog[torch.as_tensor(ev.history.row(x), device=device)].float().mean(0)
                             for x in u])
            scores = (q.half() @ catalog.T).float().masked_fill(excluded, -torch.inf)
            for k, x in enumerate(u):
                scores[k, torch.as_tensor(ev.history.row(x), device=device)] = -torch.inf
            t = torch.as_tensor(targets[b:b + 256], device=device)
            ts = scores.gather(1, t[:, None])
            ranks[b:b + 256] = (1 + (scores > ts).sum(1)
                                + ((scores == ts) & (index[None] < t[:, None])).sum(1)).cpu().numpy()
        w = warm[targets]
        res = {}
        for name, m in (("all", np.ones_like(w)), ("warm", w), ("cold", ~w)):
            r = ranks[m]
            res[name] = {"users": int(r.size),
                         **{f"R@{k}": float((r <= k).mean()) for k in (10, 100, 500)},
                         "NDCG@10": float(np.where(r <= 10, 1 / np.log2(r + 1), 0).mean())}
        out[f"{protocol}-all"] = res
        np.save(C.CACHE / "ranks" / f"content_knn_{protocol}-all.npy", ranks)
        print(protocol, res, flush=True)
    C.write_json(C.RESULTS / "content_knn.json", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
