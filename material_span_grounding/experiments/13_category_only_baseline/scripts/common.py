from __future__ import annotations

import hashlib
import json
import math
import os
import random
import tempfile
from pathlib import Path
from typing import Any

import numpy as np
import torch
from sklearn.metrics import (
    average_precision_score,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from torch import nn


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config.json"


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, indent=2, ensure_ascii=False, allow_nan=False)
            handle.write("\n")
        os.replace(temporary_name, path)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_config() -> dict[str, Any]:
    config = read_json(CONFIG_PATH)
    return config


def seed_everything(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.use_deterministic_algorithms(True)


class CategoryClassifier(nn.Module):
    """The only predictive input is a train-vocabulary category ID."""

    def __init__(self, vocabulary_size: int, embedding_dimension: int, classes: int):
        super().__init__()
        self.category_embedding = nn.Embedding(vocabulary_size, embedding_dimension)
        self.classifier = nn.Linear(embedding_dimension, classes)

    def forward(self, category_ids: torch.Tensor) -> torch.Tensor:
        return self.classifier(self.category_embedding(category_ids))


def masked_bce(
    logits: torch.Tensor,
    values: torch.Tensor,
    masks: torch.Tensor,
    positive_weight: torch.Tensor,
) -> torch.Tensor:
    elementwise = nn.functional.binary_cross_entropy_with_logits(
        logits, values, reduction="none", pos_weight=positive_weight
    )
    return (elementwise * masks).sum() / masks.sum().clamp_min(1.0)


def sigmoid(logits: np.ndarray) -> np.ndarray:
    clipped = np.clip(logits, -80.0, 80.0)
    return 1.0 / (1.0 + np.exp(-clipped))


def choose_thresholds(
    logits: np.ndarray,
    values: np.ndarray,
    masks: np.ndarray,
    minimum: float,
    maximum: float,
    step: float,
) -> np.ndarray:
    probabilities = sigmoid(logits)
    candidates = np.round(np.arange(minimum, maximum + step / 2.0, step), 10)
    thresholds: list[float] = []
    for class_number in range(values.shape[1]):
        observed = masks[:, class_number].astype(bool)
        if not observed.any():
            thresholds.append(0.5)
            continue
        truth = values[observed, class_number] >= 0.5
        best_score = -math.inf
        best_threshold = 0.5
        for threshold in candidates:
            score = f1_score(
                truth,
                probabilities[observed, class_number] >= threshold,
                zero_division=0,
            )
            if score > best_score:
                best_score = float(score)
                best_threshold = float(threshold)
        thresholds.append(best_threshold)
    return np.asarray(thresholds, dtype=np.float32)


def safe_binary_metric(function, truth: np.ndarray, score: np.ndarray) -> float | None:
    if len(np.unique(truth)) != 2:
        return None
    return float(function(truth, score))


def calculate_metrics(
    logits: np.ndarray,
    values: np.ndarray,
    masks: np.ndarray,
    thresholds: np.ndarray,
    classes: list[str],
) -> dict[str, Any]:
    probabilities = sigmoid(logits)
    all_truth: list[bool] = []
    all_predictions: list[bool] = []
    all_probabilities: list[float] = []
    per_class: dict[str, Any] = {}
    skipped_auroc: list[str] = []
    for class_number, name in enumerate(classes):
        observed = masks[:, class_number].astype(bool)
        truth = values[observed, class_number] >= 0.5
        score = probabilities[observed, class_number]
        prediction = score >= thresholds[class_number]
        average_precision = safe_binary_metric(average_precision_score, truth, score)
        auroc = safe_binary_metric(roc_auc_score, truth, score)
        if auroc is None:
            skipped_auroc.append(name)
        positive = int(truth.sum())
        per_class[name] = {
            "observed": int(observed.sum()),
            "positive": positive,
            "negative": int(observed.sum()) - positive,
            "precision": float(precision_score(truth, prediction, zero_division=0)),
            "recall": float(recall_score(truth, prediction, zero_division=0)),
            "f1": float(f1_score(truth, prediction, zero_division=0)),
            "average_precision": average_precision,
            "auroc": auroc,
            "threshold": float(thresholds[class_number]),
        }
        all_truth.extend(truth.tolist())
        all_predictions.extend(prediction.tolist())
        all_probabilities.extend(score.tolist())
    average_precisions = [
        row["average_precision"]
        for row in per_class.values()
        if row["average_precision"] is not None
    ]
    aurocs = [row["auroc"] for row in per_class.values() if row["auroc"] is not None]
    flat_truth = np.asarray(all_truth, dtype=bool)
    flat_probabilities = np.asarray(all_probabilities, dtype=np.float64)
    return {
        "macro_f1": float(np.mean([row["f1"] for row in per_class.values()])),
        "micro_f1": float(f1_score(all_truth, all_predictions, zero_division=0)),
        "macro_average_precision": float(np.mean(average_precisions)) if average_precisions else None,
        "micro_average_precision": safe_binary_metric(
            average_precision_score, flat_truth, flat_probabilities
        ),
        "macro_auroc": float(np.mean(aurocs)) if aurocs else None,
        "micro_auroc": safe_binary_metric(roc_auc_score, flat_truth, flat_probabilities),
        "auroc_skipped_classes": skipped_auroc,
        "observed_pairs": int(masks.astype(bool).sum()),
        "per_class": per_class,
    }


def pairwise_overlap(sets: dict[str, set[str]]) -> dict[str, int]:
    names = ["train", "development", "test"]
    return {
        f"{names[left]}__{names[right]}": len(sets[names[left]] & sets[names[right]])
        for left in range(len(names))
        for right in range(left + 1, len(names))
    }


def source_hashes(config: dict[str, Any]) -> dict[str, str]:
    return {
        name: sha256(Path(config["paths"][name]))
        for name in ("product_metadata", "split_manifest", "v3_targets", "v3_fashionclip_results")
    }
