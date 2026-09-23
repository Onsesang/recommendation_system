from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

import numpy as np


ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "configs" / "recommendation_config.json"
ARTIFACTS = ROOT / "artifacts"
MODELS = ROOT / "models"


def read_json(path: Path | str) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def atomic_json(path: Path | str, value: Any) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.write("\n")
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def sha256(path: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def stable_hash(text: str, seed: int) -> str:
    return hashlib.sha256(f"{seed}|{text}".encode()).hexdigest()


def percentile_rank(values: np.ndarray) -> np.ndarray:
    """Average-tie percentile ranks in [0, 1], deterministic and scale-free."""
    values = np.asarray(values, dtype=np.float64)
    if len(values) <= 1:
        return np.ones_like(values, dtype=np.float64)
    order = np.argsort(values, kind="mergesort")
    sorted_values = values[order]
    ranks = np.empty(len(values), dtype=np.float64)
    start = 0
    while start < len(values):
        stop = start + 1
        while stop < len(values) and sorted_values[stop] == sorted_values[start]:
            stop += 1
        average_rank = (start + stop - 1) / 2.0
        ranks[order[start:stop]] = average_rank / (len(values) - 1)
        start = stop
    return ranks


def one_positive_metrics(ranks: np.ndarray, cutoff: int = 10) -> dict[str, float]:
    ranks = np.asarray(ranks, dtype=np.int64)
    hit = ranks <= cutoff
    return {
        f"ndcg_at_{cutoff}": float(np.mean(np.where(hit, 1.0 / np.log2(ranks + 1), 0.0))) if len(ranks) else 0.0,
        f"hit_rate_at_{cutoff}": float(np.mean(hit)) if len(ranks) else 0.0,
        f"mrr_at_{cutoff}": float(np.mean(np.where(hit, 1.0 / ranks, 0.0))) if len(ranks) else 0.0,
    }


def ranks_from_scores(scores: np.ndarray, target_positions: np.ndarray) -> np.ndarray:
    """One-based rank with deterministic item-position tie breaking."""
    ranks = np.empty(len(scores), dtype=np.int64)
    for row_number, (row, target_position) in enumerate(zip(scores, target_positions)):
        target_score = row[target_position]
        ranks[row_number] = 1 + int(np.sum(row > target_score)) + int(
            np.sum((row == target_score) & (np.arange(len(row)) < target_position))
        )
    return ranks


def candidate_metrics(ranks: np.ndarray) -> dict[str, float]:
    output = {}
    for cutoff in (5, 10):
        output.update(one_positive_metrics(ranks, cutoff))
    return output


def cosine_scores(profile: np.ndarray, candidates: np.ndarray) -> np.ndarray:
    profile = np.asarray(profile, dtype=np.float64)
    candidates = np.asarray(candidates, dtype=np.float64)
    denominator = np.linalg.norm(candidates, axis=1) * np.linalg.norm(profile)
    return np.divide(candidates @ profile, denominator, out=np.zeros(len(candidates)), where=denominator > 0)
