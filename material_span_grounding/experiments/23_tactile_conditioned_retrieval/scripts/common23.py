#!/usr/bin/env python3
"""Query construction, ground truth and ranking metrics for experiment 23.

Ground-truth rules, fixed before any system is scored:

1. The evaluation pool is the Amazon **locked test** split only.
2. For a query constraining attributes S, the candidate pool is the set of test
   products whose label is KNOWN for every attribute in S.  Products whose label
   is unknown are removed from the pool entirely -- they are neither relevant nor
   irrelevant.  Ranking a product that has no evidence must never be punished as
   if it were a negative.
3. Relevance for a positive constraint is ``known positive`` (value >= 0.5 with
   mask = 1).  Relevance for a negative constraint ("avoid rough") is
   ``known negative`` (value < 0.5 with mask = 1).
4. Negative constraints are admissible **only** because this dataset carries real
   negative evidence: build_targets.py writes a negative for an attribute only
   when a reviewer explicitly asserted its declared incompatible counterpart
   (soft<->firm, smooth<->rough, thin<->thick, flexible<->stiff, warm<->cool).
   Silence is never turned into a negative.  All 8 attributes compared here sit
   in such a validated bipolar pair, so family E has genuine ground truth.
"""
from __future__ import annotations

import itertools
import json
import sys
from pathlib import Path

import numpy as np

EXP = Path(__file__).resolve().parents[1]
PROJECT = EXP.parents[1]
EXP22 = PROJECT / "experiments/22_open_tactile_benchmark"
sys.path.insert(0, str(EXP22 / "scripts"))
import common22 as C22  # noqa: E402

ARTIFACTS = EXP / "artifacts"
RESULTS = EXP / "results"
PLOTS = EXP / "plots"
LOGS = EXP / "logs"
CACHE = EXP / "cache"
for _d in (ARTIFACTS, RESULTS, PLOTS, LOGS, CACHE):
    _d.mkdir(parents=True, exist_ok=True)

SEED = 20260917
ATTRIBUTES = C22.COMMON8

# Declared incompatible counterparts, copied from
# experiments/12_class_multilabel_fashionclip_ft/config.json -> exclusive_pairs.
EXCLUSIVE_PAIRS = [["soft", "firm"], ["smooth", "rough"], ["non_elastic", "elastic"],
                   ["thin", "thick"], ["flexible", "stiff"], ["warm", "cool"],
                   ["spongy", "crisp"]]
OPPOSITE = {}
for _l, _r in EXCLUSIVE_PAIRS:
    OPPOSITE[_l], OPPOSITE[_r] = _r, _l

# --- query admission thresholds, fixed in advance -----------------------------
MIN_POOL = 30          # a query needs at least this many known-label candidates
MIN_RELEVANT = 8       # ... at least this many relevant ones
MIN_IRRELEVANT = 8     # ... and this many irrelevant ones, else the task is
                       #     trivially satisfied by ranking anything
TOP_K = 10
BOOTSTRAP_REPLICATES = 2000

SURFACE = {
    "soft": "soft", "rough": "rough", "smooth": "smooth", "thick": "thick",
    "thin": "thin", "cool": "cool to the touch", "warm": "warm", "stiff": "stiff",
}
CATEGORY_SURFACE = {
    "accessory": "accessory", "dress": "dress", "other": "garment",
    "outerwear": "outerwear", "pants": "pants", "skirt": "skirt",
    "sleepwear": "sleepwear", "sweater": "sweater", "swimwear": "swimwear",
    "top": "top", "underwear": "underwear",
}


def query_text(query: dict) -> str:
    parts = []
    for constraint in query["constraints"]:
        word = SURFACE[constraint["attribute"]]
        parts.append(word if constraint["direction"] == "positive" else f"not {word}")
    noun = CATEGORY_SURFACE.get(query.get("category") or "", "garment")
    return f"a {' and '.join(parts)} {noun}"


def label_block(split: str) -> dict:
    """Known / positive / negative matrices restricted to the 8 compared attributes."""
    data = C22.load_amazon(split)
    index = [data["classes"].index(a) for a in ATTRIBUTES]
    blob = np.load(C22.AMAZON_TARGETS, allow_pickle=True)
    ids = blob["product_ids"].astype(str)
    lookup = {p: i for i, p in enumerate(ids)}
    rows = [lookup[p] for p in data["product_ids"]]
    values = blob["values"][rows][:, index]
    mask = blob["mask"][rows][:, index].astype(bool)
    return {
        "split": split,
        "product_ids": list(data["product_ids"]),
        "categories": list(data["categories"]),
        "attributes": list(ATTRIBUTES),
        "known": mask,
        "positive": (values >= 0.5) & mask,
        "negative": (values < 0.5) & mask,
        "values": values,
    }


