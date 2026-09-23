#!/usr/bin/env python3
"""Exp24 figures, built from results/*.csv and cache/*.npz only."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

import common24 as C


def methods_bar(frame, metric, filename, title):
    block = frame[frame["split"] == "test"].sort_values(metric)
    if block.empty:
        return
    fig, ax = plt.subplots(figsize=(9.5, 0.46 * len(block) + 2.6))
    colours = ["#7f7f7f" if m.startswith("R0") else
               "#d62728" if m.startswith("R1") else "#1f77b4" for m in block["method"]]
    ax.barh(block["method"], block[metric], color=colours)
    reference = float(block[block["method"] == "R0_sasrec"][metric].iloc[0]) \
        if (block["method"] == "R0_sasrec").any() else None
    if reference is not None:
        ax.axvline(reference, color="#444", linestyle="--", linewidth=1.2)
        ax.text(reference, len(block) - 0.4, " R0 SASRec", color="#444", fontsize=8)
    for i, value in enumerate(block[metric]):
        ax.text(value * 1.01, i, f"{value:.6f}", va="center", fontsize=8)
    ax.set_xlabel(metric)
    ax.set_title(title, fontsize=11)
    fig.tight_layout()
    fig.savefig(C.PLOTS / filename, dpi=150)
    plt.close(fig)


def delta_plot(frame, filename):
    block = frame[(frame["split"] == "test") & (frame["method"] != "R0_sasrec")]
    if block.empty:
        return
    block = block.sort_values("delta_vs_R0")
    fig, ax = plt.subplots(figsize=(9.5, 0.46 * len(block) + 2.6))
    ax.barh(block["method"], block["delta_vs_R0"],
            color=["#2ca02c" if d > 0 else "#d62728" for d in block["delta_vs_R0"]])
    ax.errorbar(block["delta_vs_R0"], range(len(block)),
                xerr=[block["delta_vs_R0"] - block["ci95_low"],
                      block["ci95_high"] - block["delta_vs_R0"]],
                fmt="none", ecolor="#222", capsize=3, linewidth=1)
    ax.axvline(0, color="#000", linewidth=1)
    ax.set_xlabel("Δ NDCG@10 vs R0 (paired bootstrap by user, 95 % CI)")
    ax.set_title("A bar whose interval crosses zero is not a demonstrated improvement",
                 fontsize=10)
    fig.tight_layout()
    fig.savefig(C.PLOTS / filename, dpi=150)
    plt.close(fig)


def candidate_recall_plot(filename):
    rows = []
    for split in ("validation", "test"):
        path = C.RESULTS / f"candidate_recall__{split}.json"
        if path.is_file():
            for key, value in C.read_json(path).items():
                rows.append({"split": split, "generator": key, "recall": value})
    if not rows:
        return
    frame = pd.DataFrame(rows)
    frame = frame[frame["generator"].str.contains("@")]
    pivot = frame.pivot_table(index="generator", columns="split", values="recall")
    pivot = pivot.sort_values("test" if "test" in pivot else pivot.columns[0])
    fig, ax = plt.subplots(figsize=(9, 0.42 * len(pivot) + 2.6))
    pivot.plot.barh(ax=ax, color=["#1f77b4", "#ff7f0e"])
    ax.set_xscale("log")
    ax.set_xlabel("candidate recall (log scale)")
    ax.set_title("Candidate recall: the tactile arm is ~17x weaker than the backbone,\n"
                 "and the backbone itself only reaches 0.038", fontsize=10)
    fig.tight_layout()
    fig.savefig(C.PLOTS / filename, dpi=150)
    plt.close(fig)


def gate_plots(filename):
    path = C.CACHE / "gate_values__test.npz"
    if not path.is_file():
        return
    blob = np.load(path)
    gates, history, consistency = blob["gates"], blob["history_length"], blob["consistency"]
    fig, axes = plt.subplots(1, 3, figsize=(15.5, 4.6))
    axes[0].hist(gates.reshape(-1), bins=60, color="#1f77b4")
    axes[0].set_title(f"gate values\nmean {gates.mean():.4f}  std {gates.std():.4f}", fontsize=10)
    axes[0].set_xlabel("g(u, i)")
    bins = [(3, 4), (5, 9), (10, 10_000)]
    labels, means = [], []
    for low, high in bins:
        mask = (history >= low) & (history <= high)
        if mask.sum():
            labels.append(f"{low}-{high if high < 1000 else '+'}")
            means.append(gates[mask].mean())
    axes[1].bar(labels, means, color="#2ca02c")
    axes[1].set_title("mean gate by history length", fontsize=10)
    axes[1].set_xlabel("history length")
    order = np.argsort(consistency)
    chunks = np.array_split(order, 10)
    axes[2].plot([consistency[c].mean() for c in chunks],
                 [gates[c].mean() for c in chunks], marker="o", color="#d62728")
    axes[2].set_xlabel("user tactile consistency (decile mean)")
    axes[2].set_ylabel("mean gate")
    axes[2].set_title("mean gate by tactile consistency", fontsize=10)
    fig.suptitle("R2 learned gate: does the model use tactile differently per user?",
                 fontsize=11)
    fig.tight_layout(rect=(0, 0, 1, 0.94))
    fig.savefig(C.PLOTS / filename, dpi=150)
    plt.close(fig)


def group_plot(filename):
    path = C.RESULTS / "user_group_analysis.csv"
    if not path.is_file():
        return
    frame = pd.read_csv(path)
    block = frame[frame["split"] == "test"]
    if block.empty:
        return
    pivot = block.pivot_table(index="group", columns="method", values="delta_vs_R0")
    pivot = pivot.drop(columns=[c for c in pivot.columns if c == "R0_sasrec"], errors="ignore")
    fig, ax = plt.subplots(figsize=(1.9 * max(len(pivot.columns), 1) + 5.0,
                                    0.5 * len(pivot) + 3.0))
    limit = float(np.nanmax(np.abs(pivot.values))) or 1e-6
    image = ax.imshow(pivot.values, cmap="RdBu_r", vmin=-limit, vmax=limit, aspect="auto")
    ax.set_xticks(range(len(pivot.columns)), pivot.columns, rotation=30, ha="right", fontsize=8)
    ax.set_yticks(range(len(pivot.index)), pivot.index, fontsize=9)
    for i in range(pivot.shape[0]):
        for j in range(pivot.shape[1]):
            v = pivot.values[i, j]
            if not np.isnan(v):
                ax.text(j, i, f"{v:+.5f}", ha="center", va="center", fontsize=7)
    fig.colorbar(image, ax=ax, label="Δ NDCG@10 vs R0")
    ax.set_title("Who does tactile help? Subgroups defined from train history only",
                 fontsize=10)
    fig.tight_layout()
    fig.savefig(C.PLOTS / filename, dpi=150)
    plt.close(fig)


def main() -> int:
    posthoc = pd.read_csv(C.RESULTS / "posthoc_methods.csv")
    methods_bar(posthoc, "NDCG@10", "ndcg_by_method.png",
                "Test NDCG@10 by method (history>=3 cohort, 29,991 users)")
    methods_bar(posthoc, "Recall@10", "recall_by_method.png",
                "Test Recall@10 by method")
    significance = C.RESULTS / "significance_vs_R0.csv"
    if significance.is_file():
        delta_plot(pd.read_csv(significance), "delta_ndcg_vs_baseline.png")
    candidate_recall_plot("candidate_recall.png")
    gate_plots("gate_distribution.png")
    group_plot("performance_by_group.png")
    print("\n".join(sorted(p.name for p in C.PLOTS.glob("*.png"))))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
