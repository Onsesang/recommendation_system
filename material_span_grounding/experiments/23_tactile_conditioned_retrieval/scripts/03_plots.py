#!/usr/bin/env python3
"""Exp23 figures, built only from results/*.csv."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

import common23 as R

COLOUR = {"ours": "#1f77b4", "vlm": "#d62728", "clip": "#2ca02c",
          "control": "#7f7f7f", "baseline": "#9467bd"}


def bars(frame, title, filename):
    frame = frame.sort_values("ndcg@10")
    fig, ax = plt.subplots(figsize=(9.5, 0.46 * len(frame) + 2.6))
    colours = [COLOUR.get(f, "#999") for f in frame["family_type"]]
    ax.barh(frame["system"], frame["ndcg@10"], color=colours)
    low = frame["ndcg@10"] - frame["dNDCG_vs_category_only"] + frame["dNDCG_vs_category_only_ci_low"]
    high = frame["ndcg@10"] - frame["dNDCG_vs_category_only"] + frame["dNDCG_vs_category_only_ci_high"]
    ax.errorbar(frame["ndcg@10"], range(len(frame)),
                xerr=[frame["ndcg@10"] - low, high - frame["ndcg@10"]],
                fmt="none", ecolor="#333", capsize=3, linewidth=1)
    reference = float(frame[frame["system"] == "Category-only (no pixels)"]["ndcg@10"].iloc[0])
    ax.axvline(reference, color="#7f7f7f", linestyle="--", linewidth=1.2)
    ax.text(reference, len(frame) - 0.4, " category-only", color="#7f7f7f", fontsize=8)
    for i, value in enumerate(frame["ndcg@10"]):
        ax.text(value + 0.005, i, f"{value:.4f}", va="center", fontsize=8)
    ax.set_xlabel("NDCG@10")
    ax.set_title(title, fontsize=11)
    fig.tight_layout()
    fig.savefig(R.PLOTS / filename, dpi=150)
    plt.close(fig)


def per_attribute_gain(per_query, filename):
    pivot = (per_query[per_query["family"].isin(["A", "C"])]
             .groupby(["system", "attributes"])["ndcg@10"].mean().unstack())
    reference = pivot.loc["Category-only (no pixels)"]
    gain = (pivot - reference).drop(index="Category-only (no pixels)")
    gain = gain[[a for a in R.ATTRIBUTES if a in gain.columns]]
    gain = gain.loc[gain.mean(axis=1).sort_values(ascending=False).index]
    fig, ax = plt.subplots(figsize=(1.05 * gain.shape[1] + 5.5, 0.48 * len(gain) + 2.6))
    limit = float(np.nanmax(np.abs(gain.values))) or 0.1
    image = ax.imshow(gain.values, cmap="RdBu_r", vmin=-limit, vmax=limit, aspect="auto")
    ax.set_xticks(range(gain.shape[1]), gain.columns, rotation=45, ha="right")
    ax.set_yticks(range(len(gain)), gain.index, fontsize=8)
    for i in range(gain.shape[0]):
        for j in range(gain.shape[1]):
            v = gain.values[i, j]
            if not np.isnan(v):
                ax.text(j, i, f"{v:+.2f}", ha="center", va="center", fontsize=7)
    fig.colorbar(image, ax=ax, label="Δ NDCG@10 vs category-only")
    ax.set_title("Per-attribute retrieval gain over the category-only control\n"
                 "(single-tactile and same-category queries)", fontsize=10)
    fig.tight_layout()
    fig.savefig(R.PLOTS / filename, dpi=150)
    plt.close(fig)


def by_family(per_query, filename):
    pivot = per_query.groupby(["system", "family"])["ndcg@10"].mean().unstack()
    names = {"A": "A single\ntactile", "B": "B category\n+ tactile", "C": "C same-category\n(shortcut removed)",
             "D": "D multi\ntactile", "E": "E negative\ntactile"}
    pivot = pivot[[c for c in ["A", "B", "C", "D", "E"] if c in pivot.columns]]
    pivot = pivot.loc[pivot.mean(axis=1).sort_values(ascending=False).index]
    fig, ax = plt.subplots(figsize=(11, 0.46 * len(pivot) + 3.0))
    width = 0.8 / pivot.shape[1]
    positions = np.arange(len(pivot))
    for k, column in enumerate(pivot.columns):
        ax.barh(positions + k * width, pivot[column], height=width,
                label=names.get(column, column))
    ax.set_yticks(positions + 0.4 - width / 2, pivot.index, fontsize=8)
    ax.set_xlabel("NDCG@10")
    ax.legend(fontsize=7.5, ncol=5, loc="lower right")
    ax.set_title("NDCG@10 by query family", fontsize=11)
    fig.tight_layout()
    fig.savefig(R.PLOTS / filename, dpi=150)
    plt.close(fig)


def main() -> int:
    main_frame = pd.read_csv(R.RESULTS / "retrieval_main.csv")
    same = pd.read_csv(R.RESULTS / "retrieval_same_category.csv")
    per_query = pd.read_csv(R.RESULTS / "retrieval_per_query.csv")

    bars(main_frame, "Tactile-conditioned retrieval — all 107 queries", "ndcg_by_model.png")
    bars(same, "Same-category retrieval — 24 queries, category shortcut removed",
         "same_category_ndcg.png")
    per_attribute_gain(per_query, "per_attribute_retrieval_gain.png")
    by_family(per_query, "ndcg_by_query_family.png")
    print("\n".join(sorted(p.name for p in R.PLOTS.glob("*.png"))))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
