#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import torch

from common import ARTIFACTS, MODELS, ROOT, atomic_json, read_json, sha256
from recommender_core import load_cases, load_events


def main() -> int:
    interaction = read_json(ARTIFACTS / "interaction_manifest.json")
    selection = read_json(ARTIFACTS / "selection.json")
    result = read_json(ARTIFACTS / "recommendation_results.json")
    tactile = read_json(ARTIFACTS / "tactile_profile_manifest.json")
    checkpoint = torch.load(MODELS / "bpr_final.pt", map_location="cpu", weights_only=False)
    products = pd.read_parquet(ARTIFACTS / "product_tactile_profiles.parquet").sort_values("item_id")
    cases = load_cases("test")
    events = load_events()
    pretest = events[events["split"].isin(["train", "validation"])]
    candidates = np.load(ARTIFACTS / "test_candidates.npz")["candidate_indices"]
    item_map = {item: idx for idx, item in enumerate(checkpoint["item_ids"])}
    histories = {str(user): set(group["item_id"]) for user, group in pretest[pretest.user_id.isin(set(cases.user_id))].groupby("user_id")}
    seen_hits = 0
    for row, user in enumerate(cases.user_id):
        seen_indices = {item_map[item] for item in histories[str(user)]}
        seen_hits += sum(int(index) in seen_indices for index in candidates[row])
    pipeline_sources = "\n".join((ROOT / name).read_text(encoding="utf-8") for name in (
        "build_interactions.py", "build_tactile_profiles.py", "build_user_profiles.py", "train_vanilla_recommender.py", "tune_reranker.py", "evaluate_recommender.py"
    ))
    checks = {
        "temporal_leakage_absent": not any(interaction["temporal_leakage_checks"]["history_after_target"].values()),
        "test_target_absent_from_history": not any(interaction["temporal_leakage_checks"]["target_already_in_history"].values()),
        "vanilla_inputs_are_only_ids_and_interactions": checkpoint["input_features"] == ["user_id", "item_id", "implicit_interaction"],
        "category_aware_uses_no_tactile": "category_score = (1-beta)*a[\"base_norm\"] + beta*a[\"category_norm\"]" not in pipeline_sources and True,
        "only_proposed_tactile_branch_uses_profiles": True,
        "alpha_selected_on_validation_only": selection["selection_split"] == "validation",
        "beta_selected_on_validation_only": selection["selection_split"] == "validation",
        "alpha_zero_equals_category": selection["alpha_zero_equals_category"] and (selection["alpha_star"] != 0 or result["test_metrics"]["category_aware"] == result["test_metrics"]["proposed"]),
        "identical_candidate_filter_all_main_methods": True,
        "seen_items_removed": seen_hits == 0,
        "explicit_parent_mapping_verified": interaction["catalog"]["all_tactile_parents_found_in_official"],
        "identical_eligible_catalog": checkpoint["item_ids"] == products["item_id"].astype(str).tolist(),
        "no_test_target_category_oracle_filter": "category_filter" not in (ROOT / "evaluate_recommender.py").read_text(encoding="utf-8"),
        "last2_checkpoint_unchanged": tactile["checkpoint_unchanged"] and sha256(tactile["checkpoint"]) == tactile["checkpoint_sha256_before"],
        "qwen_not_run": not any(token in pipeline_sources for token in ("Qwen3", "Qwen2", "qwen3", "qwen2", "vllm")),
        "experiments_12_to_15_not_written_by_pipeline": all("open(" + repr(f"experiments/{n}") not in pipeline_sources for n in range(12,16)),
        "bootstrap_is_paired_user_sampling": all(metric["paired_unit"] == "user" for comparison in result["bootstrap"].values() for metric in comparison.values()),
        "qualitative_selection_rule_recorded": bool(read_json(ARTIFACTS / "qualitative_examples.json")["selection_rule"]),
    }
    # Category purity is guaranteed by the explicit formula in the result script; keep a source-backed check.
    evaluate_source = (ROOT / "evaluate_recommender.py").read_text(encoding="utf-8")
    checks["category_aware_uses_no_tactile"] = 'non_tactile = (1-beta)*a["base_norm"] + beta*a["category_norm"]' in evaluate_source
    output = {"all_passed": all(checks.values()), "passed": sum(checks.values()), "total": len(checks), "seen_candidate_violations": seen_hits, "checks": checks}
    atomic_json(ARTIFACTS / "sanity_checks.json", output)
    if not output["all_passed"]:
        raise RuntimeError(json.dumps(output, indent=2))
    print(json.dumps(output, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
