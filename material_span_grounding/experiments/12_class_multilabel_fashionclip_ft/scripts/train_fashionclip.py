#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import pickle
import random
from pathlib import Path
from typing import Any

import numpy as np
import torch
from PIL import Image
from sklearn.metrics import average_precision_score, f1_score, precision_score, recall_score, roc_auc_score
from torch import nn
from torch.utils.data import DataLoader, Dataset
from transformers import AutoProcessor, CLIPModel

ROOT = Path(__file__).resolve().parents[1]


def load_checkpoint(path: Path):
    """Load only checkpoints produced locally by this experiment.

    New checkpoints contain tensors and primitives only.  The compatibility
    fallback is needed for the first frozen checkpoint, which was written with
    a NumPy thresholds array before the format was tightened.
    """
    try:
        return torch.load(path, map_location="cpu", weights_only=True)
    except (pickle.UnpicklingError, RuntimeError):
        return torch.load(path, map_location="cpu", weights_only=False)


class ProductDataset(Dataset):
    def __init__(self, ids, values, masks, image_root: Path, processor, training: bool):
        self.ids, self.values, self.masks = ids, values, masks
        self.image_root, self.processor, self.training = image_root, processor, training

    def __len__(self):
        return len(self.ids)

    def __getitem__(self, index):
        with Image.open(self.image_root / f"{self.ids[index]}.jpg") as image:
            image = image.convert("RGB")
            if self.training and random.random() < 0.5:
                image = image.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
            pixels = self.processor(images=image, return_tensors="pt").pixel_values[0]
        return pixels, torch.from_numpy(self.values[index]), torch.from_numpy(self.masks[index])


class TactileClassifier(nn.Module):
    def __init__(self, clip: CLIPModel, classes: int):
        super().__init__()
        self.vision = clip.vision_model
        self.projection = clip.visual_projection
        self.head = nn.Linear(self.projection.out_features, classes)

    def forward(self, pixels):
        output = self.vision(pixel_values=pixels)
        features = self.projection(output.pooler_output)
        features = nn.functional.normalize(features, dim=-1)
        return self.head(features)


def configure(model: TactileClassifier, regime: str) -> list[dict[str, Any]]:
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
        # This pinned Transformers commit exposes CLIPVisionModel's encoder
        # directly (older releases nested it under another ``vision_model``).
        layers = model.vision.encoder.layers
        parameters = []
        for layer in layers[-count:]:
            for parameter in layer.parameters():
                parameter.requires_grad = True
                parameters.append(parameter)
        for parameter in model.vision.post_layernorm.parameters():
            parameter.requires_grad = True
            parameters.append(parameter)
        groups.append({"params": parameters, "lr_key": "encoder_lr"})
    return groups


def predict(model, loader, device):
    model.eval(); logits, values, masks = [], [], []
    with torch.inference_mode():
        for pixels, target, mask in loader:
            with torch.autocast("cuda", dtype=torch.bfloat16):
                output = model(pixels.to(device, non_blocking=True))
            logits.append(output.float().cpu().numpy())
            values.append(target.numpy()); masks.append(mask.numpy())
    return np.concatenate(logits), np.concatenate(values), np.concatenate(masks).astype(bool)


def choose_thresholds(logits, values, masks):
    probabilities = 1 / (1 + np.exp(-logits))
    thresholds = []
    for number in range(values.shape[1]):
        observed = masks[:, number]
        truth = values[observed, number] >= 0.5
        best = (float("-inf"), 0.5)
        for threshold in np.linspace(0.1, 0.9, 17):
            score = f1_score(truth, probabilities[observed, number] >= threshold, zero_division=0)
            if score > best[0]: best = (score, float(threshold))
        thresholds.append(best[1])
    return np.asarray(thresholds)


def metrics(logits, values, masks, thresholds, classes):
    probabilities = 1 / (1 + np.exp(-logits)); per_class = {}; truths = []; predictions = []
    for number, name in enumerate(classes):
        observed = masks[:, number]; truth = values[observed, number] >= 0.5
        prediction = probabilities[observed, number] >= thresholds[number]
        row = {
            "observed": int(observed.sum()), "positive": int(truth.sum()),
            "precision": float(precision_score(truth, prediction, zero_division=0)),
            "recall": float(recall_score(truth, prediction, zero_division=0)),
            "f1": float(f1_score(truth, prediction, zero_division=0)),
        }
        if len(np.unique(truth)) == 2:
            row["average_precision"] = float(average_precision_score(truth, probabilities[observed, number]))
            row["auroc"] = float(roc_auc_score(truth, probabilities[observed, number]))
        per_class[name] = row; truths.extend(truth.tolist()); predictions.extend(prediction.tolist())
    f1s = [row["f1"] for row in per_class.values()]
    aps = [row["average_precision"] for row in per_class.values() if "average_precision" in row]
    return {
        "macro_f1": float(np.mean(f1s)),
        "micro_f1": float(f1_score(truths, predictions, zero_division=0)),
        "macro_average_precision": float(np.mean(aps)) if aps else None,
        "per_class": per_class,
    }


