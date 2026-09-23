#!/usr/bin/env python3
"""Run every retrieval system over the auto-generated tactile query benchmark.

Protocol decisions, all fixed before any test number is read:

* The multi-constraint aggregator is selected **once**, on queries built from the
  Amazon *development* split, by macro NDCG@10 averaged over systems -- not per
  system, so no system gets a bespoke aggregator.  The winner is applied
  unchanged to every system on test.
* Positive constraint on attribute a scores P(a); negative constraint scores
  1 - P(a).  Same formula for every system.
* Ties are broken by one fixed seeded permutation shared by all systems.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np
import pandas as pd

import common23 as R

SCORES22 = R.EXP22 / "cache/scores"

# display name -> (exp22 cache key, family)
TACTILE_SYSTEMS = [
    ("Last2 (ours)", "last2", "ours"),
    ("FabricVST-B 18attr (ours)", "fabricvst_B", "ours"),
    ("FabricVST-A 24attr (ours)", "fabricvst_A", "ours"),
    ("FashionCLIP frozen head (ours)", "fashionclip_frozen", "ours"),
    ("FashionCLIP zero-shot", "fashionclip_zeroshot", "clip"),
    ("CLIP-Texture protocol (ViT-L/14)", "clip_texture_vitl14", "clip"),
    ("SigLIP2-so400m", "siglip2_so400m_384", "clip"),
    ("Qwen3-VL-8B-Instruct", "qwen3vl_8b", "vlm"),
    ("Qwen3-VL-32B-Instruct", "qwen3vl_32b", "vlm"),
    ("InternVL3.5-8B", "internvl3_5_8b", "vlm"),
    ("Category-only (no pixels)", "category_only", "control"),
]


def load_attribute_scores(key, split, product_ids, template_choice):
    """(N, 8) matrix of P(attribute) aligned to product_ids, or None."""
    path = SCORES22 / f"{key}__amazon_{split}.npz"
    if not path.is_file():
        return None
    blob = np.load(path, allow_pickle=True)
    if "probabilities" in blob:
        probabilities = blob["probabilities"]
    else:
        template = template_choice.get(key, {}).get("selected", "paired_generic")
        probabilities = blob[f"probabilities__{template}"]
    classes = [str(c) for c in blob["classes"]]
    index = {c: i for i, c in enumerate(classes)}
    if any(a not in index for a in R.ATTRIBUTES):
        return None
    ordered = probabilities[:, [index[a] for a in R.ATTRIBUTES]]
    ids = [str(u) for u in blob["unit_ids"]]
    position = {p: i for i, p in enumerate(ids)}
    rows = [position[p] for p in product_ids]
    return ordered[rows]


def popularity_scores(product_ids):
    catalog = pd.read_parquet(
        R.PROJECT / "experiments/16_strong_recommender_tactile/data/catalog.parquet",
        columns=["parent_asin", "train_count"])
    lookup = dict(zip(catalog["parent_asin"].astype(str), catalog["train_count"]))
    return np.array([float(lookup.get(p, 0.0)) for p in product_ids])


def constraint_scores(attribute_scores, query):
    """(pool, n_constraints) satisfaction matrix."""
    pool = np.asarray(query["pool_index"])
    columns = []
    for constraint in query["constraints"]:
        j = R.ATTRIBUTES.index(constraint["attribute"])
        column = attribute_scores[pool, j]
        columns.append(column if constraint["direction"] == "positive" else 1.0 - column)
    return np.stack(columns, axis=1)


def evaluate(queries, attribute_scores, aggregator, tie_breaker):
    rows = []
    for query in queries:
        pool = np.asarray(query["pool_index"])
        relevant = np.isin(pool, np.asarray(query["relevant_index"]))
        combined = R.aggregate(constraint_scores(attribute_scores, query))[aggregator]
        order = R.rank_order(combined, tie_breaker[pool])
        rows.append({"query_id": query["query_id"], "family": query["family"],
                     "scope": query["scope"], "category": query["category"] or "",
                     "attributes": "+".join(c["attribute"] for c in query["constraints"]),
                     "direction": query["constraints"][0]["direction"],
                     **R.rank_metrics(relevant, order)})
    return pd.DataFrame(rows)


def evaluate_text_image(queries, features, text_bank, tie_breaker):
    """What a deployed search box does: embed the query sentence, rank images by
    cosine similarity.  Query-dependent but not attribute-decomposed."""
    rows = []
    for query in queries:
        pool = np.asarray(query["pool_index"])
        relevant = np.isin(pool, np.asarray(query["relevant_index"]))
        similarity = features[pool] @ text_bank[query["text"]]
        order = R.rank_order(similarity, tie_breaker[pool])
        rows.append({"query_id": query["query_id"], "family": query["family"],
                     "scope": query["scope"], "category": query["category"] or "",
                     "attributes": "+".join(c["attribute"] for c in query["constraints"]),
                     "direction": query["constraints"][0]["direction"],
                     **R.rank_metrics(relevant, order)})
    return pd.DataFrame(rows)


def evaluate_static(queries, static_scores, tie_breaker):
    """A system with one score per product, independent of the query (popularity)."""
    rows = []
    for query in queries:
        pool = np.asarray(query["pool_index"])
        relevant = np.isin(pool, np.asarray(query["relevant_index"]))
        order = R.rank_order(static_scores[pool], tie_breaker[pool])
        rows.append({"query_id": query["query_id"], "family": query["family"],
                     "scope": query["scope"], "category": query["category"] or "",
                     "attributes": "+".join(c["attribute"] for c in query["constraints"]),
                     "direction": query["constraints"][0]["direction"],
                     **R.rank_metrics(relevant, order)})
    return pd.DataFrame(rows)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-missing", action="store_true", default=True)
    args = ap.parse_args()

    template_choice = {}
    choice_path = R.EXP22 / "artifacts/clip_prompt_selection.json"
    if choice_path.is_file():
        template_choice = R.write_json.__globals__["json"].loads(choice_path.read_text())

    blocks = {split: R.label_block(split) for split in ("development", "test")}
    queries = {split: R.build_queries(blocks[split]) for split in blocks}
    R.write_json(R.ARTIFACTS / "query_manifest.json", {
        "seed": R.SEED,
        "admission": {"min_pool": R.MIN_POOL, "min_relevant": R.MIN_RELEVANT,
                      "min_irrelevant": R.MIN_IRRELEVANT},
        "attributes": R.ATTRIBUTES,
        "counts": {split: len(q) for split, q in queries.items()},
        "queries": {split: [{k: v for k, v in q.items()
                             if k not in ("pool_index", "relevant_index")}
                            for q in q_list] for split, q_list in queries.items()},
    })

    # one shared tie-breaker per split
    tie = {}
    for split, block in blocks.items():
        rng = np.random.default_rng(R.SEED)
        tie[split] = rng.permutation(len(block["product_ids"])).astype(np.int64)

    available = []
    for display, key, family in TACTILE_SYSTEMS:
        dev = load_attribute_scores(key, "development", blocks["development"]["product_ids"],
                                    template_choice)
        test = load_attribute_scores(key, "test", blocks["test"]["product_ids"], template_choice)
        if dev is None or test is None:
            print(f"skip {display}: no cached Exp22 scores", flush=True)
            continue
        available.append((display, key, family, dev, test))

    # ---- aggregator selected on DEVELOPMENT queries only, shared by all systems
    multi = [q for q in queries["development"] if len(q["constraints"]) > 1]
    aggregator_table = {}
    for aggregator in ("mean_probability", "mean_log_probability", "min_probability"):
        per_system = []
        for display, _key, _family, dev, _test in available:
            frame = evaluate(multi, dev, aggregator, tie["development"])
            per_system.append(frame["ndcg@10"].mean())
        aggregator_table[aggregator] = float(np.mean(per_system)) if per_system else None
    aggregator = max(aggregator_table, key=lambda a: aggregator_table[a] or -1)
    R.write_json(R.ARTIFACTS / "aggregator_selection.json", {
        "selected": aggregator,
        "selected_on": "development-split multi-constraint queries, macro NDCG@10 averaged over all systems",
        "n_development_multi_constraint_queries": len(multi),
        "macro_ndcg_by_aggregator": aggregator_table,
        "note": "One aggregator for every system; no system has a bespoke combination rule.",
    })
    print(f"aggregator selected on development: {aggregator}  {aggregator_table}", flush=True)

    # ---- test evaluation
    all_rows, summary = [], []
    popularity = popularity_scores(blocks["test"]["product_ids"])
    frame = evaluate_static(queries["test"], popularity, tie["test"])
    frame.insert(0, "system", "Popularity (non-tactile)")
    frame.insert(1, "family_type", "baseline")
    all_rows.append(frame)

    for display, _key, family, _dev, test in available:
        frame = evaluate(queries["test"], test, aggregator, tie["test"])
        frame.insert(0, "system", display)
        frame.insert(1, "family_type", family)
        all_rows.append(frame)

    # natural-language text-image retrieval, the "search box" baseline
    features_path = R.CACHE / "fashionclip_image_features__test.npz"
    text_path = R.CACHE / "fashionclip_text_features.npz"
    if features_path.is_file() and text_path.is_file():
        fblob = np.load(features_path, allow_pickle=True)
        tblob = np.load(text_path, allow_pickle=True)
        position = {str(p): i for i, p in enumerate(fblob["product_ids"])}
        features = fblob["features"][[position[p] for p in blocks["test"]["product_ids"]]]
        text_bank = {str(t): v for t, v in zip(tblob["texts"], tblob["features"])}
        frame = evaluate_text_image(queries["test"], features, text_bank, tie["test"])
        frame.insert(0, "system", "FashionCLIP text-image (query sentence)")
        frame.insert(1, "family_type", "clip")
        all_rows.append(frame)
    else:
        print("skip FashionCLIP text-image: feature cache missing", flush=True)

    per_query = pd.concat(all_rows, ignore_index=True)
    per_query.to_csv(R.RESULTS / "retrieval_per_query.csv", index=False)

    metrics = ["ndcg@10", "precision@10", "recall@10", "map@10"]
    for name, subset in (("retrieval_main", per_query),
                         ("retrieval_same_category",
                          per_query[per_query["scope"] == "same_category"])):
        grouped = subset.groupby(["system", "family_type"])
        block = grouped[metrics].mean().reset_index()
        block = block.merge(grouped.size().rename("n_queries").reset_index(),
                            on=["system", "family_type"])
        # paired bootstrap over queries against the two reference systems
        for reference in ("Popularity (non-tactile)", "Category-only (no pixels)"):
            deltas, lows, highs = [], [], []
            ref = (subset[subset["system"] == reference]
                   .set_index("query_id")["ndcg@10"])
            for system in block["system"]:
                mine = subset[subset["system"] == system].set_index("query_id")["ndcg@10"]
                shared = mine.index.intersection(ref.index)
                stat = R.bootstrap_delta(mine.loc[shared].to_numpy(),
                                         ref.loc[shared].to_numpy())
                deltas.append(stat["delta"]); lows.append(stat["ci_low"]); highs.append(stat["ci_high"])
            tag = "vs_popularity" if "Popularity" in reference else "vs_category_only"
            block[f"dNDCG_{tag}"] = deltas
            block[f"dNDCG_{tag}_ci_low"] = lows
            block[f"dNDCG_{tag}_ci_high"] = highs
        block = block.sort_values("ndcg@10", ascending=False)
        block.to_csv(R.RESULTS / f"{name}.csv", index=False)
        summary.append((name, block))

    (per_query.groupby(["system", "attributes", "direction"])[metrics].mean().reset_index()
     .to_csv(R.RESULTS / "retrieval_per_attribute.csv", index=False))
    (per_query[per_query["category"] != ""]
     .groupby(["system", "category"])[metrics].mean().reset_index()
     .to_csv(R.RESULTS / "retrieval_per_category.csv", index=False))
    (per_query.groupby(["system", "family"])[metrics].mean().reset_index()
     .to_csv(R.RESULTS / "retrieval_per_family.csv", index=False))

    # --- head-to-head paired contrasts against our predictor -------------------
    # The report's central claim is that the natural-language search box loses its
    # apparent ability once category is held fixed, while Last2 does not.  That is a
    # statement about the gap BETWEEN two systems, so it needs a paired test between
    # them -- comparing each separately to the control does not establish it.
    head_to_head = []
    reference_system = "Last2 (ours)"
    for scope_name, subset in (("all_queries", per_query),
                               ("same_category",
                                per_query[per_query["scope"] == "same_category"])):
        if subset.empty or reference_system not in set(subset["system"]):
            continue
        reference = subset[subset["system"] == reference_system].set_index("query_id")["ndcg@10"]
        for system in sorted(set(subset["system"])):
            if system == reference_system:
                continue
            mine = subset[subset["system"] == system].set_index("query_id")["ndcg@10"]
            shared = mine.index.intersection(reference.index)
            stat = R.bootstrap_delta(reference.loc[shared].to_numpy(),
                                     mine.loc[shared].to_numpy())
            head_to_head.append({
                "scope": scope_name, "reference": reference_system, "system": system,
                "n_queries": int(len(shared)),
                "delta_ndcg_reference_minus_system": stat["delta"],
                "ci95_low": stat["ci_low"], "ci95_high": stat["ci_high"],
                "significant": bool(stat["ci_low"] is not None
                                    and (stat["ci_low"] > 0 or stat["ci_high"] < 0)),
            })
    pd.DataFrame(head_to_head).to_csv(R.RESULTS / "retrieval_head_to_head.csv", index=False)
    print("\n===== head-to-head vs Last2 (paired over queries) =====")
    frame_h2h = pd.DataFrame(head_to_head)
    if not frame_h2h.empty:
        print(frame_h2h.to_string(index=False, float_format=lambda v: f"{v:.4f}"))

    for name, block in summary:
        print(f"\n===== {name} =====")
        show = block[["system", "family_type", "n_queries", "ndcg@10", "precision@10",
                      "map@10", "dNDCG_vs_category_only", "dNDCG_vs_category_only_ci_low",
                      "dNDCG_vs_category_only_ci_high"]]
        print(show.to_string(index=False, float_format=lambda v: f"{v:.4f}"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
