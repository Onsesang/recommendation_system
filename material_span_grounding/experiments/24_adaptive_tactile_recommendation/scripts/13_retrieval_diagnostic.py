#!/usr/bin/env python3
"""Why is SASRec's candidate recall so low? Is the code wrong?

Answers both questions with checks that would each fail loudly if the pipeline
were broken, then quantifies how much of the shortfall is a property of the data
rather than of the model.

Run: <texture python> scripts/13_retrieval_diagnostic.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np
import torch

import common24 as C
import models24 as M
from importlib import import_module

evaluator = import_module("02_evaluate")
candidates = import_module("04_candidates")

K = 500
STRIDE = 6          # deterministic subsample for the GPU-heavy parts
OVERLAP_STRIDE = 60


def recall_and_rank(model, matrix, targets, histories, device, k=K, batch=256):
    catalog = model.catalog_matrix().to(device)
    ranks = np.zeros(len(matrix), dtype=np.int64)
    for begin in range(0, len(matrix), batch):
        rows = slice(begin, min(begin + batch, len(matrix)))
        seq = torch.as_tensor(matrix[rows], dtype=torch.long, device=device)
        with torch.no_grad():
            scores = (model.query(seq) @ catalog.T).clone()
        for i, row in enumerate(range(rows.start, rows.stop)):
            history = histories[row]
            if history.size:
                scores[i, history - 1] = -torch.inf
        index = torch.as_tensor(targets[rows] - 1, dtype=torch.long, device=device)
        target_score = scores.gather(1, index[:, None]).squeeze(1)
        ranks[rows] = (1 + (scores > target_score[:, None]).sum(1)).cpu().numpy()
    return ranks <= k, ranks


def main() -> int:
    data = C.load_prepared()
    n_items = int(data["n_items"][0])
    train_count = data["train_count"]
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    users, matrix, targets, histories = candidates.evaluation_point(data, "test")

    report = {"evaluation": "test cohort, history>=3", "K": K, "n_users": int(len(users))}

    # ---- correctness checks: each would fail loudly on a broken pipeline
    lengths = np.array([h.size for h in histories])
    nonzero = (matrix > 0).sum(1)
    leaks = int(sum(1 for i, h in enumerate(histories) if targets[i] in h))
    report["correctness_checks"] = {
        "min_history_length": int(lengths.min()),
        "cohort_definition_holds_history_ge_3": bool((lengths >= 3).all()),
        "padding_matches_history_length": bool((np.minimum(lengths, C.MAXLEN) == nonzero).all()),
        "right_aligned_last_slot_is_most_recent": bool(
            (matrix[np.arange(len(matrix)), -1] == np.array([h[-1] for h in histories])).all()),
        "target_leaked_into_history": leaks,
    }

    # ---- how much of the catalog and of the targets is even learnable
    cold_catalog = float((train_count == 0).mean())
    cold_targets = float((train_count[targets - 1] == 0).mean())
    report["data_properties"] = {
        "catalog_items": n_items,
        "catalog_never_seen_in_training_fraction": cold_catalog,
        "catalog_never_seen_in_training_count": int((train_count == 0).sum()),
        "test_targets_never_seen_in_training_fraction": cold_targets,
        "ceiling_recall_for_any_collaborative_model": 1.0 - cold_targets,
        # Averaging over ALL 2.03M users buries the point: most have no training
        # history at all.  Report both, and use the with-history figure in prose.
        "mean_train_history_over_all_users": float(np.diff(data["offsets"]).mean()),
        "mean_train_history_over_users_with_history": float(
            np.diff(data["offsets"])[np.diff(data["offsets"]) > 0].mean()),
        "users_with_any_training_history": int((np.diff(data["offsets"]) > 0).sum()),
        "mean_history_of_the_evaluated_cohort": float(
            np.mean([h.size for h in histories])),
    }

    # ---- trained vs untrained vs popularity
    sub = np.arange(0, len(users), STRIDE)
    m_sub, t_sub = matrix[sub], targets[sub]
    h_sub = [histories[i] for i in sub]

    trained = evaluator.load_exp16_sasrec(
        str(C.E16 / "artifacts/checkpoints/sasrec_lr0.0003.pt"), n_items, device)
    hit_trained, _ = recall_and_rank(trained, m_sub, t_sub, h_sub, device)

    torch.manual_seed(0)
    untrained = M.SASRec(n_items, dim=C.DIM, layers=C.LAYERS, heads=C.HEADS,
                         maxlen=C.MAXLEN, dropout=C.DROPOUT).to(device).eval()
    hit_untrained, _ = recall_and_rank(untrained, m_sub, t_sub, h_sub, device)

    popular = set(np.argsort(-train_count)[:K].tolist())
    hit_popularity = np.array([int(t - 1) in popular for t in t_sub])

    warm = train_count[t_sub - 1] >= 1
    report["recall_at_500"] = {
        "sasrec_trained": float(hit_trained.mean()),
        "sasrec_random_init": float(hit_untrained.mean()),
        "popularity_top500": float(hit_popularity.mean()),
        "trained_over_random_ratio": float(hit_trained.mean() / max(hit_untrained.mean(), 1e-9)),
        "warm_targets_only": {
            "n_users": int(warm.sum()),
            "sasrec_trained": float(hit_trained[warm].mean()),
            "popularity_top500": float(hit_popularity[warm].mean()),
        },
        "cold_targets_only": {
            "n_users": int((~warm).sum()),
            "sasrec_trained": float(hit_trained[~warm].mean()),
        },
        "subsample_users": int(len(sub)),
    }

    # ---- is SASRec's candidate list just the popularity list?
    catalog = trained.catalog_matrix().to(device)
    overlaps = []
    thin = np.arange(0, len(users), OVERLAP_STRIDE)
    for begin in range(0, len(thin), 128):
        idx = thin[begin:begin + 128]
        seq = torch.as_tensor(matrix[idx], dtype=torch.long, device=device)
        with torch.no_grad():
            scores = (trained.query(seq) @ catalog.T).clone()
        for i, row in enumerate(idx):
            history = histories[row]
            if history.size:
                scores[i, history - 1] = -torch.inf
        for top in scores.topk(K, dim=1).indices.cpu().numpy():
            overlaps.append(len(set(top.tolist()) & popular) / K)
    report["popularity_overlap"] = {
        "users_sampled": len(overlaps),
        "mean_fraction_of_sasrec_top500_that_is_popularity_top500": float(np.mean(overlaps)),
    }

    C.write_json(C.RESULTS / "retrieval_bottleneck_diagnostic.json", report)
    import json
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
