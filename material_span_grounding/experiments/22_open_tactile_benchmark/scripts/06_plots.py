#!/usr/bin/env python3
"""Exp22 figures, generated from results/*.csv only (no re-scoring)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

import common22 as C

FAMILY_COLOUR = {"ours": "#1f77b4", "vlm": "#d62728", "clip": "#2ca02c", "control": "#7f7f7f"}
TRACK_TITLE = {"A_amazon_test": "Track A — Amazon apparel locked test (1,060 products)",
               "B_fabricvst_ood": "Track B — FabricVST external OOD (50 fabrics)"}


def bar_metric(metrics, column, filename, label):
    tracks = [t for t in ("A_amazon_test", "B_fabricvst_ood") if t in set(metrics["track"])]
    fig, axes = plt.subplots(1, len(tracks), figsize=(7.6 * len(tracks), 5.6))
    axes = np.atleast_1d(axes)
    for ax, track in zip(axes, tracks):
        block = metrics[metrics["track"] == track].sort_values(column)
        colours = [FAMILY_COLOUR.get(f, "#999") for f in block["family"]]
        ax.barh(block["model"], block[column], color=colours)
        low, high = f"{column}_ci_low", f"{column}_ci_high"
        if low in block and block[low].notna().any():
            ax.errorbar(block[column], range(len(block)),
                        xerr=[block[column] - block[low], block[high] - block[column]],
                        fmt="none", ecolor="#333", capsize=3, linewidth=1)
        ax.axvline(0.5, color="#444", linestyle="--", linewidth=1)
        ax.set_xlabel(f"{label}   (0.5 = chance)")
        ax.set_title(TRACK_TITLE[track], fontsize=10)
        ax.set_xlim(0.40, max(0.85, float(block[column].max()) + 0.07))
        ax.tick_params(axis="y", labelsize=8)
        for i, value in enumerate(block[column]):
            ax.text(value + 0.004, i, f"{value:.4f}", va="center", fontsize=8)
    handles = [plt.Rectangle((0, 0), 1, 1, color=c) for c in FAMILY_COLOUR.values()]
    fig.legend(handles, list(FAMILY_COLOUR), loc="lower center", ncol=4, frameon=False)
    fig.suptitle(f"{label} on the 8 EXACT-mapped tactile attributes", fontsize=12)
    fig.tight_layout(rect=(0, 0.06, 1, 0.96))
    fig.savefig(C.PLOTS / filename, dpi=150)
    plt.close(fig)


def heatmap(per_attribute, track, filename):
    block = per_attribute[per_attribute["track"] == track]
    if block.empty:
        return
    pivot = block.pivot_table(index="model", columns="attribute", values="auroc")
    pivot = pivot[[a for a in C.COMMON8 if a in pivot.columns]]
    pivot = pivot.loc[pivot.mean(axis=1).sort_values(ascending=False).index]
    fig, ax = plt.subplots(figsize=(1.0 * len(pivot.columns) + 5.5, 0.5 * len(pivot) + 2.6))
    image = ax.imshow(pivot.values, cmap="RdYlBu_r", vmin=0.3, vmax=0.9, aspect="auto")
    ax.set_xticks(range(len(pivot.columns)), pivot.columns, rotation=45, ha="right")
    ax.set_yticks(range(len(pivot.index)), pivot.index, fontsize=8)
    for i in range(pivot.shape[0]):
        for j in range(pivot.shape[1]):
            value = pivot.values[i, j]
            if not np.isnan(value):
                ax.text(j, i, f"{value:.2f}", ha="center", va="center", fontsize=7,
                        color="white" if abs(value - 0.6) > 0.18 else "black")
    fig.colorbar(image, ax=ax, label="AUROC (0.5 = chance)")
    ax.set_title(f"Per-attribute AUROC — {TRACK_TITLE[track]}", fontsize=10)
    fig.tight_layout()
    fig.savefig(C.PLOTS / filename, dpi=150)
    plt.close(fig)


def rate_vs_prevalence(rates, filename):
    tracks = sorted(set(rates["track"]))
    fig, axes = plt.subplots(1, len(tracks), figsize=(6.8 * len(tracks), 5.8))
    axes = np.atleast_1d(axes)
    for ax, track in zip(axes, tracks):
        block = rates[rates["track"] == track]
        for model, group in block.groupby("model"):
            ax.scatter(group["gt_prevalence"], group["prediction_positive_rate"],
                       label=model, s=36, alpha=0.8)
        ax.plot([0, 1], [0, 1], color="#444", linestyle="--", linewidth=1)
        ax.axhline(0.95, color="#d62728", linestyle=":", linewidth=1)
        ax.text(0.02, 0.957, "all-positive collapse", color="#d62728", fontsize=7)
        ax.set_xlabel("ground-truth positive prevalence")
        ax.set_ylabel("prediction positive rate")
        ax.set_title(TRACK_TITLE[track], fontsize=10)
        ax.set_xlim(-0.02, 1.02)
        ax.set_ylim(-0.02, 1.06)
    axes[-1].legend(fontsize=6.5, loc="lower right", framealpha=0.9)
    fig.suptitle("Degeneracy check: does the model track the base rate, "
                 "or simply answer YES to everything?", fontsize=11)
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    fig.savefig(C.PLOTS / filename, dpi=150)
    plt.close(fig)


def score_distributions(filename, track="A_amazon_test"):
    keys = [("last2", "Last2"), ("fabricvst_B", "FabricVST-B"),
            ("siglip2_so400m_384", "SigLIP2"), ("qwen3vl_8b", "Qwen3-VL-8B"),
            ("internvl3_5_8b", "InternVL3.5-8B"), ("qwen3vl_32b", "Qwen3-VL-32B"),
            ("category_only", "Category-only")]
    track_file = "amazon_test" if track == "A_amazon_test" else "fabricvst_subset"
    available = [(k, n) for k, n in keys
                 if (C.CACHE / "scores" / f"{k}__{track_file}.npz").is_file()]
    if not available:
        return
    fig, axes = plt.subplots(len(available), len(C.COMMON8),
                             figsize=(1.75 * len(C.COMMON8), 1.7 * len(available)),
                             sharex=True, squeeze=False)
    for r, (key, name) in enumerate(available):
        blob = np.load(C.CACHE / "scores" / f"{key}__{track_file}.npz", allow_pickle=True)
        probabilities = (blob["probabilities"] if "probabilities" in blob
                         else blob["probabilities__paired_generic"])
        classes = [str(c) for c in blob["classes"]]
        index = {c: i for i, c in enumerate(classes)}
        for c, attribute in enumerate(C.COMMON8):
            ax = axes[r][c]
            if attribute in index:
                ax.hist(probabilities[:, index[attribute]], bins=30, range=(0, 1),
                        color="#1f77b4")
            ax.set_yticks([])
            if r == 0:
                ax.set_title(attribute, fontsize=9)
            if c == 0:
                ax.set_ylabel(name, fontsize=7.5, rotation=0, ha="right", va="center")
    fig.suptitle(f"Score distributions — {TRACK_TITLE[track]}\n"
                 "a spike at one value means the model is not discriminating", fontsize=11)
    fig.tight_layout(rect=(0, 0, 1, 0.94))
    fig.savefig(C.PLOTS / filename, dpi=140)
    plt.close(fig)


def f1_vs_base_rate(per_attribute, filename):
    block = per_attribute[per_attribute["track"] == "A_amazon_test"]
    if block.empty:
        return
    fig, ax = plt.subplots(figsize=(7.6, 6.4))
    for model, group in block.groupby("model"):
        ax.scatter(group["all_positive_f1"], group["f1"], label=model, s=36, alpha=0.8)
    ax.plot([0, 1], [0, 1], color="#444", linestyle="--", linewidth=1)
    ax.set_xlabel("F1 of an all-positive predictor, 2p/(1+p)")
    ax.set_ylabel("observed F1")
    ax.set_title("Points on the diagonal mean the reported F1 is just the base rate",
                 fontsize=10)
    ax.legend(fontsize=6.5, loc="lower right")
    fig.tight_layout()
    fig.savefig(C.PLOTS / filename, dpi=150)
    plt.close(fig)


def main() -> int:
    metrics = pd.read_csv(C.RESULTS / "model_metrics.csv")
    per_attribute = pd.read_csv(C.RESULTS / "per_attribute_metrics.csv")
    rates = pd.read_csv(C.RESULTS / "prediction_rates.csv")

    bar_metric(metrics, "macro_auroc", "auroc_comparison.png", "Macro AUROC")
    bar_metric(metrics, "macro_auprc", "auprc_comparison.png", "Macro AUPRC")
    heatmap(per_attribute, "A_amazon_test", "per_attribute_auroc_trackA.png")
    heatmap(per_attribute, "B_fabricvst_ood", "per_attribute_auroc_trackB.png")
    rate_vs_prevalence(rates, "prediction_rate_vs_prevalence.png")
    score_distributions("score_distributions_trackA.png", "A_amazon_test")
    f1_vs_base_rate(per_attribute, "f1_vs_base_rate.png")
    print("\n".join(sorted(p.name for p in C.PLOTS.glob("*.png"))))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
