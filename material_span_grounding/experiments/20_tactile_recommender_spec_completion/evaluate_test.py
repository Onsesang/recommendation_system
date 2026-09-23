"""Open the locked Exp20 exploratory test gate and evaluate selected models.

This is post-lock orchestration only: it reuses the frozen model/metric code in
``models_exp20.py`` and does not train, select, tune, or change candidate
budgets after validation selection.
"""
from __future__ import annotations

import gc
from pathlib import Path

import numpy as np
import pandas as pd
import torch

from common import ART, CONFIG, EXP16, event, load_json, metric_dict, save_json, sha, transition_state, require_state
from models_exp20 import RecData20, evaluate_exact, make_model, setup


VARIANT_ORDER = ["I", "I_T", "I_VX", "I_VX_T", "I_VX_T_SHUFFLE"]


def dcg10_from_ranks(ranks: np.ndarray) -> np.ndarray:
    ranks = np.asarray(ranks)
    ok = (ranks > 0) & (ranks <= 10)
    return np.where(ok, 1.0 / np.log2(np.maximum(ranks, 1) + 1), 0.0)


def summarize_pair(label: str, base_path: Path, prop_path: Path) -> dict:
    base = pd.read_parquet(base_path, columns=["uid", "iid", "rank"])
    prop = pd.read_parquet(prop_path, columns=["uid", "iid", "rank"])
    if len(base) != len(prop):
        raise RuntimeError(f"{label}: row count mismatch")
    if not (base[["uid", "iid"]].to_numpy() == prop[["uid", "iid"]].to_numpy()).all():
        raise RuntimeError(f"{label}: target alignment mismatch")
    base_rank = base["rank"].to_numpy(dtype=np.int64)
    prop_rank = prop["rank"].to_numpy(dtype=np.int64)
    delta_rank = base_rank - prop_rank
    delta_dcg10 = dcg10_from_ranks(prop_rank) - dcg10_from_ranks(base_rank)
    return {
        "label": label,
        "users": int(len(base_rank)),
        "mean_delta_ndcg_at_10": float(delta_dcg10.mean()),
        "mean_rank_improvement": float(delta_rank.mean()),
        "median_rank_improvement": float(np.median(delta_rank)),
        "improved_rank_users": int((delta_rank > 0).sum()),
        "worse_rank_users": int((delta_rank < 0).sum()),
        "unchanged_rank_users": int((delta_rank == 0).sum()),
        "top10_gain_users": int(((prop_rank <= 10) & (base_rank > 10)).sum()),
        "top10_loss_users": int(((base_rank <= 10) & (prop_rank > 10)).sum()),
    }


