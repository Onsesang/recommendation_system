#!/usr/bin/env python3
"""Full-catalog ranking evaluation, shared by every Exp24 method.

Scores all 825,869 catalog items for each cohort user, removes items the user has
already seen, and ranks the held-out target with ties broken by ascending iid --
the exp17b rule, so R0 must reproduce exp17b's numbers exactly.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np
import torch

import common24 as C
import models24 as M


def history_and_targets(data, split):
    users = data[f"{split}_users"]
    offsets = data["offsets"]
    sequences = data["sequences"]
    extra = data["validation_target"] if split == "test" else None
    matrix = C.sequence_matrix(sequences, offsets, users, C.MAXLEN, extra=extra)
    targets = data[f"{split}_target"][users]
    return users, matrix, targets


def seen_items(data, split, users):
    offsets, sequences = data["offsets"], data["sequences"]
    extra = data["validation_target"] if split == "test" else None
    out = []
    for user in users:
        history = sequences[offsets[user]:offsets[user + 1]]
        if extra is not None and extra[user] > 0:
            history = np.concatenate([history, [extra[user]]])
        out.append(history)
    return out


@torch.inference_mode()
def rank_targets(model, matrix, targets, seen, device, batch=256,
                 item_chunk=200_000, extra_scores=None, return_topk=0):
    """Rank of each user's target over the full catalog, and optionally the top-K."""
    catalog = model.catalog_matrix().to(device)            # (n_items, dim)
    n_items = catalog.shape[0]
    ranks = np.zeros(len(matrix), dtype=np.int64)
    topk = np.zeros((len(matrix), return_topk), dtype=np.int64) if return_topk else None
    start = time.time()
    for begin in range(0, len(matrix), batch):
        rows = slice(begin, min(begin + batch, len(matrix)))
        seq = torch.as_tensor(matrix[rows], dtype=torch.long, device=device)
        query = model.query(seq)                            # (b, dim)
        scores = torch.empty((query.shape[0], n_items), device=device)
        for i in range(0, n_items, item_chunk):
            scores[:, i:i + item_chunk] = query @ catalog[i:i + item_chunk].T
        if extra_scores is not None:
            scores += extra_scores(np.arange(rows.start, rows.stop), scores)
        for k, user_row in enumerate(range(rows.start, rows.stop)):
            history = seen[user_row]
            if history.size:
                scores[k, history - 1] = -torch.inf
        target_index = torch.as_tensor(targets[rows] - 1, dtype=torch.long, device=device)
        target_score = scores.gather(1, target_index[:, None]).squeeze(1)
        greater = (scores > target_score[:, None]).sum(1)
        index = torch.arange(n_items, device=device)
        equal_before = ((scores == target_score[:, None]) &
                        (index[None, :] < target_index[:, None])).sum(1)
        ranks[rows] = (1 + greater + equal_before).cpu().numpy()
        if return_topk:
            topk[rows] = scores.topk(return_topk, dim=1).indices.cpu().numpy() + 1
        if begin % (batch * 20) == 0:
            done = rows.stop
            print(f"    {done}/{len(matrix)}  {done / max(time.time() - start, 1e-9):.1f} users/s",
                  flush=True)
    return ranks, topk


def load_exp16_sasrec(path, n_items, device):
    saved = torch.load(path, map_location="cpu", weights_only=False)
    state = saved.get("state_dict", saved.get("model", saved))
    model = M.SASRec(n_items, dim=C.DIM, layers=C.LAYERS, heads=C.HEADS,
                     maxlen=C.MAXLEN, dropout=C.DROPOUT)
    missing, unexpected = model.load_state_dict(state, strict=False)
    if unexpected:
        raise RuntimeError(f"unexpected keys: {list(unexpected)[:6]}")
    if missing:
        print(f"  note: {len(missing)} missing keys (first: {list(missing)[:3]})", flush=True)
    return model.to(device).eval()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--checkpoint",
                    default=str(C.E16 / "artifacts/checkpoints/sasrec_lr0.0003.pt"))
    ap.add_argument("--split", default="test", choices=["validation", "test"])
    ap.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    ap.add_argument("--batch", type=int, default=256)
    ap.add_argument("--tag", default="R0_reproduction")
    args = ap.parse_args()

    data = C.load_prepared()
    n_items = int(data["n_items"][0])
    device = torch.device(args.device)
    print(f"device {device}, items {n_items}", flush=True)

    model = load_exp16_sasrec(args.checkpoint, n_items, device)
    users, matrix, targets = history_and_targets(data, args.split)
    seen = seen_items(data, args.split, users)
    print(f"{args.split}: {len(users)} users", flush=True)

    ranks, _ = rank_targets(model, matrix, targets, seen, device, batch=args.batch)
    metrics = C.metrics_from_ranks(ranks)
    np.savez_compressed(C.CACHE / f"ranks__{args.tag}__{args.split}.npz",
                        users=users, ranks=ranks, targets=targets)
    C.write_json(C.RESULTS / f"{args.tag}__{args.split}.json", {
        "tag": args.tag, "split": args.split, "checkpoint": args.checkpoint,
        "metrics": metrics,
    })
    print(f"\n{args.tag} / {args.split}: " +
          "  ".join(f"{k}={v:.8f}" if isinstance(v, float) else f"{k}={v}"
                    for k, v in metrics.items()), flush=True)
    if args.tag == "R0_reproduction" and args.split == "test":
        expected = {"NDCG@10": 0.00349417, "HR@10": 0.00576840, "MRR@10": 0.00280234}
        print("\nexp17b reported vs reproduced:")
        for key, value in expected.items():
            got = metrics[key]
            flag = "MATCH" if abs(got - value) < 5e-8 else "DIFFERS"
            print(f"  {key:8s} reported {value:.8f}  reproduced {got:.8f}  {flag}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
