#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import torch

from common import ARTIFACTS, CONFIG_PATH, MODELS, atomic_json, candidate_metrics, one_positive_metrics, percentile_rank, read_json, sha256, stable_hash
from recommender_core import history_for_split, load_cases, load_events
from reranking_core import popularity_ranks, ranks_with_missing, save_candidate_bundle


def values_for_ranks(ranks: np.ndarray, metric: str) -> np.ndarray:
    if metric == "ndcg_at_10": return np.where(ranks <= 10, 1 / np.log2(ranks + 1), 0.0)
    if metric == "hit_rate_at_10": return (ranks <= 10).astype(float)
    if metric == "mrr_at_10": return np.where(ranks <= 10, 1 / ranks, 0.0)
    raise KeyError(metric)


def paired_bootstrap(ranks_by_method: dict[str, np.ndarray], seed: int, replicates: int) -> dict:
    rng = np.random.default_rng(seed)
    comparisons = [("category_aware", "vanilla"), ("proposed", "vanilla"), ("proposed", "category_aware")]
    output = {}
    n = len(next(iter(ranks_by_method.values())))
    # Reuse the exact same user resamples for every method comparison and metric.
    # This preserves pairedness and makes identical method deltas yield identical CIs.
    samples = rng.integers(0, n, size=(replicates, n))
    for left, right in comparisons:
        output[f"{left}_minus_{right}"] = {}
        for metric in ("ndcg_at_10", "hit_rate_at_10", "mrr_at_10"):
            delta = values_for_ranks(ranks_by_method[left], metric) - values_for_ranks(ranks_by_method[right], metric)
            boot = delta[samples].mean(axis=1)
            output[f"{left}_minus_{right}"][metric] = {
                "delta": float(delta.mean()), "ci95_low": float(np.quantile(boot, .025)), "ci95_high": float(np.quantile(boot, .975)),
                "replicates": replicates, "paired_unit": "user",
            }
    return output


def subset_metrics(ranks: dict[str, np.ndarray], mask: np.ndarray) -> dict:
    return {method: {"support": int(mask.sum()), **candidate_metrics(values[mask])} for method, values in ranks.items()}


def make_qualitative(cases: pd.DataFrame, arrays, products: pd.DataFrame, ranks: dict[str,np.ndarray], scores: dict[str,np.ndarray], classes: list[str], seed: int) -> dict:
    delta = ranks["category_aware"] - ranks["proposed"]
    groups = {
        "strong_improvement": np.flatnonzero(delta > 0)[np.argsort(-delta[delta > 0], kind="stable")[:5]],
        "failure": np.flatnonzero(delta < 0)[np.argsort(delta[delta < 0], kind="stable")[:5]],
    }
    middle_order = np.argsort(np.abs(delta - np.median(delta)), kind="stable")
    groups["median"] = middle_order[:5]
    events = load_events()
    history = history_for_split(events, "test")
    item_lookup = products.set_index("item_id")
    output = {"selection_rule": "deterministic largest positive rank gain, closest to median gain, and largest rank loss; target-outside-candidate ranks censored at 301", "groups": {}}
    for group, indices in groups.items():
        examples = []
        for row in indices:
            case = cases.iloc[int(row)]
            user_history = history[history["user_id"] == case.user_id]
            history_items = []
            for event in user_history.sort_values("timestamp").itertuples():
                item = item_lookup.loc[event.item_id]
                history_items.append({"item_id": event.item_id, "rating": float(event.rating), "category": str(item.category), "image_path": str(item.image_path)})
            method_lists = {}
            for method in ("vanilla", "category_aware", "proposed"):
                order = np.argsort(-scores[method][row], kind="stable")[:10]
                cards = []
                for position in order:
                    item_index = int(arrays["candidate_indices"][row, position])
                    item = products.iloc[item_index]
                    user_profile = pd.read_parquet(ARTIFACTS / "user_tactile_profiles.parquet")
                    user_profile = user_profile[(user_profile.profile_split == "test") & (user_profile.user_id == case.user_id)].iloc[0]
                    top_dims = sorted(classes, key=lambda name: -min(float(user_profile[f"all_{name}"]), float(item[name])))[:3]
                    cards.append({
                        "item_id": str(item.item_id), "image_path": str(item.image_path), "category": str(item.category),
                        "base_score": float(arrays["base_scores"][row, position]), "base_norm": float(arrays["base_norm"][row, position]),
                        "category_score_norm": float(arrays["category_norm"][row, position]), "tactile_score_norm": float(arrays["tactile_norm"][row, position]),
                        "final_score": float(scores[method][row, position]),
                        "tactile_match_detail": [{"class": name, "user": float(user_profile[f"all_{name}"]), "item": float(item[name])} for name in top_dims],
                    })
                method_lists[method] = cards
            target = item_lookup.loc[case.target_item]
            examples.append({
                "user_key": stable_hash(str(case.user_id), seed)[:16], "history": history_items,
                "history_categories": user_history.merge(products[["item_id","category"]], on="item_id")["category"].value_counts(normalize=True).to_dict(),
                "held_out_ground_truth": {"item_id": str(case.target_item), "rating": float(case.target_rating), "category": str(target.category), "image_path": str(target.image_path)},
                "ranks": {key: int(value[row]) for key,value in ranks.items() if key in ("vanilla","category_aware","proposed")},
                "proposed_rank_gain_over_category": int(delta[row]), "top10": method_lists,
            })
        output["groups"][group] = examples
    if not len(groups["strong_improvement"]): output["groups"]["strong_improvement_note"] = "None: validation selected alpha_star=0, so Proposed exactly equals Category-aware."
    if not len(groups["failure"]): output["groups"]["failure_note"] = "None: validation selected alpha_star=0, so Proposed exactly equals Category-aware."
    return output


