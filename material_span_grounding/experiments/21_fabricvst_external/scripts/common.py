#!/usr/bin/env python3
"""Shared model, data and metric helpers for the FabricVST experiments.

The classifier definition mirrors experiment 12 exactly so that the preserved
``fashionclip_last2.pt`` checkpoint loads without any architectural drift.
"""
from __future__ import annotations

import json
import os
import pickle
from pathlib import Path

# The project's model snapshots live beside the conda prefix, not in the default
# ~/.cache location, and must be set before transformers is imported.
os.environ.setdefault("HF_HOME", "/home/user/onsesang/.cache/huggingface")
os.environ.setdefault("HF_HUB_OFFLINE", "1")

import numpy as np
import torch
from PIL import Image
from torch import nn
from torch.utils.data import Dataset
from transformers import CLIPModel

ROOT = Path(__file__).resolve().parents[1]


def load_config() -> dict:
    return json.loads((ROOT / "config.json").read_text())


def load_checkpoint(path: Path):
    try:
        return torch.load(path, map_location="cpu", weights_only=True)
    except (pickle.UnpicklingError, RuntimeError):
        return torch.load(path, map_location="cpu", weights_only=False)


class TactileClassifier(nn.Module):
    """Identical to experiments/12_class_multilabel_fashionclip_ft."""

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


def build_model_from_checkpoint(checkpoint_path: Path, model_id: str, revision: str, device):
    """Restore a trained classifier; the checkpoint stores trainable tensors only."""
    saved = load_checkpoint(checkpoint_path)
    classes = [str(name) for name in saved["classes"]]
    clip = CLIPModel.from_pretrained(model_id, revision=revision, local_files_only=True)
    model = TactileClassifier(clip, len(classes))
    missing, unexpected = model.load_state_dict(saved["state_dict"], strict=False)
    if unexpected:
        raise RuntimeError(f"unexpected keys in checkpoint: {unexpected[:5]}")
    thresholds = saved["thresholds"]
    if isinstance(thresholds, torch.Tensor):
        thresholds = thresholds.numpy()
    thresholds = np.asarray(thresholds, dtype=np.float32)
    model = model.to(device).eval()
    return model, classes, thresholds, saved


class ImageListDataset(Dataset):
    def __init__(self, paths: list[Path], processor):
        self.paths = paths
        self.processor = processor

    def __len__(self) -> int:
        return len(self.paths)

    def __getitem__(self, index):
        with Image.open(self.paths[index]) as image:
            image = image.convert("RGB")
            pixels = self.processor(images=image, return_tensors="pt").pixel_values[0]
        return pixels, index


@torch.inference_mode()
def predict_probabilities(model, loader, device, n_classes: int) -> np.ndarray:
    chunks = []
    order = []
    for pixels, index in loader:
        with torch.autocast("cuda", dtype=torch.bfloat16):
            logits = model(pixels.to(device, non_blocking=True))
        chunks.append(torch.sigmoid(logits.float()).cpu().numpy())
        order.append(index.numpy())
    probabilities = np.concatenate(chunks)
    indices = np.concatenate(order)
    output = np.zeros((len(indices), n_classes), dtype=np.float32)
    output[indices] = probabilities
    return output


def binary_metrics(truth: np.ndarray, probability: np.ndarray, threshold: float) -> dict:
    # Imported lazily so the vLLM environment, which has no sklearn, can still
    # import this module for the model and data helpers.
    from sklearn.metrics import (
        average_precision_score,
        balanced_accuracy_score,
        f1_score,
        precision_score,
        recall_score,
        roc_auc_score,
    )

    prediction = probability >= threshold
    row = {
        "support": int(truth.size),
        "positive": int(truth.sum()),
        "negative": int(truth.size - truth.sum()),
        "predicted_positive": int(prediction.sum()),
        "accuracy": float((prediction == truth).mean()),
        "precision": float(precision_score(truth, prediction, zero_division=0)),
        "recall": float(recall_score(truth, prediction, zero_division=0)),
        "f1": float(f1_score(truth, prediction, zero_division=0)),
    }
    if len(np.unique(truth)) == 2:
        row["balanced_accuracy"] = float(balanced_accuracy_score(truth, prediction))
        row["auroc"] = float(roc_auc_score(truth, probability))
        row["average_precision"] = float(average_precision_score(truth, probability))
    else:
        row["balanced_accuracy"] = None
        row["auroc"] = None
        row["average_precision"] = None
    return row


def summarise(per_attribute: dict[str, dict]) -> dict:
    from sklearn.metrics import f1_score

    rows = list(per_attribute.values())
    truths, predictions = [], []
    for name, row in per_attribute.items():
        truths.extend(row.pop("_truth"))
        predictions.extend(row.pop("_prediction"))

    def mean_of(key: str):
        values = [row[key] for row in rows if row.get(key) is not None]
        return float(np.mean(values)) if values else None

    return {
        "n_attributes": len(rows),
        "macro_f1": mean_of("f1"),
        "micro_f1": float(f1_score(truths, predictions, zero_division=0)),
        "macro_precision": mean_of("precision"),
        "macro_recall": mean_of("recall"),
        "macro_accuracy": mean_of("accuracy"),
        "macro_balanced_accuracy": mean_of("balanced_accuracy"),
        "macro_auroc": mean_of("auroc"),
        "macro_average_precision": mean_of("average_precision"),
    }


def fabric_split(fabric_ids: list[str], seed: int) -> dict[str, list[str]]:
    """Deterministic fabric-level split replicating the paper's 40/5/5 counts.

    The dataset ships no split file, so this is our own reproducible stand-in
    and is used only for the secondary comparison.
    """
    rng = np.random.default_rng(seed)
    order = list(fabric_ids)
    rng.shuffle(order)
    return {"train": order[:40], "validation": order[40:45], "test": order[45:50]}
