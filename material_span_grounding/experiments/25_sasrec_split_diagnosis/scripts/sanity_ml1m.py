#!/usr/bin/env python3
"""Is the SASRec code itself sound?  Run the same (verbatim exp16b) SASRec on MovieLens-1M,
the dense benchmark of the SASRec paper, with the paper's leave-one-out protocol.

Paper (Kang & McAuley 2018, 100 sampled negatives): HR@10 0.8245, NDCG@10 0.5905.
Published full-ranking re-runs of BCE SASRec on ML-1M report NDCG@10 around 0.13
(gSASRec, RecSys'23).  Both protocols are reported here.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import torch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common25 as C
import models25 as M

MAXLEN = 200
DIM = 50


def main() -> int:
    device = torch.device("cuda")
    ratings = pd.read_csv(C.CACHE / "ml1m/ml-1m/ratings.dat", sep="::", engine="python",
                          names=["user", "item", "rating", "ts"])
    ratings["item"] = pd.factorize(ratings["item"], sort=True)[0] + 1   # 0 = padding
    ratings = ratings.sort_values(["user", "ts"], kind="mergesort")
    sequences = [g.to_numpy() for _, g in ratings.groupby("user")["item"]]
    n_items = int(ratings["item"].max())
    torch.manual_seed(C.SEED)
    rng = np.random.default_rng(C.SEED)

    def matrix(rows):
        out = np.zeros((len(rows), MAXLEN), dtype=np.int64)
        for r, s in enumerate(rows):
            s = s[-MAXLEN:]
            out[r, MAXLEN - s.size:] = s
        return torch.as_tensor(out, device=device)

    model = M.SASRec(n_items, dim=DIM, layers=2, heads=1, maxlen=MAXLEN, dropout=0.2).to(device)
    optimiser = torch.optim.Adam(model.parameters(), lr=1e-3, betas=(0.9, 0.98))
    train = [s[:-2] for s in sequences]

    @torch.inference_mode()
    def evaluate(histories, targets, sampled=False):
        model.eval()
        ranks = []
        eval_rng = np.random.default_rng(0)
        for b in range(0, len(histories), 512):
            h = histories[b:b + 512]
            t = torch.as_tensor(targets[b:b + 512], device=device)
            scores = model.query(matrix(h)) @ model.catalog_matrix().T   # column j = item j+1
            for k, s in enumerate(h):
                scores[k, torch.as_tensor(s - 1, device=device)] = -torch.inf
            target_score = scores.gather(1, (t - 1)[:, None])
            if sampled:
                negs = torch.as_tensor(eval_rng.integers(1, n_items + 1, size=(len(h), 100)),
                                       device=device)
                neg_scores = scores.gather(1, negs - 1)
                ranks.append((1 + (neg_scores > target_score).sum(1)).cpu().numpy())
            else:
                ranks.append((1 + (scores > target_score).sum(1)).cpu().numpy())
        r = np.concatenate(ranks)
        return {"HR@10": float((r <= 10).mean()),
                "NDCG@10": float(np.where(r <= 10, 1 / np.log2(r + 1), 0).mean())}

    val_hist = [s[:-2] for s in sequences]
    val_t = np.array([s[-2] for s in sequences])
    test_hist = [s[:-1] for s in sequences]
    test_t = np.array([s[-1] for s in sequences])
    best, best_state, log = -1, None, []
    start = time.time()
    for epoch in range(1, 201):
        model.train()
        order = rng.permutation(len(train))
        for b in range(0, len(train), 128):
            rows = [train[i] for i in order[b:b + 128]]
            seq = matrix([s[:-1] for s in rows])
            pos = matrix([s[1:] for s in rows])
            neg = torch.as_tensor(rng.integers(1, n_items + 1, size=tuple(pos.shape)), device=device)
            optimiser.zero_grad()
            loss = model.loss(seq, pos, neg)
            loss.backward()
            optimiser.step()
        if epoch % 20 == 0:
            v = evaluate(val_hist, val_t)
            log.append({"epoch": epoch, **v})
            print(epoch, v, f"{time.time() - start:.0f}s", flush=True)
            if v["NDCG@10"] > best:
                best = v["NDCG@10"]
                best_state = {k: x.detach().clone() for k, x in model.state_dict().items()}
    model.load_state_dict(best_state)
    out = {"dataset": "MovieLens-1M", "users": len(sequences), "items": n_items,
           "events": len(ratings), "recipe": {"maxlen": MAXLEN, "dim": DIM, "layers": 2,
           "heads": 1, "dropout": 0.2, "lr": 1e-3, "loss": "BCE, 1 negative", "epochs": 200},
           "test_full_ranking": evaluate(test_hist, test_t),
           "test_100_sampled": evaluate(test_hist, test_t, sampled=True),
           "paper_100_sampled": {"HR@10": 0.8245, "NDCG@10": 0.5905},
           "log": log}
    C.write_json(C.RESULTS / "sanity_ml1m.json", out)
    print(out["test_full_ranking"], out["test_100_sampled"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
