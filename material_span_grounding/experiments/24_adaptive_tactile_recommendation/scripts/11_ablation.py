#!/usr/bin/env python3
"""Tactile-source ablation: does a different tactile predictor change the verdict?

Sources compared, over the same SASRec candidates and the same two methods
(R1 fixed alpha, R2 learned gate):

  none          tactile term removed entirely (equals R0)
  last2         the project's 14-class predictor, full-catalog cache from exp16b
  fabricvst_B   18-attribute FabricVST-taxonomy model   [DIAGNOSTIC]
  fabricvst_A   24-attribute FabricVST-taxonomy model   [DIAGNOSTIC]

The two FabricVST models are labelled DIAGNOSTIC because experiment 21 showed they
predict nearly every fabric positive on the comparable attributes; they are
included for completeness, not as credible tactile predictors, and their numbers
must not be presented as an improvement.

Only the tactile matrix changes between runs. SASRec candidates and scores are
identical throughout, so any difference is attributable to the tactile source.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np
import pandas as pd
import torch

import common24 as C
import models24 as M
from importlib import import_module

rerank = import_module("05_rerank")


def tactile_source(name, data):
    """(values, available, label) for one source."""
    n_items = int(data["n_items"][0])
    if name == "none":
        return np.zeros((n_items, 1), dtype=np.float32), np.zeros(n_items, dtype=bool), "control"
    if name == "last2":
        return data["tactile"], data["tactile_available"], "ours"
    path = C.CACHE / f"catalog_tactile__{name}.npz"
    if not path.is_file():
        return None, None, None
    blob = np.load(path)
    return blob["values"].astype(np.float32), blob["available"].astype(bool), "diagnostic"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    ap.add_argument("--epochs", type=int, default=15)
    ap.add_argument("--lr", type=float, default=1e-3)
    args = ap.parse_args()

    device = torch.device(args.device)
    data = C.load_prepared()
    splits = {s: rerank.load_split(s) for s in ("train", "validation", "test")}
    selection = C.read_json(C.ARTIFACTS / "r2_gate_selection.json")["selected"]
    init_bias, gate_lr = float(selection["init_bias"]), float(selection["lr"])

    rows = []
    for source in ("none", "last2", "fabricvst_B", "fabricvst_A"):
        values, available, family = tactile_source(source, data)
        if values is None:
            print(f"skip {source}: no catalog cache yet", flush=True)
            continue
        print(f"\n===== tactile source: {source} ({family}) =====", flush=True)
        shim = dict(data)
        shim["tactile"] = values
        shim["tactile_available"] = available

        prepared = {}
        for split, block in splits.items():
            candidates = block["sasrec_candidates"]
            # The cached user profile is 14-dimensional (Last2).  FabricVST-A/B have
            # 24/18 attributes, so the profile must be rebuilt in the SAME space as
            # the item vectors or the cosine cannot even be formed.  Rebuilt here
            # from the user's PAST items only, exactly as 04_candidates.py does.
            block = dict(block)
            history = block["history_matrix"]
            profile = np.zeros((history.shape[0], values.shape[1]), dtype=np.float32)
            support = np.zeros(history.shape[0], dtype=np.int32)
            for row in range(history.shape[0]):
                items = history[row][history[row] > 0] - 1
                items = items[available[items]]
                support[row] = items.size
                if items.size:
                    profile[row] = values[items].mean(axis=0)
            block["profile"] = profile
            block["support"] = support
            features, cosine, bp, tp = rerank.build_features(block, shim, candidates,
                                                             block["sasrec_scores"])
            valid = available[candidates - 1] & (support[:, None] > 0)
            prepared[split] = {"candidates": candidates, "features": features, "bp": bp,
                               "tp": tp, "valid": valid, "targets": block["targets"]}

        # R1: alpha chosen on validation
        best_alpha, best_ndcg = 0.0, -1.0
        for alpha in rerank.ALPHA_GRID:
            block = prepared["validation"]
            scores = rerank.r1_scores(block["bp"], block["tp"], alpha, block["valid"])
            ndcg = C.metrics_from_ranks(
                rerank.ranks_from_scores(scores, block["candidates"], block["targets"])
            )["NDCG@10"]
            if ndcg > best_ndcg or (ndcg == best_ndcg and alpha < best_alpha):
                best_alpha, best_ndcg = alpha, ndcg

        # R2: same selected initialisation as the main experiment
        gate = M.TactileGate(prepared["train"]["features"].shape[2],
                             init_bias=init_bias).to(device)
        rerank.train_head(gate, prepared["train"]["features"], prepared["train"]["candidates"],
                          prepared["train"]["targets"], args.epochs, gate_lr, device, C.SEED,
                          combine="gate", base_percentile=prepared["train"]["bp"],
                          tactile_percentile=prepared["train"]["tp"],
                          label=f"R2 gate [{source}]", validation=prepared["validation"])

        for split in ("validation", "test"):
            block = prepared[split]
            r1 = rerank.r1_scores(block["bp"], block["tp"], best_alpha, block["valid"])
            r1_metrics = C.metrics_from_ranks(
                rerank.ranks_from_scores(r1, block["candidates"], block["targets"]))
            scores, gates = rerank.apply_head(gate, block["features"], device, combine="gate",
                                              base_percentile=block["bp"],
                                              tactile_percentile=block["tp"])
            r2_metrics = C.metrics_from_ranks(
                rerank.ranks_from_scores(scores, block["candidates"], block["targets"]))
            rows.append({"tactile_source": source, "status": family, "split": split,
                         "selected_alpha": best_alpha,
                         "R1_NDCG@10": r1_metrics["NDCG@10"],
                         "R2_NDCG@10": r2_metrics["NDCG@10"],
                         "R1_HR@10": r1_metrics["HR@10"], "R2_HR@10": r2_metrics["HR@10"],
                         "gate_mean": float(gates.mean()), "gate_std": float(gates.std()),
                         "tactile_coverage": float(available.mean())})
            print(f"  {split}: alpha={best_alpha}  R1 {r1_metrics['NDCG@10']:.8f}  "
                  f"R2 {r2_metrics['NDCG@10']:.8f}  gate mean {gates.mean():.5f}", flush=True)

    frame = pd.DataFrame(rows)
    frame.to_csv(C.RESULTS / "tactile_source_ablation.csv", index=False)
    print("\n===== tactile source ablation =====")
    print(frame[frame["split"] == "test"][
        ["tactile_source", "status", "selected_alpha", "R1_NDCG@10", "R2_NDCG@10",
         "gate_mean", "tactile_coverage"]]
        .to_string(index=False, float_format=lambda v: f"{v:.8f}"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