def main() -> int:
    parser = argparse.ArgumentParser(); parser.add_argument("--regime", choices=["frozen", "projection", "last1", "last2", "full"])
    args = parser.parse_args()
    config = json.loads((ROOT / "config.json").read_text()); cfg = config["fashionclip"]
    torch.manual_seed(config["seed"]); np.random.seed(config["seed"]); random.seed(config["seed"])
    with np.load(ROOT / "artifacts" / "product_class_targets.npz", allow_pickle=False) as data:
        ids = data["product_ids"].astype(str); classes = data["classes"].astype(str).tolist()
        values = data["values"].astype(np.float32); masks = data["mask"].astype(np.float32)
    split = json.loads(Path(config["split_manifest"]).read_text())["splits"]
    index = {value: number for number, value in enumerate(ids)}
    split_indices = {name: np.asarray([index[value] for value in members], dtype=int) for name, members in split.items()}
    processor = AutoProcessor.from_pretrained(cfg["model_id"], revision=cfg["revision"], local_files_only=True)
    device = torch.device("cuda")
    regimes = [args.regime] if args.regime else cfg["regimes"]
    results_path = ROOT / "artifacts" / "fashionclip_results.json"
    if results_path.is_file():
        results = json.loads(results_path.read_text())
    else:
        results = {}
    models_dir = ROOT / "models"; models_dir.mkdir(exist_ok=True)
    for regime in regimes:
        if regime in results and (models_dir / f"fashionclip_{regime}.pt").is_file():
            print(f"regime={regime} complete checkpoint found; skipping", flush=True)
            continue
        clip = CLIPModel.from_pretrained(cfg["model_id"], revision=cfg["revision"], local_files_only=True)
        model = TactileClassifier(clip, len(classes)).to(device)
        groups = configure(model, regime)
        optimizer = torch.optim.AdamW(
            [{"params": group["params"], "lr": float(cfg[group["lr_key"]])} for group in groups],
            weight_decay=float(cfg["weight_decay"]),
        )
        loaders = {}
        for name, selected in split_indices.items():
            dataset = ProductDataset(ids[selected], values[selected], masks[selected], Path(config["image_root"]), processor, name == "train")
            loaders[name] = DataLoader(dataset, batch_size=int(cfg["batch_size"]), shuffle=name == "train", num_workers=8, pin_memory=True, persistent_workers=True)
        train_selected = split_indices["train"]
        positive = ((values[train_selected] >= 0.5) * masks[train_selected]).sum(axis=0)
        negative = ((values[train_selected] < 0.5) * masks[train_selected]).sum(axis=0)
        pos_weight = torch.from_numpy(np.clip(negative / np.clip(positive, 1, None), 0.25, 4.0).astype(np.float32)).to(device)
        best_score, best_epoch, stale = -math.inf, 0, 0
        checkpoint = models_dir / f"fashionclip_{regime}.pt"
        history = []
        for epoch in range(1, int(cfg["epochs"]) + 1):
            model.train(); total_loss = total_weight = 0.0
            for pixels, target, mask in loaders["train"]:
                pixels, target, mask = pixels.to(device, non_blocking=True), target.to(device), mask.to(device)
                optimizer.zero_grad(set_to_none=True)
                with torch.autocast("cuda", dtype=torch.bfloat16):
                    logits = model(pixels)
                    element = nn.functional.binary_cross_entropy_with_logits(logits, target, reduction="none", pos_weight=pos_weight)
                    loss = (element * mask).sum() / mask.sum().clamp_min(1.0)
                loss.backward(); nn.utils.clip_grad_norm_([p for p in model.parameters() if p.requires_grad], 1.0); optimizer.step()
                total_loss += float(loss.item()) * float(mask.sum()); total_weight += float(mask.sum())
            dev_logits, dev_values, dev_masks = predict(model, loaders["development"], device)
            thresholds = choose_thresholds(dev_logits, dev_values, dev_masks)
            dev_metrics = metrics(dev_logits, dev_values, dev_masks, thresholds, classes)
            history.append({"epoch": epoch, "train_loss": total_loss / max(total_weight, 1), "development": dev_metrics})
            print(f"regime={regime} epoch={epoch} loss={history[-1]['train_loss']:.5f} dev_macro_f1={dev_metrics['macro_f1']:.5f}", flush=True)
            if dev_metrics["macro_f1"] > best_score + 1e-6:
                best_score, best_epoch, stale = dev_metrics["macro_f1"], epoch, 0
                trainable = {name: value.detach().cpu() for name, value in model.state_dict().items() if dict(model.named_parameters()).get(name, None) is not None and dict(model.named_parameters())[name].requires_grad}
                torch.save({
                    "regime": regime,
                    "state_dict": trainable,
                    "thresholds": torch.from_numpy(thresholds.astype(np.float32)),
                    "classes": classes,
                    "best_epoch": epoch,
                }, checkpoint)
            else:
                stale += 1
                if stale >= int(cfg["patience"]): break
        saved = load_checkpoint(checkpoint)
        model.load_state_dict(saved["state_dict"], strict=False)
        saved_thresholds = saved["thresholds"]
        if isinstance(saved_thresholds, torch.Tensor):
            saved_thresholds = saved_thresholds.numpy()
        else:
            saved_thresholds = np.asarray(saved_thresholds, dtype=np.float32)
        dev_logits, dev_values, dev_masks = predict(model, loaders["development"], device)
        test_logits, test_values, test_masks = predict(model, loaders["test"], device)
        results[regime] = {
            "best_epoch": int(saved.get("best_epoch", best_epoch)), "thresholds": saved_thresholds.tolist(),
            "development": metrics(dev_logits, dev_values, dev_masks, saved_thresholds, classes),
            "test": metrics(test_logits, test_values, test_masks, saved_thresholds, classes),
            "history": history,
        }
        results_path.write_text(json.dumps(results, indent=2) + "\n")
        del model, clip, optimizer; torch.cuda.empty_cache()
    selected = max(results, key=lambda name: results[name]["development"]["macro_f1"])
    manifest = {"status": "complete", "selected_by_development": selected, "results": str(ROOT / "artifacts" / "fashionclip_results.json")}
    (ROOT / "manifests" / "train_fashionclip.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(manifest, indent=2)); return 0


if __name__ == "__main__": raise SystemExit(main())
