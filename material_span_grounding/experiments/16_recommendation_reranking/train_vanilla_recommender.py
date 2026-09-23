#!/usr/bin/env python3
from __future__ import annotations

import json
import time

import pandas as pd
import torch

from common import ARTIFACTS, CONFIG_PATH, MODELS, atomic_json, candidate_metrics, read_json, sha256
from recommender_core import BPRMF, full_catalog_ranks, load_cases, load_catalog, load_events, make_training_arrays, sample_negatives, save_checkpoint, seed_everything, train_model


def main() -> int:
    config = read_json(CONFIG_PATH)
    seed_everything(config["seed"])
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    _, item_ids, _ = load_catalog()
    events = load_events()
    train = events[events["split"] == "train"].copy()
    validation_cases = load_cases("validation")
    maximum = config["bpr"]["maximum_epochs"]
    patience = config["bpr"]["early_stopping_patience"]
    _, _, item_map = load_catalog()
    users, user_map, positives_u, positives_i, seen = make_training_arrays(train, item_map)
    model = BPRMF(len(users), len(item_ids), config["bpr"]["embedding_dim"]).to(device)
    optimizer = torch.optim.Adam(model.parameters(), lr=config["bpr"]["learning_rate"], weight_decay=config["bpr"]["weight_decay"])
    rng = __import__("numpy").random.default_rng(config["seed"])
    batch_size = config["bpr"]["batch_size"]
    neg_count = config["bpr"]["negative_samples"]
    best_metric = -1.0
    best_epoch = 0
    best = None
    trace = []
    stale = 0
    started = time.time()
    for epoch in range(1, maximum + 1):
        epoch_users, negative = sample_negatives(positives_u, seen, len(item_ids), neg_count, rng)
        positive = __import__("numpy").repeat(positives_i, neg_count)
        order = rng.permutation(len(epoch_users))
        total = 0.0
        model.train()
        for start in range(0, len(order), batch_size):
            selected = order[start : start + batch_size]
            users_t = torch.from_numpy(epoch_users[selected]).to(device)
            positive_t = torch.from_numpy(positive[selected]).to(device)
            negative_t = torch.from_numpy(negative[selected]).to(device)
            loss = -torch.nn.functional.logsigmoid(model.score(users_t, positive_t) - model.score(users_t, negative_t)).mean()
            optimizer.zero_grad(set_to_none=True)
            loss.backward()
            optimizer.step()
            total += float(loss.item()) * len(selected)
        train_loss = total / len(order)
        ranks, recall = full_catalog_ranks(model, validation_cases, train, user_map, item_map, device, config["bpr"]["validation_user_batch_size"])
        metrics = candidate_metrics(ranks)
        row = {"epoch": epoch, "train_loss": train_loss, **metrics, **recall}
        trace.append(row)
        print(json.dumps(row), flush=True)
        if metrics["ndcg_at_10"] > best_metric + 1e-12:
            best_metric, best_epoch, stale = metrics["ndcg_at_10"], epoch, 0
            save_checkpoint(MODELS / "bpr_validation.pt", model, users, item_ids, epoch, config)
        else:
            stale += 1
        if stale >= patience:
            break
    torch.cuda.empty_cache()
    # Locked final fit: all pre-test interactions, exactly the validation-selected epoch.
    seed_everything(config["seed"])
    pretest = events[events["split"].isin(["train", "validation"])].copy()
    final_model, final_users, _, _, final_losses = train_model(pretest, item_ids, best_epoch, config, device)
    save_checkpoint(MODELS / "bpr_final.pt", final_model, final_users, item_ids, best_epoch, config)
    pd.DataFrame(trace).to_csv(ARTIFACTS / "bpr_training_trace.csv", index=False)
    manifest = {
        "status": "complete",
        "model": "PyTorch BPR-MF",
        "purity": "user_id/item_id/implicit interaction only; no category, image, text, Qwen, or tactile input",
        "device": str(device),
        "selection": "validation NDCG@10, early stopping, ties keep earlier epoch",
        "best_epoch": best_epoch,
        "best_validation_ndcg_at_10": best_metric,
        "validation_training_interactions": len(train),
        "final_training_interactions": len(pretest),
        "validation_checkpoint": str(MODELS / "bpr_validation.pt"),
        "validation_checkpoint_sha256": sha256(MODELS / "bpr_validation.pt"),
        "final_checkpoint": str(MODELS / "bpr_final.pt"),
        "final_checkpoint_sha256": sha256(MODELS / "bpr_final.pt"),
        "elapsed_seconds": time.time() - started,
        "config": config["bpr"],
    }
    atomic_json(ARTIFACTS / "bpr_manifest.json", manifest)
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