def main() -> None:
    state = require_state(
        "validation_locked_before_exp20_test",
        "exploratory_test_opened_no_retuning",
        "complete_locked_posthoc_exploratory",
    )
    selection_path = ART / "validation_selection.json"
    if not selection_path.exists():
        raise RuntimeError("validation_selection.json is missing")
    selection = load_json(selection_path)
    if selection.get("status") != "validation_locked":
        raise RuntimeError("validation is not locked")

    if state["state"] == "validation_locked_before_exp20_test":
        transition_state(
            "validation_locked_before_exp20_test",
            "exploratory_test_opened_no_retuning",
            validation_selection_sha256=sha(selection_path),
            exp16_test_targets_sha256=sha(EXP16 / "data/test_targets.parquet"),
        )

    event("exp20_test", "started")
    cfg = load_json(CONFIG / "model_variants.json")
    d = RecData20()
    device = setup(int(cfg["primary_seed"]))
    results: dict[str, dict] = {}
    per_user_paths: dict[str, str] = {}

    for variant in VARIANT_ORDER:
        selected = selection["model_selections"].get(variant)
        if selected is None:
            raise RuntimeError(f"missing selected model for {variant}")
        run = selected["selected_run"]
        checkpoint = Path(run["checkpoint"])
        if not checkpoint.is_absolute():
            checkpoint = (Path.cwd() / checkpoint).resolve()
        if sha(checkpoint) != selected["checkpoint_sha256"]:
            raise RuntimeError(f"checkpoint hash mismatch for {variant}")
        out_path = ART / f"test_{variant}_per_user.parquet"
        if out_path.exists():
            frame = pd.read_parquet(out_path, columns=["rank", "variant"])
            if len(frame) == len(pd.read_parquet(EXP16 / "data/test_targets.parquet", columns=["uid"])):
                metrics = {"all_official_targets": metric_dict(frame["rank"].to_numpy()), "personalized_users": None}
                results[variant] = {
                    "status": "complete",
                    "selected_learning_rate": selected["selected_learning_rate"],
                    "selected_epoch": selected["selected_epoch"],
                    "checkpoint": str(checkpoint),
                    "checkpoint_sha256": selected["checkpoint_sha256"],
                    "candidate_budget": selection["candidate_budget"].get(variant),
                    "test": metrics,
                    "per_user_path": str(out_path),
                    "per_user_sha256": sha(out_path),
                    "resume_used_existing_per_user_file": True,
                }
                per_user_paths[variant] = str(out_path)
                event("exp20_test_variant", "complete", variant=variant, reused=True, ndcg_at_10=metrics["all_official_targets"]["ndcg_at_10"])
                continue

        event("exp20_test_variant", "started", variant=variant)
        model = make_model(variant, d, cfg, device).to(device)
        ck = torch.load(checkpoint, map_location=device, weights_only=False)
        model.load_state_dict(ck["state_dict"])
        model.eval()
        metrics, _ = evaluate_exact(model, d, "test", device, batch_size=int(cfg.get("evaluation_batch_size", 256)), save_to=out_path)
        results[variant] = {
            "status": "complete",
            "selected_learning_rate": selected["selected_learning_rate"],
            "selected_epoch": selected["selected_epoch"],
            "checkpoint": str(checkpoint),
            "checkpoint_sha256": selected["checkpoint_sha256"],
            "candidate_budget": selection["candidate_budget"].get(variant),
            "test": metrics,
            "per_user_path": str(out_path),
            "per_user_sha256": sha(out_path),
            "resume_used_existing_per_user_file": False,
        }
        per_user_paths[variant] = str(out_path)
        event("exp20_test_variant", "complete", variant=variant, ndcg_at_10=metrics["all_official_targets"]["ndcg_at_10"])
        del model, ck
        gc.collect()
        if device == "cuda":
            torch.cuda.empty_cache()

    contrasts = {
        "primary_I_VX_T_minus_I_VX": summarize_pair(
            "primary_I_VX_T_minus_I_VX",
            Path(per_user_paths["I_VX"]),
            Path(per_user_paths["I_VX_T"]),
        ),
        "aligned_tactile_minus_shuffle": summarize_pair(
            "aligned_tactile_minus_shuffle",
            Path(per_user_paths["I_VX_T_SHUFFLE"]),
            Path(per_user_paths["I_VX_T"]),
        ),
        "tactile_ablation_I_T_minus_I": summarize_pair(
            "tactile_ablation_I_T_minus_I",
            Path(per_user_paths["I"]),
            Path(per_user_paths["I_T"]),
        ),
    }
    output = {
        "status": "complete_locked_posthoc_exploratory",
        "claim_track": "locked_posthoc_exploratory_followup",
        "confirmatory": False,
        "validation_selection_sha256": sha(selection_path),
        "test_targets_sha256": sha(EXP16 / "data/test_targets.parquet"),
        "results": results,
        "contrasts": contrasts,
        "post_lock_orchestration_note": "evaluate_test.py was added only to orchestrate locked checkpoints with frozen evaluate_exact metric code.",
    }
    save_json(ART / "test_results.json", output)
    if require_state("exploratory_test_opened_no_retuning", "complete_locked_posthoc_exploratory")["state"] == "exploratory_test_opened_no_retuning":
        transition_state(
            "exploratory_test_opened_no_retuning",
            "complete_locked_posthoc_exploratory",
            test_results_sha256=sha(ART / "test_results.json"),
        )
    event("exp20_test", "complete", variants=len(results), test_results_sha256=sha(ART / "test_results.json"))


if __name__ == "__main__":
    main()
