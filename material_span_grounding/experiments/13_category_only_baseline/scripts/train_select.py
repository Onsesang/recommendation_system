#!/usr/bin/env python3
from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import torch
from torch import nn
from torch.utils.data import DataLoader, TensorDataset

from common import (
    CONFIG_PATH,
    ROOT,
    CategoryClassifier,
    atomic_json,
    calculate_metrics,
    choose_thresholds,
    load_config,
    masked_bce,
    read_json,
    seed_everything,
    sha256,
    source_hashes,
)


def predict(model: nn.Module, loader: DataLoader, device: torch.device):
    model.eval()
    logits: list[np.ndarray] = []
    values: list[np.ndarray] = []
    masks: list[np.ndarray] = []
    with torch.inference_mode():
        for category_ids, target, mask in loader:
            logits.append(model(category_ids.to(device)).cpu().numpy())
            values.append(target.numpy())
            masks.append(mask.numpy())
    return np.concatenate(logits), np.concatenate(values), np.concatenate(masks).astype(bool)


def main() -> int:
    config = load_config()
    training = config["training"]
    threshold_config = config["threshold_search"]
    seed_everything(int(training["seed"]))
    artifacts = ROOT / "artifacts"
    prepared_path = artifacts / "train_development_only.npz"
    preparation = read_json(artifacts / "preparation_manifest.json")
    assert preparation["dataset_sha256"] == sha256(prepared_path)
    assert preparation["config_sha256"] == sha256(CONFIG_PATH)
    assert preparation["source_hashes"] == source_hashes(config)
    assert preparation["locked_test_labels_in_prepared_artifact"] is False

    with np.load(prepared_path, allow_pickle=False) as data:
        category_ids = data["category_ids"].astype(np.int64)
        values = data["values"].astype(np.float32)
        masks = data["mask"].astype(np.float32)
        split_codes = data["split_codes"].astype(np.uint8)
        classes = data["classes"].astype(str).tolist()
    assert set(np.unique(split_codes).tolist()) == {0, 1}, "prepared data may only contain train/dev"
    train_indices = np.flatnonzero(split_codes == 0)
    development_indices = np.flatnonzero(split_codes == 1)
    assert len(train_indices) == config["data"]["expected_split_counts"]["train"]
    assert len(development_indices) == config["data"]["expected_split_counts"]["development"]

    def make_loader(indices: np.ndarray, shuffle: bool) -> DataLoader:
        dataset = TensorDataset(
            torch.from_numpy(category_ids[indices]),
            torch.from_numpy(values[indices]),
            torch.from_numpy(masks[indices]),
        )
        generator = torch.Generator().manual_seed(int(training["seed"]))
        return DataLoader(
            dataset,
            batch_size=int(training["batch_size"]),
            shuffle=shuffle,
            generator=generator,
            num_workers=0,
        )

    train_loader = make_loader(train_indices, True)
    development_loader = make_loader(development_indices, False)
    device = torch.device(training["device"])
    model = CategoryClassifier(
        preparation["category_vocabulary_size_including_unk"],
        int(config["model"]["embedding_dimension"]),
        len(classes),
    ).to(device)
    optimizer = torch.optim.AdamW(
        model.parameters(),
        lr=float(training["learning_rate"]),
        weight_decay=float(training["weight_decay"]),
    )
    train_values = values[train_indices]
    train_masks = masks[train_indices]
    positive = ((train_values >= 0.5) * train_masks).sum(axis=0)
    negative = ((train_values < 0.5) * train_masks).sum(axis=0)
    clip_min, clip_max = training["positive_weight_clip"]
    positive_weight_numpy = np.clip(
        negative / np.clip(positive, 1, None), clip_min, clip_max
    ).astype(np.float32)
    positive_weight = torch.from_numpy(positive_weight_numpy).to(device)

    model_dir = ROOT / "models"
    model_dir.mkdir(parents=True, exist_ok=True)
    checkpoint_path = model_dir / "category_only_best.pt"
    best_score = -math.inf
    best_epoch = 0
    stale = 0
    history: list[dict] = []
    for epoch in range(1, int(training["maximum_epochs"]) + 1):
        model.train()
        loss_numerator = 0.0
        observed_total = 0.0
        for batch_category_ids, target, mask in train_loader:
            batch_category_ids = batch_category_ids.to(device)
            target = target.to(device)
            mask = mask.to(device)
            optimizer.zero_grad(set_to_none=True)
            logits = model(batch_category_ids)
            loss = masked_bce(logits, target, mask, positive_weight)
            loss.backward()
            optimizer.step()
            observed = float(mask.sum().item())
            loss_numerator += float(loss.item()) * observed
            observed_total += observed
        development_logits, development_values, development_masks = predict(
            model, development_loader, device
        )
        thresholds = choose_thresholds(
            development_logits,
            development_values,
            development_masks,
            float(threshold_config["minimum"]),
            float(threshold_config["maximum"]),
            float(threshold_config["step"]),
        )
        development_metrics = calculate_metrics(
            development_logits, development_values, development_masks, thresholds, classes
        )
        epoch_row = {
            "epoch": epoch,
            "train_masked_bce": loss_numerator / max(observed_total, 1.0),
            "development_macro_f1": development_metrics["macro_f1"],
        }
        history.append(epoch_row)
        print(
            f"epoch={epoch:02d} train_masked_bce={epoch_row['train_masked_bce']:.6f} "
            f"development_macro_f1={epoch_row['development_macro_f1']:.6f}",
            flush=True,
        )
        if development_metrics["macro_f1"] > best_score + 1e-6:
            best_score = development_metrics["macro_f1"]
            best_epoch = epoch
            stale = 0
            torch.save(
                {
                    "state_dict": model.state_dict(),
                    "thresholds": torch.from_numpy(thresholds),
                    "classes": classes,
                    "category_vocabulary": preparation["category_vocabulary"],
                    "best_epoch": best_epoch,
                    "development_metrics": development_metrics,
                    "config_sha256": sha256(CONFIG_PATH),
                    "prepared_dataset_sha256": sha256(prepared_path),
                },
                checkpoint_path,
            )
        else:
            stale += 1
            if stale >= int(training["early_stopping_patience"]):
                break

    saved = torch.load(checkpoint_path, map_location="cpu", weights_only=True)
    selection = {
        "status": "development_selection_complete_and_frozen",
        "locked_test_evaluated": False,
        "selection_split": "development",
        "best_epoch": int(saved["best_epoch"]),
        "selected_thresholds": {
            name: float(value) for name, value in zip(classes, saved["thresholds"].tolist())
        },
        "development_metrics": saved["development_metrics"],
        "train_only_positive_weight": {
            name: float(value) for name, value in zip(classes, positive_weight_numpy.tolist())
        },
        "history": history,
        "checkpoint": str(checkpoint_path),
        "checkpoint_sha256": sha256(checkpoint_path),
        "prepared_dataset_sha256": sha256(prepared_path),
        "config_sha256": sha256(CONFIG_PATH),
        "source_hashes": source_hashes(config),
        "selection_constraints": {
            "training_splits": ["train"],
            "early_stopping_splits": ["development"],
            "threshold_selection_splits": ["development"],
            "locked_test_used": False,
        },
    }
    atomic_json(artifacts / "development_selection.json", selection)
    print(f"selection frozen: epoch={best_epoch} dev_macro_f1={best_score:.6f}")
    print(f"checkpoint_sha256={selection['checkpoint_sha256']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
