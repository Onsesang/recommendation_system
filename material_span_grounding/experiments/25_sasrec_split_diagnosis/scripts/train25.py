#!/usr/bin/env python3
"""Train and evaluate SASRec (and the popularity list) on one split setting.

Recipe = exp24 03_train.py R0 except validation every epoch (exp24: every 5, which misses
the peak -- validation NDCG peaks at epoch 1-3 here).  dim 64, 2 layers, 2 heads,
maxlen 50, dropout 0.2, batch 256, AdamW lr 1e-3 wd 0.01, one uniform negative per
position (BCE), max 50 epochs, patience 5 epochs, select on validation
NDCG@10.  Ranking = every item in the setting's universe, previously seen items
removed, ties broken by ascending iid (exp17b rule).

For tsp/uh the test model is refit from scratch on train+validation for the selected
number of epochs; loo keeps the exp24 practice of testing the train-only model.

Every test user is ranked twice:
  main  over the setting's universe (all: 825,869 items; rec: 483,779 recommendable)
  rec   over recommendable items only (only meaningful when the target is recommendable)
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np
import torch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common25 as C
import models25 as M
import protocols as P


# ------------------------------------------------------------------ batching
def history_matrix(history: P.Grouped, users: np.ndarray, maxlen=C.MAXLEN) -> np.ndarray:
    out = np.zeros((len(users), maxlen), dtype=np.int64)
    for row, user in enumerate(users):
        items = history.row(user)[-maxlen:] + 1        # 0 = padding
        if items.size:
            out[row, maxlen - items.size:] = items
    return out


def training_batch(grouped: P.Grouped, users: np.ndarray, maxlen=C.MAXLEN):
    seq = np.zeros((len(users), maxlen), dtype=np.int64)
    pos = np.zeros((len(users), maxlen), dtype=np.int64)
    for row, user in enumerate(users):
        history = grouped.row(user)[-(maxlen + 1):] + 1
        inputs, targets = history[:-1], history[1:]
        seq[row, maxlen - inputs.size:] = inputs
        pos[row, maxlen - targets.size:] = targets
    return seq, pos


# ------------------------------------------------------------------ ranking
@torch.inference_mode()
def rank(score_fn, ev: P.EvalSet, masks: dict, device, batch=256, topk=10):
    """Ranks of the target under each candidate mask; top-k under the first mask."""
    users, targets = ev.users, ev.target
    ranks = {name: np.zeros(len(users), dtype=np.int64) for name in masks}
    top = np.zeros((len(users), topk), dtype=np.int64)
    mask_t = {name: torch.as_tensor(~m, device=device) for name, m in masks.items()}
    first = next(iter(masks))
    n_items = next(iter(masks.values())).size
    index = torch.arange(n_items, device=device)
    for begin in range(0, len(users), batch):
        rows = slice(begin, min(begin + batch, len(users)))
        base = score_fn(users[rows])                             # (b, n_items)
        for k, user in enumerate(users[rows]):
            seen = ev.history.row(user)
            if seen.size:
                base[k, torch.as_tensor(seen, device=device)] = -torch.inf
        target = torch.as_tensor(targets[rows], device=device)
        for name, excluded in mask_t.items():
            scores = base.masked_fill(excluded, -torch.inf)
            t = scores.gather(1, target[:, None])
            greater = (scores > t).sum(1)
            tied_before = ((scores == t) & (index[None, :] < target[:, None])).sum(1)
            ranks[name][rows] = (1 + greater + tied_before).cpu().numpy()
            if name == first:
                top[rows] = scores.topk(topk, dim=1).indices.cpu().numpy()
    return ranks, top


def metrics(ranks: np.ndarray) -> dict:
    ranks = np.asarray(ranks, dtype=np.float64)
    out = {"users": int(ranks.size)}
    if ranks.size == 0:
        return out
    for k in C.K_GRID:
        out[f"Recall@{k}"] = float((ranks <= k).mean())
    out["NDCG@10"] = float(np.where(ranks <= 10, 1 / np.log2(ranks + 1), 0).mean())
    out["MRR@10"] = float(np.where(ranks <= 10, 1 / ranks, 0).mean())
    return out


# ------------------------------------------------------------------ training
class Negatives:
    def __init__(self, universe: np.ndarray, seed: int, device):
        self.items = np.flatnonzero(universe) + 1                # shifted ids
        self.rng = np.random.default_rng(seed)
        self.device = device

    def per_position(self, shape):
        return torch.as_tensor(self.items[self.rng.integers(0, self.items.size, size=shape)],
                               device=self.device)

    def shared(self, n):
        return torch.as_tensor(self.items[self.rng.integers(0, self.items.size, size=n)],
                               device=self.device)


def fit(split: P.Split, grouped: P.Grouped, args, device, epochs: int,
        validate: bool, log: list) -> M.SASRec:
    torch.manual_seed(args.seed)
    rng = np.random.default_rng(args.seed)
    model = M.SASRec(split.n_items, dim=args.dim, layers=C.LAYERS, heads=C.HEADS,
                     maxlen=C.MAXLEN, dropout=args.dropout).to(device)
    optimiser = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=0.01)
    negatives = Negatives(split.universe, args.seed, device)
    users = np.flatnonzero(grouped.lengths() >= 2)
    best = {"ndcg": -1.0, "epoch": 0, "state": None}
    patience = 0
    for epoch in range(1, epochs + 1):
        model.train()
        total, batches, start = 0.0, 0, time.time()
        order = rng.permutation(users.size)
        for begin in range(0, users.size, C.BATCH):
            seq, pos = training_batch(grouped, users[order[begin:begin + C.BATCH]])
            seq_t = torch.as_tensor(seq, device=device)
            pos_t = torch.as_tensor(pos, device=device)
            optimiser.zero_grad()
            if args.loss == "bce":
                loss = model.loss(seq_t, pos_t, negatives.per_position(pos.shape))
            else:
                loss = M.sampled_softmax_loss(model, seq_t, pos_t, negatives.shared(args.ce_negatives))
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimiser.step()
            total += float(loss.item())
            batches += 1
        entry = {"epoch": epoch, "loss": total / max(batches, 1), "seconds": time.time() - start}
        if validate and epoch % args.validate_every == 0:
            model.eval()
            ranks, _ = rank(sasrec_scores(model, split.validation, device), split.validation,
                            {"main": split.universe}, device)
            entry.update({f"val_{k}": v for k, v in metrics(ranks["main"]).items()})
            if entry["val_NDCG@10"] > best["ndcg"]:
                best = {"ndcg": entry["val_NDCG@10"], "epoch": epoch,
                        "state": {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}}
                patience = 0
            else:
                patience += 1
        log.append(entry)
        print(f"[{args.tag}] {entry}", flush=True)
        if validate and patience >= args.patience:
            break
    if validate:
        model.load_state_dict(best["state"])
        model.best_epoch = best["epoch"]
    return model.eval()


def sasrec_scores(model, ev: P.EvalSet, device):
    def score(users):
        seq = torch.as_tensor(history_matrix(ev.history, users), device=device)
        return model.query(seq) @ model.catalog_matrix().T
    return score


def popularity_scores(grouped: P.Grouped, n_items: int, device):
    counts = torch.as_tensor(np.bincount(grouped.flat, minlength=n_items).astype(np.float32),
                             device=device)
    return lambda users: counts.expand(len(users), -1).clone()


# ------------------------------------------------------------------ main
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--protocol", required=True, choices=["loo", "tsp", "uh"])
    ap.add_argument("--data", default="all", choices=["all", "rec"])
    ap.add_argument("--loss", default="bce", choices=["bce", "ce"])
    ap.add_argument("--ce-negatives", type=int, default=4096)
    ap.add_argument("--lr", type=float, default=1e-3)
    ap.add_argument("--dim", type=int, default=C.DIM)
    ap.add_argument("--dropout", type=float, default=C.DROPOUT)
    ap.add_argument("--epochs", type=int, default=50)
    ap.add_argument("--validate-every", type=int, default=1)
    ap.add_argument("--patience", type=int, default=5)
    ap.add_argument("--seed", type=int, default=C.SEED)
    ap.add_argument("--tag", default=None)
    args = ap.parse_args()
    args.tag = args.tag or f"{args.protocol}-{args.data}-{args.loss}-s{args.seed}"
    device = torch.device("cuda")
    start = time.time()

    split = P.build(args.protocol, args.data, seed=C.SEED)
    recommendable = np.load(C.RECOMMENDABLE_MASK)
    log: list = []
    model = fit(split, split.train, args, device, args.epochs, True, log)
    best_epoch = model.best_epoch
    test_model = model
    if split.refit is not None:
        print(f"[{args.tag}] refit on train+validation for {best_epoch} epochs", flush=True)
        test_model = fit(split, split.refit, args, device, best_epoch, False, log)
    fit_events = split.refit or split.train

    masks = {"main": split.universe, "rec": recommendable & split.universe}
    out = {"tag": args.tag, "args": vars(args), "best_epoch": best_epoch, "log": log}
    arrays = {"users": split.test.users, "targets": split.test.target}
    for name, fn in (("sasrec", sasrec_scores(test_model, split.test, device)),
                     ("popularity", popularity_scores(fit_events, split.n_items, device))):
        ranks, top = rank(fn, split.test, masks, device)
        arrays[f"{name}_rank_main"], arrays[f"{name}_rank_rec"] = ranks["main"], ranks["rec"]
        arrays[f"{name}_top10"] = top
        rec_target = recommendable[split.test.target]
        out[name] = {"main": metrics(ranks["main"]), "rec": metrics(ranks["rec"][rec_target])}
        print(f"[{args.tag}] {name} main {out[name]['main']}", flush=True)
        print(f"[{args.tag}] {name} rec  {out[name]['rec']}", flush=True)
    # SASRec's top-500 overlap with the popularity top-500 (collapse-to-popularity check)
    with torch.inference_mode():
        counts = np.bincount(fit_events.flat, minlength=split.n_items).astype(np.float32)
        counts[~split.universe] = -1
        pop500 = torch.as_tensor(np.argsort(-counts, kind="stable")[:500], device=device)
        sample = split.test.users[:2000]
        scores = sasrec_scores(test_model, split.test, device)(sample)
        scores[:, ~torch.as_tensor(split.universe, device=device)] = -torch.inf
        top500 = scores.topk(500, dim=1).indices
        overlap = torch.isin(top500, pop500).float().mean().item()
    out["sasrec_top500_popularity_overlap"] = overlap
    out["elapsed_seconds"] = time.time() - start
    C.write_json(C.RESULTS / "runs" / f"{args.tag}.json", out)
    np.savez_compressed(C.CACHE / "ranks" / f"{args.tag}.npz", **arrays)
    print(f"[{args.tag}] done in {out['elapsed_seconds']:.0f}s  overlap {overlap:.3f}", flush=True)
    return 0


if __name__ == "__main__":
    (C.CACHE / "ranks").mkdir(exist_ok=True)
    raise SystemExit(main())