def build_queries(block: dict, families=("A", "B", "C", "D", "E")) -> list[dict]:
    """Enumerate the taxonomy exhaustively; nothing is hand-picked.

    Admission depends only on pool size and class balance, never on how any
    system scores the query.
    """
    attributes = block["attributes"]
    categories = sorted(set(block["categories"]))
    n = len(block["product_ids"])
    category_array = np.array(block["categories"])
    queries = []

    def add(family, constraints, category, scope):
        idx = np.arange(n)
        if scope == "same_category":
            idx = idx[category_array[idx] == category]
        pool = idx
        for constraint in constraints:
            j = attributes.index(constraint["attribute"])
            pool = pool[block["known"][pool, j]]
        if pool.size < MIN_POOL:
            return
        relevant = np.ones(pool.size, dtype=bool)
        for constraint in constraints:
            j = attributes.index(constraint["attribute"])
            field = "positive" if constraint["direction"] == "positive" else "negative"
            relevant &= block[field][pool, j]
        if family == "B":                       # category is part of the query itself
            relevant &= (category_array[pool] == category)
        if relevant.sum() < MIN_RELEVANT or (~relevant).sum() < MIN_IRRELEVANT:
            return
        tag = "+".join(
            c["attribute"] if c["direction"] == "positive" else f"not_{c['attribute']}"
            for c in constraints)
        query = {
            "query_id": f"{family}__{tag}" + (f"__{category}" if category else ""),
            "family": family,
            "scope": scope,
            "category": category,
            "constraints": constraints,
            "pool_index": pool.tolist(),
            "pool_size": int(pool.size),
            "n_relevant": int(relevant.sum()),
            "relevant_index": pool[relevant].tolist(),
        }
        query["text"] = query_text(query)
        queries.append(query)

    if "A" in families:                                   # single tactile, global
        for a in attributes:
            add("A", [{"attribute": a, "direction": "positive"}], None, "global")
    if "B" in families:                                   # category + tactile, global
        for a in attributes:
            for category in categories:
                add("B", [{"attribute": a, "direction": "positive"}], category, "global")
    if "C" in families:                                   # tactile within one category
        for a in attributes:
            for category in categories:
                add("C", [{"attribute": a, "direction": "positive"}], category, "same_category")
    if "D" in families:                                   # multi-tactile, global
        for left, right in itertools.combinations(attributes, 2):
            if OPPOSITE.get(left) == right:               # never ask for a contradiction
                continue
            add("D", [{"attribute": left, "direction": "positive"},
                      {"attribute": right, "direction": "positive"}], None, "global")
    if "E" in families:                                   # negative tactile, global
        for a in attributes:
            add("E", [{"attribute": a, "direction": "negative"}], None, "global")
    return queries


def aggregate(scores: np.ndarray) -> dict:
    """Combine per-constraint satisfaction scores.  Identical for every system."""
    clipped = np.clip(scores, 1e-6, 1 - 1e-6)
    return {
        "mean_probability": scores.mean(axis=1),
        "mean_log_probability": np.log(clipped).mean(axis=1),
        "min_probability": scores.min(axis=1),
    }


def rank_metrics(relevant_flags: np.ndarray, order: np.ndarray, k: int = TOP_K) -> dict:
    """NDCG@k, Precision@k, Recall@k, MAP@k for one ranked list."""
    ranked = relevant_flags[order]
    total_relevant = int(relevant_flags.sum())
    top = ranked[:k].astype(float)
    discounts = 1.0 / np.log2(np.arange(2, len(top) + 2))
    dcg = float((top * discounts).sum())
    ideal_n = min(total_relevant, k)
    idcg = float((np.ones(ideal_n) / np.log2(np.arange(2, ideal_n + 2))).sum()) if ideal_n else 0.0
    precisions = np.cumsum(top) / np.arange(1, len(top) + 1)
    hits = float(top.sum())
    return {
        "ndcg@10": dcg / idcg if idcg > 0 else 0.0,
        "precision@10": hits / k,
        "recall@10": hits / total_relevant if total_relevant else 0.0,
        "map@10": float((precisions * top).sum() / min(total_relevant, k)) if total_relevant else 0.0,
        "n_relevant": total_relevant,
        "pool_size": int(relevant_flags.size),
    }


def rank_order(scores: np.ndarray, tie_breaker: np.ndarray) -> np.ndarray:
    """Descending by score, ties broken by a fixed secondary key so no system
    benefits from an arbitrary index order."""
    return np.lexsort((tie_breaker, -scores))


def bootstrap_delta(per_query_a, per_query_b, replicates=BOOTSTRAP_REPLICATES, seed=SEED):
    """Paired bootstrap over queries."""
    a = np.asarray(per_query_a, dtype=float)
    b = np.asarray(per_query_b, dtype=float)
    if a.size == 0:
        return {"delta": None, "ci_low": None, "ci_high": None, "replicates": 0}
    rng = np.random.default_rng(seed)
    n = a.size
    draws = np.empty(replicates)
    for r in range(replicates):
        idx = rng.integers(0, n, size=n)
        draws[r] = a[idx].mean() - b[idx].mean()
    return {"delta": float(a.mean() - b.mean()),
            "ci_low": float(np.percentile(draws, 2.5)),
            "ci_high": float(np.percentile(draws, 97.5)),
            "replicates": replicates}


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, default=float))
