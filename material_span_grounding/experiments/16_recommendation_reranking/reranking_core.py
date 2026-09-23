from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import torch

from common import ARTIFACTS, percentile_rank, read_json
from recommender_core import history_for_split, load_cases, load_checkpoint, load_events


def ranks_with_missing(scores: np.ndarray, target_positions: np.ndarray, missing_rank: int = 301) -> np.ndarray:
    result = np.full(len(scores), missing_rank, dtype=np.int32)
    positions = np.arange(scores.shape[1])
    for row, target in enumerate(target_positions):
        if target >= 0:
            target_score = scores[row, target]
            result[row] = 1 + int(np.sum(scores[row] > target_score)) + int(np.sum((scores[row] == target_score) & (positions < target)))
    return result


def generate_candidates(split: str, checkpoint_path: Path, candidate_k: int, device: torch.device) -> dict[str, np.ndarray]:
    model, checkpoint, user_map, item_map = load_checkpoint(checkpoint_path, device)
    cases = load_cases(split)
    events = load_events()
    history = history_for_split(events, split)
    history = history[history["user_id"].isin(set(cases["user_id"]))]
    histories = {str(user): [item_map[item] for item in group["item_id"]] for user, group in history.groupby("user_id")}
    candidates, base_scores, target_positions = [], [], []
    with torch.inference_mode():
        for start in range(0, len(cases), 512):
            part = cases.iloc[start : start + 512]
            user_idx = torch.tensor([user_map[user] for user in part["user_id"]], device=device)
            scores = model.all_scores(user_idx)
            for row, user in enumerate(part["user_id"]):
                scores[row, histories[str(user)]] = -torch.inf
            values, indices = torch.topk(scores, candidate_k, dim=1, sorted=True)
            candidates.append(indices.cpu().numpy().astype(np.int32))
            base_scores.append(values.cpu().numpy().astype(np.float32))
            for row, target in enumerate(part["target_item"]):
                hit = np.flatnonzero(indices[row].cpu().numpy() == item_map[str(target)])
                target_positions.append(int(hit[0]) if len(hit) else -1)
    return {
        "candidate_indices": np.concatenate(candidates),
        "base_scores": np.concatenate(base_scores),
        "target_positions": np.asarray(target_positions, dtype=np.int32),
    }


def add_components(split: str, arrays: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
    manifest = read_json(ARTIFACTS / "tactile_profile_manifest.json")
    classes = manifest["classes"]
    products = pd.read_parquet(ARTIFACTS / "product_tactile_profiles.parquet").sort_values("item_id").reset_index(drop=True)
    cases = load_cases(split)
    category_profiles = pd.read_parquet(ARTIFACTS / "user_category_profiles.parquet")
    category_profiles = category_profiles[category_profiles["profile_split"] == split]
    category_map = {(str(r.user_id), str(r.category)): float(r.preference) for r in category_profiles.itertuples()}
    tactile_profiles = pd.read_parquet(ARTIFACTS / "user_tactile_profiles.parquet")
    tactile_profiles = tactile_profiles[tactile_profiles["profile_split"] == split].set_index("user_id")
    item_categories = products["category"].astype(str).to_numpy()
    item_tactile = products[classes].to_numpy(np.float64)
    rows, width = arrays["candidate_indices"].shape
    base_norm = np.empty((rows, width), np.float32)
    category_norm = np.empty_like(base_norm)
    tactile_norm = np.empty_like(base_norm)
    tactile_rating4_norm = np.full_like(base_norm, np.nan)
    for row, user in enumerate(cases["user_id"]):
        idx = arrays["candidate_indices"][row]
        base_norm[row] = percentile_rank(arrays["base_scores"][row])
        category_raw = np.asarray([category_map.get((str(user), category), 0.0) for category in item_categories[idx]])
        category_norm[row] = percentile_rank(category_raw)
        profile = tactile_profiles.loc[user, [f"all_{name}" for name in classes]].to_numpy(np.float64)
        candidates = item_tactile[idx]
        denominator = np.linalg.norm(candidates, axis=1) * np.linalg.norm(profile)
        tactile_raw = np.divide(candidates @ profile, denominator, out=np.zeros(width), where=denominator > 0)
        tactile_norm[row] = percentile_rank(tactile_raw)
        rating_profile = tactile_profiles.loc[user, [f"rating4_{name}" for name in classes]].to_numpy(np.float64)
        if not np.isnan(rating_profile).any():
            denominator = np.linalg.norm(candidates, axis=1) * np.linalg.norm(rating_profile)
            raw = np.divide(candidates @ rating_profile, denominator, out=np.zeros(width), where=denominator > 0)
            tactile_rating4_norm[row] = percentile_rank(raw)
    return {**arrays, "base_norm": base_norm, "category_norm": category_norm, "tactile_norm": tactile_norm, "tactile_rating4_norm": tactile_rating4_norm}


def save_candidate_bundle(split: str, checkpoint_path: Path, candidate_k: int, device: torch.device) -> Path:
    arrays = add_components(split, generate_candidates(split, checkpoint_path, candidate_k, device))
    path = ARTIFACTS / f"{split}_candidates.npz"
    np.savez_compressed(path, **arrays)
    return path


def popularity_ranks(split: str, item_ids: list[str]) -> np.ndarray:
    cases = load_cases(split)
    events = load_events()
    history = history_for_split(events, split)
    item_map = {item: i for i, item in enumerate(item_ids)}
    counts = history["item_id"].value_counts()
    score = np.asarray([float(counts.get(item, 0)) for item in item_ids])
    histories = {str(user): [item_map[item] for item in group["item_id"]] for user, group in history[history["user_id"].isin(set(cases["user_id"]))].groupby("user_id")}
    result = []
    indices = np.arange(len(item_ids))
    for case in cases.itertuples():
        available = score.copy()
        available[histories[str(case.user_id)]] = -np.inf
        target = item_map[str(case.target_item)]
        result.append(1 + int(np.sum(available > available[target])) + int(np.sum((available == available[target]) & (indices < target))))
    return np.asarray(result, dtype=np.int32)

