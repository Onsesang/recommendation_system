#!/usr/bin/env python3
"""Automatically selected qualitative examples -- no cherry-picking.

For a fixed (system, reference) contrast the queries are ranked by NDCG@10 gain
and exactly three are taken by rule: largest gain, median gain, largest loss.
Each example stores the full top-10 of both rankings together with the known
labels, the unknown labels and the raw model scores, so a reader can check the
claim rather than take it on trust.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np
import pandas as pd

import common23 as R

sys.path.insert(0, str(Path(__file__).resolve().parent))
from importlib import import_module

runner = import_module("01_run_retrieval")

SYSTEM = ("Last2 (ours)", "last2")
REFERENCE = ("Category-only (no pixels)", "category_only")


def main() -> int:
    template_choice = {}
    choice = R.EXP22 / "artifacts/clip_prompt_selection.json"
    if choice.is_file():
        import json
        template_choice = json.loads(choice.read_text())

    block = R.label_block("test")
    queries = R.build_queries(block)
    by_id = {q["query_id"]: q for q in queries}
    rng = np.random.default_rng(R.SEED)
    tie = rng.permutation(len(block["product_ids"])).astype(np.int64)

    aggregator = R.write_json.__globals__["json"].loads(
        (R.ARTIFACTS / "aggregator_selection.json").read_text())["selected"]

    scores = {}
    for name, key in (SYSTEM, REFERENCE):
        scores[name] = runner.load_attribute_scores(
            key, "test", block["product_ids"], template_choice)

    per_query = pd.read_csv(R.RESULTS / "retrieval_per_query.csv")
    mine = per_query[per_query["system"] == SYSTEM[0]].set_index("query_id")["ndcg@10"]
    ref = per_query[per_query["system"] == REFERENCE[0]].set_index("query_id")["ndcg@10"]
    gain = (mine - ref).dropna().sort_values()

    picks = {
        "largest_loss": gain.index[0],
        "median_gain": gain.index[len(gain) // 2],
        "largest_gain": gain.index[-1],
    }

    examples = {}
    for label, query_id in picks.items():
        query = by_id[query_id]
        pool = np.asarray(query["pool_index"])
        relevant = set(query["relevant_index"])
        entry = {
            "selection_rule": label,
            "query_id": query_id,
            "query_text": query["text"],
            "family": query["family"],
            "scope": query["scope"],
            "category": query["category"],
            "constraints": query["constraints"],
            "pool_size": query["pool_size"],
            "n_relevant": query["n_relevant"],
            "ndcg@10": {SYSTEM[0]: float(mine[query_id]), REFERENCE[0]: float(ref[query_id])},
            "rankings": {},
        }
        for name, _key in (SYSTEM, REFERENCE):
            combined = R.aggregate(runner.constraint_scores(scores[name], query))[aggregator]
            order = R.rank_order(combined, tie[pool])
            top = []
            for rank, position in enumerate(order[:10], start=1):
                product = pool[position]
                known = {a: ("positive" if block["positive"][product, j]
                             else "negative" if block["negative"][product, j] else "unknown")
                         for j, a in enumerate(R.ATTRIBUTES)}
                top.append({
                    "rank": rank,
                    "product_id": block["product_ids"][product],
                    "category": block["categories"][product],
                    "relevant": bool(product in relevant),
                    "aggregated_score": float(combined[position]),
                    "model_scores": {a: float(scores[name][product, j])
                                     for j, a in enumerate(R.ATTRIBUTES)},
                    "known_labels": {a: v for a, v in known.items() if v != "unknown"},
                    "unknown_labels": [a for a, v in known.items() if v == "unknown"],
                })
            entry["rankings"][name] = top
        examples[label] = entry

    R.write_json(R.RESULTS / "qualitative_examples.json", {
        "contrast": f"{SYSTEM[0]} minus {REFERENCE[0]}",
        "metric": "ndcg@10",
        "selection": "automatic: argmax gain / median gain / argmin gain over all test queries",
        "aggregator": aggregator,
        "examples": examples,
    })
    for label, entry in examples.items():
        print(f"{label:14s} {entry['query_id']:34s} "
              f"{SYSTEM[0]} {entry['ndcg@10'][SYSTEM[0]]:.4f} vs "
              f"{REFERENCE[0]} {entry['ndcg@10'][REFERENCE[0]]:.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
