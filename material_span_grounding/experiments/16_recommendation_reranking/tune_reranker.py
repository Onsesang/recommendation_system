#!/usr/bin/env python3
from __future__ import annotations

import json

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import torch

from common import ARTIFACTS, CONFIG_PATH, MODELS, atomic_json, candidate_metrics, percentile_rank, read_json, sha256
from reranking_core import ranks_with_missing, save_candidate_bundle


def metric_row(scores: np.ndarray, target: np.ndarray) -> dict[str, float]:
    return candidate_metrics(ranks_with_missing(scores, target))


def choose(rows: list[dict], parameter: str) -> dict:
    return sorted(rows, key=lambda row: (-row["ndcg_at_10"], row[parameter]))[0]


def main() -> int:
    config = read_json(CONFIG_PATH)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    bundle_path = save_candidate_bundle("validation", MODELS / "bpr_validation.pt", config["candidate_k"], device)
    bundle = np.load(bundle_path)
    target = bundle["target_positions"]
    base, category, tactile = bundle["base_norm"], bundle["category_norm"], bundle["tactile_norm"]
    rows = []
    beta_rows = []
    for beta in config["weight_grid"]:
        metrics = metric_row((1-beta)*base + beta*category, target)
        row = {"search": "beta_category", "beta": beta, "alpha": np.nan, **metrics}
        rows.append(row); beta_rows.append(row)
    beta_best = choose(beta_rows, "beta")
    beta = beta_best["beta"]
    non_tactile = (1-beta)*base + beta*category
    non_tactile_norm = np.vstack([percentile_rank(row) for row in non_tactile]).astype(np.float32)
    alpha_rows = []
    for alpha in config["weight_grid"]:
        metrics = metric_row((1-alpha)*non_tactile_norm + alpha*tactile, target)
        row = {"search": "alpha_proposed", "beta": beta, "alpha": alpha, **metrics}
        rows.append(row); alpha_rows.append(row)
    alpha_best = choose(alpha_rows, "alpha")
    base_tactile_rows = []
    for alpha in config["weight_grid"]:
        metrics = metric_row((1-alpha)*base + alpha*tactile, target)
        row = {"search": "alpha_base_tactile", "beta": np.nan, "alpha": alpha, **metrics}
        rows.append(row); base_tactile_rows.append(row)
    base_tactile_best = choose(base_tactile_rows, "alpha")
    category_ranks = ranks_with_missing(non_tactile, target)
    alpha_zero_ranks = ranks_with_missing(non_tactile_norm, target)
    if not np.array_equal(category_ranks, alpha_zero_ranks):
        raise RuntimeError("alpha=0 does not reproduce category-aware ranking")
    path = ARTIFACTS / "validation_weight_search.csv"
    pd.DataFrame(rows).to_csv(path, index=False)
    plt.figure(figsize=(7, 4))
    plt.plot([r["alpha"] for r in alpha_rows], [r["ndcg_at_10"] for r in alpha_rows], marker="o")
    plt.axvline(alpha_best["alpha"], color="crimson", linestyle="--", label=f"alpha*={alpha_best['alpha']:.2f}")
    plt.xlabel("Tactile weight alpha"); plt.ylabel("Validation NDCG@10"); plt.grid(alpha=.3); plt.legend(); plt.tight_layout()
    plot_path = ARTIFACTS / "alpha_validation_curve.png"
    plt.savefig(plot_path, dpi=180); plt.close()
    candidate_recall = {f"recall_at_{k}": float(np.mean((target >= 0) & (target < k))) for k in config["candidate_k_values"]}
    selection = {
        "status": "locked_before_test", "selection_split": "validation", "selection_metric": "NDCG@10",
        "tie_rule": "smaller weight", "candidate_k": config["candidate_k"],
        "candidate_recall": candidate_recall,
        "beta_star": beta, "category_validation": {k:v for k,v in beta_best.items() if k not in ("search","beta","alpha")},
        "alpha_star": alpha_best["alpha"], "proposed_validation": {k:v for k,v in alpha_best.items() if k not in ("search","beta","alpha")},
        "base_tactile_alpha_star": base_tactile_best["alpha"],
        "base_tactile_validation": {k:v for k,v in base_tactile_best.items() if k not in ("search","beta","alpha")},
        "alpha_zero_equals_category": True,
        "weight_search": str(path), "weight_search_sha256": sha256(path), "curve": str(plot_path),
    }
    atomic_json(ARTIFACTS / "selection.json", selection)
    print(json.dumps(selection, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
