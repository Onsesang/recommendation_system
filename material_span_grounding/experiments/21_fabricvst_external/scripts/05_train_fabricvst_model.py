#!/usr/bin/env python3
"""PART C - train the FabricVST-taxonomy multi-label image predictor.

Same encoder, regime and optimiser settings as experiment 12; the change under
test is the label space, not the architecture. ``unknown`` entries are masked
out of the loss and out of every metric. FabricVST is never touched here.
"""
from __future__ import annotations

import argparse
import json
import math
import random
import sys
from pathlib import Path

import numpy as np
import torch
from torch import nn
from torch.utils.data import DataLoader, Dataset
from transformers import AutoProcessor, CLIPModel

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import ROOT, TactileClassifier, load_config  # noqa: E402

RESULTS = ROOT / "results" / "fabricvst_taxonomy_retraining"
CHECKPOINTS = ROOT / "checkpoints" / "fabricvst_taxonomy"


class ProductDataset(Dataset):
    def __init__(self, ids, values, masks, image_root: Path, processor, training: bool):
        self.ids, self.values, self.masks = ids, values, masks
        self.image_root, self.processor, self.training = image_root, processor, training

    def __len__(self):
        return len(self.ids)

    def __getitem__(self, index):
        from PIL import Image

        with Image.open(self.image_root / f"{self.ids[index]}.jpg") as image:
            image = image.convert("RGB")
            if self.training and random.random() < 0.5:
                image = image.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
            pixels = self.processor(images=image, return_tensors="pt").pixel_values[0]
        return pixels, torch.from_numpy(self.values[index]), torch.from_numpy(self.masks[index])


def configure(model: TactileClassifier, regime: str):
    for parameter in model.parameters():
        parameter.requires_grad = False
    for parameter in model.head.parameters():
        parameter.requires_grad = True
    groups = [{"params": list(model.head.parameters()), "lr_key": "head_lr"}]
    if regime in {"projection", "last1", "last2", "full"}:
        for parameter in model.projection.parameters():
            parameter.requires_grad = True
        groups.append({"params": list(model.projection.parameters()), "lr_key": "projection_lr"})
    if regime == "full":
        for parameter in model.vision.parameters():
            parameter.requires_grad = True
        groups.append({"params": list(model.vision.parameters()), "lr_key": "encoder_lr"})
    elif regime.startswith("last"):
        count = int(regime.removeprefix("last"))
        parameters = []
        for layer in model.vision.encoder.layers[-count:]:
            for parameter in layer.parameters():
                parameter.requires_grad = True
                parameters.append(parameter)
        for parameter in model.vision.post_layernorm.parameters():
            parameter.requires_grad = True
            parameters.append(parameter)
        groups.append({"params": parameters, "lr_key": "encoder_lr"})
    return groups


@torch.inference_mode()
def predict(model, loader, device):
    model.eval()
    logits, values, masks = [], [], []
    for pixels, target, mask in loader:
        with torch.autocast("cuda", dtype=torch.bfloat16):
            output = model(pixels.to(device, non_blocking=True))
        logits.append(output.float().cpu().numpy())
        values.append(target.numpy())
        masks.append(mask.numpy())
    return np.concatenate(logits), np.concatenate(values), np.concatenate(masks).astype(bool)


def choose_thresholds(logits, values, masks):
    from sklearn.metrics import f1_score

    probabilities = 1 / (1 + np.exp(-logits))
    thresholds = []
    for number in range(values.shape[1]):
        observed = masks[:, number]
        if observed.sum() == 0 or len(np.unique(values[observed, number] >= 0.5)) < 2:
            thresholds.append(0.5)
            continue
        truth = values[observed, number] >= 0.5
        best = (float("-inf"), 0.5)
        for threshold in np.linspace(0.1, 0.9, 17):
            score = f1_score(truth, probabilities[observed, number] >= threshold, zero_division=0)
            if score > best[0]:
                best = (score, float(threshold))
        thresholds.append(best[1])
    return np.asarray(thresholds, dtype=np.float32)


