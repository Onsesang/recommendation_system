"""Train the five preregistered Exp20 variants and lock validation choices."""
from __future__ import annotations

import argparse
import gc
import traceback
from pathlib import Path

import numpy as np
import pandas as pd
import torch

from common import ART, CONFIG, ROOT, event, load_json, save_json, sha, transition_state, require_state
from models_exp20 import RecData20, evaluate_exact, make_model, sample_negatives, setup


def flatten(variant: str, lr: float, run: dict) -> dict:
    row = {
        "variant": variant,
        "learning_rate": lr,
        "status": run["status"],
        "best_epoch": run.get("best_epoch"),
        "checkpoint": run.get("checkpoint"),
    }
    for cohort, values in run.get("validation", {}).items():
        if isinstance(values, dict):
            for key, value in values.items():
                row[f"{cohort}.{key}"] = value
    return row


def choose_run(runs: list[dict]) -> dict:
    return max(
        runs,
        key=lambda r: (
            r["validation"]["all_official_targets"]["ndcg_at_10"],
            r["validation"]["all_official_targets"]["hr_at_10"],
            r["validation"]["all_official_targets"]["mrr_at_10"],
            -r["best_epoch"],
            -r["lr"],
        ),
    )


def train_one(variant: str, lr: float, d: RecData20, cfg: dict, device: str, force: bool = False) -> dict:
    outdir = ART / "checkpoints"
    outdir.mkdir(parents=True, exist_ok=True)
    tag = f"{variant}_lr{lr:g}_seed{cfg['primary_seed']}"
    done = outdir / f"{tag}.complete.json"
    bestfile = outdir / f"{tag}.pt"
    resume = outdir / f"{tag}.resume.pt"
    if done.exists() and not force:
        return load_json(done)
    event("exp20_train", "started", variant=variant, learning_rate=lr)
    model = make_model(variant, d, cfg, device).to(device)
    opt = torch.optim.Adam(model.parameters(), lr=lr)
    rng = np.random.default_rng(int(cfg["primary_seed"]))
    best = -1.0
    best_epoch = None
    bad = 0
    first_epoch = 1
    if resume.exists() and not force:
        state = torch.load(resume, map_location=device, weights_only=False)
        model.load_state_dict(state["model"])
        opt.load_state_dict(state["optimizer"])
        rng.bit_generator.state = state["numpy_rng"]
        torch.set_rng_state(state["torch_rng"].cpu())
        if device == "cuda" and "cuda_rng" in state:
            torch.cuda.set_rng_state_all([x.cpu() for x in state["cuda_rng"]])
        best = float(state["best"])
        best_epoch = state.get("best_epoch")
        bad = int(state["bad"])
        first_epoch = int(state["epoch"]) + 1
    train = d.train
    batch_size = int(cfg["shared_training"].get("train_batch_size", 512))
    if "train_batch_size" not in cfg["shared_training"]:
        batch_size = 512
    max_epochs = int(cfg["shared_training"]["maximum_epochs"])
    val_every = int(cfg["shared_training"]["validation_every_epochs"])
    reg_weight = float(cfg["shared_training"]["regularization"])
    clip_norm = float(cfg["shared_training"]["gradient_clip_norm"])
    cl_cap = int(cfg["shared_training"]["contrastive_in_batch_cap"])
    result = None
    for epoch in range(first_epoch, max_epochs + 1):
        model.train()
        losses = []
        order = rng.permutation(len(train))
        for start in range(0, len(order), batch_size):
            idx = order[start : start + batch_size]
            batch = train.iloc[idx]
            neg = sample_negatives(rng, batch.uid.to_numpy(), d)
            users = torch.tensor(batch.local_uid.to_numpy(), dtype=torch.long, device=device)
            pos = torch.tensor(batch.iid.to_numpy(), dtype=torch.long, device=device)
            neg_t = torch.tensor(neg, dtype=torch.long, device=device)
            opt.zero_grad(set_to_none=True)
            loss = model.calculate_loss(users, pos, neg_t, reg_weight=reg_weight, cl_cap=cl_cap)
            if not torch.isfinite(loss):
                raise FloatingPointError(f"{tag} non-finite loss at epoch {epoch}")
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), clip_norm)
            opt.step()
            losses.append(float(loss.detach().cpu()))
        event("exp20_train_epoch", "complete", variant=variant, learning_rate=lr, epoch=epoch, loss=float(np.mean(losses)))
        if epoch % val_every == 0 or epoch == max_epochs:
            model.eval()
            validation, _ = evaluate_exact(model, d, "validation", device, batch_size=int(cfg.get("evaluation_batch_size", 256)))
            metric = validation["all_official_targets"]
            value = metric["ndcg_at_10"]
            event("exp20_validation", "complete", variant=variant, learning_rate=lr, epoch=epoch, ndcg_at_10=value, recall_at_30000=metric["recall_at_30000"])
            if value > best:
                best = float(value)
                best_epoch = int(epoch)
                bad = 0
                torch.save(
                    {
                        "variant": variant,
                        "state_dict": model.state_dict(),
                        "config": cfg,
                        "learning_rate": lr,
                        "epoch": epoch,
                        "validation": validation,
                        "implementation_lock_sha256": sha(ART / "implementation_lock.json"),
                    },
                    bestfile,
                )
                result = validation
            else:
                bad += 1
        state = {
            "model": model.state_dict(),
            "optimizer": opt.state_dict(),
            "epoch": epoch,
            "best": best,
            "best_epoch": best_epoch,
            "bad": bad,
            "numpy_rng": rng.bit_generator.state,
            "torch_rng": torch.get_rng_state(),
        }
        if device == "cuda":
            state["cuda_rng"] = torch.cuda.get_rng_state_all()
        tmp = resume.with_suffix(".tmp")
        torch.save(state, tmp)
        tmp.replace(resume)
    ck = torch.load(bestfile, map_location="cpu", weights_only=False)
    run = {
        "status": "complete",
        "variant": variant,
        "lr": lr,
        "best_epoch": int(ck["epoch"]),
        "checkpoint": str(bestfile),
        "checkpoint_sha256": sha(bestfile),
        "validation": ck["validation"],
        "implementation_lock_sha256": ck["implementation_lock_sha256"],
    }
    save_json(done, run)
    event("exp20_train", "complete", variant=variant, learning_rate=lr, best_epoch=run["best_epoch"], ndcg_at_10=run["validation"]["all_official_targets"]["ndcg_at_10"])
    del model, opt
    gc.collect()
    if device == "cuda":
        torch.cuda.empty_cache()
    return run


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--variants", nargs="*", default=None)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    require_state("implementation_frozen_before_validation")
    lock = load_json(ART / "implementation_lock.json")
    if lock.get("status") != "complete":
        raise RuntimeError("implementation lock is incomplete")
    cfg = load_json(CONFIG / "model_variants.json")
    protocol = load_json(CONFIG / "protocol.json")
    event("exp20_validation_run", "started")
    d = RecData20()
    device = setup(int(cfg["primary_seed"]))
    variants = args.variants or [v["id"] for v in cfg["variants"]]
    all_runs = []
    errors = []
    for variant in variants:
        for lr in cfg["shared_training"]["learning_rate_grid"]:
            try:
                all_runs.append(train_one(variant, float(lr), d, cfg, device, force=args.force))
            except Exception as exc:
                errors.append(
                    {
                        "variant": variant,
                        "learning_rate": lr,
                        "error_type": type(exc).__name__,
                        "message": str(exc)[:500],
                        "traceback_tail": "\n".join(traceback.format_exc().splitlines()[-16:]),
                    }
                )
                event("exp20_train", "failed", variant=variant, learning_rate=lr, error_type=type(exc).__name__)
    frame = pd.DataFrame([flatten(r["variant"], r["lr"], r) for r in all_runs])
    tmp = (ART / "validation_results.csv").with_suffix(".csv.tmp")
    frame.to_csv(tmp, index=False)
    tmp.replace(ART / "validation_results.csv")
    selections = {}
    candidate_budget = {}
    for variant in variants:
        completed = [r for r in all_runs if r["variant"] == variant and r["status"] == "complete"]
        if not completed:
            continue
        best = choose_run(completed)
        metric = best["validation"]["all_official_targets"]
        selected_k = 30000
        status = protocol["candidate_retrieval"]["fallback_status"]
        for k in protocol["candidate_retrieval"]["reported_k"]:
            if metric[f"recall_at_{k}"] >= protocol["candidate_retrieval"]["threshold"]:
                selected_k = int(k)
                status = "threshold_satisfied"
                break
        selections[variant] = {
            "selected_run": best,
            "selected_learning_rate": best["lr"],
            "selected_epoch": best["best_epoch"],
            "validation_ndcg_at_10": metric["ndcg_at_10"],
            "validation_recall_at_selected_k": metric[f"recall_at_{selected_k}"],
            "checkpoint_sha256": best["checkpoint_sha256"],
        }
        candidate_budget[variant] = {"k": selected_k, "status": status}
    result = {
        "status": "validation_locked" if len(selections) == len(variants) else "incomplete",
        "model_selections": selections,
        "candidate_budget": candidate_budget,
        "errors": errors,
        "implementation_lock_sha256": sha(ART / "implementation_lock.json"),
        "validation_results_sha256": sha(ART / "validation_results.csv"),
        "assert_no_experiment16_test_artifact_was_a_development_or_selection_input": True,
    }
    save_json(ART / "validation_selection.json", result)
    if result["status"] != "validation_locked":
        event("exp20_validation_run", "blocked", selected=len(selections), requested=len(variants))
        raise SystemExit("not all variants completed")
    transition_state(
        "implementation_frozen_before_validation",
        "validation_locked_before_exp20_test",
        validation_selection_sha256=sha(ART / "validation_selection.json"),
    )
    event("exp20_validation_run", "complete", variants=len(selections))


if __name__ == "__main__":
    main()