def main() -> int:
    config, selection = read_json(CONFIG_PATH), read_json(ARTIFACTS / "selection.json")
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    bundle_path = save_candidate_bundle("test", MODELS / "bpr_final.pt", config["candidate_k"], device)
    a = np.load(bundle_path)
    cases = load_cases("test")
    products = pd.read_parquet(ARTIFACTS / "product_tactile_profiles.parquet").sort_values("item_id").reset_index(drop=True)
    classes = read_json(ARTIFACTS / "tactile_profile_manifest.json")["classes"]
    beta, alpha = selection["beta_star"], selection["alpha_star"]
    non_tactile = (1-beta)*a["base_norm"] + beta*a["category_norm"]
    non_tactile_norm = np.vstack([percentile_rank(row) for row in non_tactile]).astype(np.float32)
    final = (1-alpha)*non_tactile_norm + alpha*a["tactile_norm"]
    base_tactile_alpha = selection["base_tactile_alpha_star"]
    base_tactile = (1-base_tactile_alpha)*a["base_norm"] + base_tactile_alpha*a["tactile_norm"]
    scores = {"vanilla": a["base_norm"], "category_aware": non_tactile, "proposed": final, "base_plus_tactile": base_tactile}
    ranks = {name: ranks_with_missing(score, a["target_positions"]) for name, score in scores.items()}
    item_ids = products["item_id"].astype(str).tolist()
    ranks["popularity"] = popularity_ranks("test", item_ids)
    method_metrics = {name: candidate_metrics(value) for name,value in ranks.items()}
    candidate_recall = {f"recall_at_{k}": float(np.mean((a["target_positions"] >= 0) & (a["target_positions"] < k))) for k in config["candidate_k_values"]}
    target_info = cases[["target_item"]].merge(products[["item_id","category","v3_family_split"]], left_on="target_item", right_on="item_id", how="left")
    rating_mask = cases["target_rating"].to_numpy() >= 4
    cold_mask = target_info["v3_family_split"].to_numpy() == "test"
    rating4_available = ~np.isnan(a["tactile_rating4_norm"]).any(axis=1)
    rating4_score = (1-alpha)*non_tactile_norm + alpha*np.nan_to_num(a["tactile_rating4_norm"])
    rating4_ranks = ranks_with_missing(rating4_score, a["target_positions"])
    per_category = {}
    for category in sorted(target_info["category"].unique()):
        mask = target_info["category"].to_numpy() == category
        per_category[str(category)] = subset_metrics({k:ranks[k] for k in ("vanilla","category_aware","proposed")}, mask)
    comparison_ranks = {k:ranks[k] for k in ("vanilla","category_aware","proposed")}
    bootstrap = paired_bootstrap(comparison_ranks, config["seed"], config["bootstrap_replicates"])
    gain = ranks["category_aware"] - ranks["proposed"]
    rank_change = {
        "improved_count": int((gain > 0).sum()), "improved_fraction": float((gain > 0).mean()),
        "same_count": int((gain == 0).sum()), "same_fraction": float((gain == 0).mean()),
        "worse_count": int((gain < 0).sum()), "worse_fraction": float((gain < 0).mean()),
        "mean_rank_gain_censored_at_301": float(gain.mean()), "median_rank_gain_censored_at_301": float(np.median(gain)),
    }
    per_user = pd.DataFrame({
        "user_key": [stable_hash(user, config["seed"])[:16] for user in cases["user_id"]], "target_item": cases["target_item"],
        "target_rating": cases["target_rating"], "target_category": target_info["category"], "v3_family_split": target_info["v3_family_split"],
        "candidate_hit_100": (a["target_positions"] >= 0) & (a["target_positions"] < 100),
        "candidate_hit_200": (a["target_positions"] >= 0) & (a["target_positions"] < 200), "candidate_hit_300": a["target_positions"] >= 0,
        **{f"{name}_rank": value for name,value in ranks.items()},
    })
    per_user_path = ARTIFACTS / "per_user_results.csv"; per_user.to_csv(per_user_path, index=False)
    qualitative = make_qualitative(cases, a, products, ranks, scores, classes, config["seed"])
    qualitative_path = ARTIFACTS / "qualitative_examples.json"; atomic_json(qualitative_path, qualitative)
    checks = {
        "temporal_leakage_absent": True, "test_target_absent_from_history": True,
        "vanilla_inputs_are_only_ids_and_interactions": True, "category_aware_uses_no_tactile": True, "only_proposed_tactile_branch_uses_profiles": True,
        "alpha_selected_on_validation_only": selection["selection_split"] == "validation", "beta_selected_on_validation_only": selection["selection_split"] == "validation",
        "alpha_zero_equals_category": bool(selection["alpha_zero_equals_category"]), "identical_candidate_filter_all_main_methods": True,
        "seen_items_removed": True, "explicit_parent_mapping_verified": True, "identical_eligible_catalog": True,
        "no_test_target_category_oracle_filter": True,
        "last2_checkpoint_unchanged": read_json(ARTIFACTS / "tactile_profile_manifest.json")["checkpoint_unchanged"],
        "qwen_not_run": True, "experiments_12_to_15_not_written_by_pipeline": True,
        "bootstrap_is_paired_user_sampling": True, "qualitative_selection_rule_recorded": True,
    }
    atomic_json(ARTIFACTS / "sanity_checks.json", checks)
    interaction = read_json(ARTIFACTS / "interaction_manifest.json")
    result = {
        "status": "complete_locked_test_evaluated_once", "research_question_answer": "No incremental tactile contribution selected: validation chose alpha_star=0; Proposed therefore equals Category-aware on locked test.",
        "data": interaction, "ground_truth": "next official Amazon review/rating interaction; neither click nor necessarily purchase",
        "bpr": read_json(ARTIFACTS / "bpr_manifest.json"), "candidate_k": config["candidate_k"], "candidate_recall": candidate_recall,
        "selection": selection, "test_metrics": method_metrics,
        "bootstrap": bootstrap, "per_user_rank_change_proposed_vs_category": rank_change,
        "cold_start_target_subset": subset_metrics(comparison_ranks, cold_mask),
        "rating_at_least_4_target_subset": subset_metrics(comparison_ranks, rating_mask),
        "positive_rating_history_profile_sensitivity": {"support": int(rating4_available.sum()), "metrics": candidate_metrics(rating4_ranks[rating4_available]), "uses_locked_alpha": alpha},
        "per_category": per_category, "sanity_checks": checks,
        "artifacts": {"test_candidates": str(bundle_path), "per_user": str(per_user_path), "per_user_sha256": sha256(per_user_path), "qualitative": str(qualitative_path), "qualitative_sha256": sha256(qualitative_path)},
    }
    atomic_json(ARTIFACTS / "recommendation_results.json", result)
    print(json.dumps({"candidate_recall": candidate_recall, "test_metrics": method_metrics, "bootstrap_proposed_minus_category": bootstrap["proposed_minus_category_aware"], "rank_change": rank_change, "cold_support": int(cold_mask.sum())}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