def metrics(logits, values, masks, thresholds, attributes):
    from sklearn.metrics import (
        average_precision_score,
        f1_score,
        precision_score,
        recall_score,
        roc_auc_score,
    )

    probabilities = 1 / (1 + np.exp(-logits))
    per_attribute = {}
    truths, predictions = [], []
    for number, name in enumerate(attributes):
        observed = masks[:, number]
        if observed.sum() == 0:
            continue
        truth = values[observed, number] >= 0.5
        probability = probabilities[observed, number]
        prediction = probability >= thresholds[number]
        row = {
            "support": int(observed.sum()),
            "positive": int(truth.sum()),
            "precision": float(precision_score(truth, prediction, zero_division=0)),
            "recall": float(recall_score(truth, prediction, zero_division=0)),
            "f1": float(f1_score(truth, prediction, zero_division=0)),
        }
        if len(np.unique(truth)) == 2:
            row["auroc"] = float(roc_auc_score(truth, probability))
            row["average_precision"] = float(average_precision_score(truth, probability))
        per_attribute[name] = row
        truths.extend(truth.tolist())
        predictions.extend(prediction.tolist())

    def mean_of(key):
        values_ = [row[key] for row in per_attribute.values() if key in row]
        return float(np.mean(values_)) if values_ else None

    return {
        "macro_f1": mean_of("f1"),
        "micro_f1": float(f1_score(truths, predictions, zero_division=0)) if truths else None,
        "macro_precision": mean_of("precision"),
        "macro_recall": mean_of("recall"),
        "macro_auroc": mean_of("auroc"),
        "mean_average_precision": mean_of("average_precision"),
        "per_attribute": per_attribute,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--group", choices=["A_fabricvst_24", "B_tactile_subset"], default="B_tactile_subset")
    args = parser.parse_args()

    config = load_config()
    cfg = config["fashionclip"]
    seed = int(config["seed"])
    torch.manual_seed(seed)
    np.random.seed(seed)
    random.seed(seed)

    RESULTS.mkdir(parents=True, exist_ok=True)
    CHECKPOINTS.mkdir(parents=True, exist_ok=True)

    data = np.load(ROOT / "artifacts" / "product_fabricvst_targets.npz", allow_pickle=False)
    product_ids = data["product_ids"].astype(str)
    all_attributes = data["attributes"].astype(str).tolist()
    values_all = data["values"].astype(np.float32)
    mask_all = data["mask"].astype(np.float32)

    selected = config["retraining"]["attribute_groups"][args.group]
    columns = [all_attributes.index(name) for name in selected]
    values = np.ascontiguousarray(values_all[:, columns])
    masks = np.ascontiguousarray(mask_all[:, columns])

    split = json.loads(Path(config["retraining"]["split_manifest"]).read_text())["splits"]
    image_root = Path(config["retraining"]["image_root"])
    index = {value: number for number, value in enumerate(product_ids)}
    split_indices = {}
    for name, members in split.items():
        keep = [index[v] for v in members if v in index and (image_root / f"{v}.jpg").is_file()]
        split_indices[name] = np.asarray(keep, dtype=int)
    (ROOT / "splits" / f"fabricvst_taxonomy_{args.group}.json").write_text(
        json.dumps(
            {
                "seed": seed,
                "group": args.group,
                "attributes": selected,
                "source_split_manifest": config["retraining"]["split_manifest"],
                "counts": {name: int(len(v)) for name, v in split_indices.items()},
                **{name: [product_ids[i] for i in v] for name, v in split_indices.items()},
            },
            indent=2,
        )
        + "\n"
    )
    print({name: len(v) for name, v in split_indices.items()}, flush=True)

    processor = AutoProcessor.from_pretrained(cfg["model_id"], revision=cfg["revision"], local_files_only=True)
    device = torch.device("cuda")
    clip = CLIPModel.from_pretrained(cfg["model_id"], revision=cfg["revision"], local_files_only=True)
    model = TactileClassifier(clip, len(selected)).to(device)
    groups = configure(model, cfg["regime"])
    optimizer = torch.optim.AdamW(
        [{"params": group["params"], "lr": float(cfg[group["lr_key"]])} for group in groups],
        weight_decay=float(cfg["weight_decay"]),
    )

    loaders = {}
    for name, chosen in split_indices.items():
        dataset = ProductDataset(
            product_ids[chosen], values[chosen], masks[chosen], image_root, processor, name == "train"
        )
        loaders[name] = DataLoader(
            dataset, batch_size=int(cfg["batch_size"]), shuffle=name == "train",
            num_workers=8, pin_memory=True, persistent_workers=True,
        )

    train_selected = split_indices["train"]
    positive = ((values[train_selected] >= 0.5) * masks[train_selected]).sum(axis=0)
    negative = ((values[train_selected] < 0.5) * masks[train_selected]).sum(axis=0)
    pos_weight = torch.from_numpy(
        np.clip(negative / np.clip(positive, 1, None), 0.25, 4.0).astype(np.float32)
    ).to(device)

    best_score, best_epoch, stale = -math.inf, 0, 0
    checkpoint = CHECKPOINTS / "best.pt"
    history = []
    for epoch in range(1, int(cfg["epochs"]) + 1):
        model.train()
        total_loss = total_weight = 0.0
        for pixels, target, mask in loaders["train"]:
            pixels, target, mask = pixels.to(device, non_blocking=True), target.to(device), mask.to(device)
            optimizer.zero_grad(set_to_none=True)
            with torch.autocast("cuda", dtype=torch.bfloat16):
                logits = model(pixels)
                element = nn.functional.binary_cross_entropy_with_logits(
                    logits, target, reduction="none", pos_weight=pos_weight
                )
                loss = (element * mask).sum() / mask.sum().clamp_min(1.0)
            loss.backward()
            nn.utils.clip_grad_norm_([p for p in model.parameters() if p.requires_grad], 1.0)
            optimizer.step()
            total_loss += float(loss.item()) * float(mask.sum())
            total_weight += float(mask.sum())

        dev_logits, dev_values, dev_masks = predict(model, loaders["development"], device)
        thresholds = choose_thresholds(dev_logits, dev_values, dev_masks)
        dev_metrics = metrics(dev_logits, dev_values, dev_masks, thresholds, selected)
        history.append({
            "epoch": epoch,
            "train_loss": total_loss / max(total_weight, 1),
            "development_macro_f1": dev_metrics["macro_f1"],
            "development_macro_auroc": dev_metrics["macro_auroc"],
        })
        print(
            f"epoch={epoch} loss={history[-1]['train_loss']:.5f} "
            f"dev_macro_f1={dev_metrics['macro_f1']:.5f}",
            flush=True,
        )
        if dev_metrics["macro_f1"] > best_score + 1e-6:
            best_score, best_epoch, stale = dev_metrics["macro_f1"], epoch, 0
            named = dict(model.named_parameters())
            trainable = {
                name: value.detach().cpu()
                for name, value in model.state_dict().items()
                if name in named and named[name].requires_grad
            }
            torch.save(
                {
                    "regime": cfg["regime"],
                    "group": args.group,
                    "state_dict": trainable,
                    "thresholds": torch.from_numpy(thresholds),
                    "classes": selected,
                    "best_epoch": epoch,
                },
                checkpoint,
            )
        else:
            stale += 1
            if stale >= int(cfg["patience"]):
                break

    torch.save(
        {
            "regime": cfg["regime"], "group": args.group,
            "state_dict": {
                name: value.detach().cpu()
                for name, value in model.state_dict().items()
                if name in dict(model.named_parameters()) and dict(model.named_parameters())[name].requires_grad
            },
            "thresholds": torch.from_numpy(thresholds),
            "classes": selected, "best_epoch": best_epoch,
        },
        CHECKPOINTS / "last.pt",
    )

    saved = torch.load(checkpoint, map_location="cpu", weights_only=True)
    model.load_state_dict(saved["state_dict"], strict=False)
    best_thresholds = saved["thresholds"].numpy()
    dev_logits, dev_values, dev_masks = predict(model, loaders["development"], device)
    test_logits, test_values, test_masks = predict(model, loaders["test"], device)
    report = {
        "group": args.group,
        "attributes": selected,
        "regime": cfg["regime"],
        "best_epoch": int(saved["best_epoch"]),
        "seed": seed,
        "split_counts": {name: int(len(v)) for name, v in split_indices.items()},
        "thresholds": best_thresholds.tolist(),
        "development": metrics(dev_logits, dev_values, dev_masks, best_thresholds, selected),
        "test": metrics(test_logits, test_values, test_masks, best_thresholds, selected),
        "history": history,
    }
    (RESULTS / f"internal_test_metrics_{args.group}.json").write_text(json.dumps(report, indent=2) + "\n")

    import csv

    with (RESULTS / f"training_history_{args.group}.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(history[0].keys()))
        writer.writeheader()
        writer.writerows(history)
    rows = [{"attribute": name, **row} for name, row in report["test"]["per_attribute"].items()]
    with (RESULTS / f"per_attribute_metrics_{args.group}.csv").open("w", newline="", encoding="utf-8") as handle:
        fields: list[str] = []
        for row in rows:
            for key in row:
                if key not in fields:
                    fields.append(key)
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    print(json.dumps({k: v for k, v in report.items() if k not in {"history", "development", "test"}}, indent=2))
    print(f"internal test macro_f1={report['test']['macro_f1']:.4f} macro_auroc={report['test']['macro_auroc']}")
    (ROOT / "manifests" / f"05_train_{args.group}.json").write_text(
        json.dumps({"status": "complete", "checkpoint": str(checkpoint)}, indent=2) + "\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
