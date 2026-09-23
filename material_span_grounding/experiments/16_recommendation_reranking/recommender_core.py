from __future__ import annotations

import random
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import torch
from torch import nn

from common import ARTIFACTS, MODELS, candidate_metrics, one_positive_metrics, read_json, CONFIG_PATH


class BPRMF(nn.Module):
    """Pure collaborative BPR-MF: only user/item IDs enter the model."""

    def __init__(self, users: int, items: int, dimension: int) -> None:
        super().__init__()
        self.user_embedding = nn.Embedding(users, dimension)
        self.item_embedding = nn.Embedding(items, dimension)
        self.item_bias = nn.Embedding(items, 1)
        nn.init.normal_(self.user_embedding.weight, std=0.05)
        nn.init.normal_(self.item_embedding.weight, std=0.05)
        nn.init.zeros_(self.item_bias.weight)

    def score(self, users: torch.Tensor, items: torch.Tensor) -> torch.Tensor:
        return (self.user_embedding(users) * self.item_embedding(items)).sum(-1) + self.item_bias(items).squeeze(-1)

    def all_scores(self, users: torch.Tensor) -> torch.Tensor:
        return self.user_embedding(users) @ self.item_embedding.weight.T + self.item_bias.weight.T


def seed_everything(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)


def load_catalog() -> tuple[pd.DataFrame, list[str], dict[str, int]]:
    profiles = pd.read_parquet(ARTIFACTS / "product_tactile_profiles.parquet").sort_values("item_id").reset_index(drop=True)
    items = profiles["item_id"].astype(str).tolist()
    return profiles, items, {item: index for index, item in enumerate(items)}


def load_events() -> pd.DataFrame:
    return pd.read_parquet(ARTIFACTS / "recommendation_splits.parquet")


def load_cases(split: str) -> pd.DataFrame:
    cases = pd.read_parquet(ARTIFACTS / "evaluation_cases.parquet")
    return cases[cases["split"] == split].sort_values("user_id").reset_index(drop=True)


def history_for_split(events: pd.DataFrame, split: str) -> pd.DataFrame:
    allowed = ["train"] if split == "validation" else ["train", "validation"]
    return events[events["split"].isin(allowed)].copy()


def make_training_arrays(events: pd.DataFrame, item_to_index: dict[str, int]):
    user_ids = sorted(events["user_id"].astype(str).unique())
    user_to_index = {user: index for index, user in enumerate(user_ids)}
    users = events["user_id"].map(user_to_index).to_numpy(np.int64)
    items = events["item_id"].map(item_to_index).to_numpy(np.int64)
    seen: list[set[int]] = [set() for _ in user_ids]
    for user, item in zip(users, items):
        seen[int(user)].add(int(item))
    return user_ids, user_to_index, users, items, seen


def sample_negatives(users: np.ndarray, seen: list[set[int]], item_count: int, count: int, rng: np.random.Generator):
    repeated = np.repeat(users, count)
    negatives = rng.integers(0, item_count, size=len(repeated), dtype=np.int64)
    for idx, user in enumerate(repeated):
        while int(negatives[idx]) in seen[int(user)]:
            negatives[idx] = rng.integers(0, item_count)
    return repeated, negatives


def full_catalog_ranks(
    model: BPRMF,
    cases: pd.DataFrame,
    history: pd.DataFrame,
    user_to_index: dict[str, int],
    item_to_index: dict[str, int],
    device: torch.device,
    batch_size: int,
) -> tuple[np.ndarray, dict[str, float]]:
    history_indices: dict[str, list[int]] = {}
    for user, group in history.groupby("user_id"):
        history_indices[str(user)] = [item_to_index[item] for item in group["item_id"]]
    ranks: list[int] = []
    recalls = {100: 0, 200: 0, 300: 0}
    model.eval()
    with torch.inference_mode():
        for start in range(0, len(cases), batch_size):
            part = cases.iloc[start : start + batch_size]
            user_idx = torch.tensor([user_to_index[user] for user in part["user_id"]], device=device)
            scores = model.all_scores(user_idx)
            for row, (user, target) in enumerate(zip(part["user_id"], part["target_item"])):
                seen = history_indices[str(user)]
                scores[row, seen] = -torch.inf
                target_idx = item_to_index[str(target)]
                target_score = scores[row, target_idx]
                rank = 1 + int((scores[row] > target_score).sum().item())
                ranks.append(rank)
                for cutoff in recalls:
                    recalls[cutoff] += int(rank <= cutoff)
    output = {f"candidate_recall_at_{cutoff}": recalls[cutoff] / len(cases) for cutoff in recalls}
    return np.asarray(ranks), output


def save_checkpoint(path: Path, model: BPRMF, user_ids: list[str], item_ids: list[str], epoch: int, config: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    torch.save({
        "state_dict": {key: value.detach().cpu() for key, value in model.state_dict().items()},
        "user_ids": user_ids,
        "item_ids": item_ids,
        "embedding_dim": config["bpr"]["embedding_dim"],
        "epoch": epoch,
        "input_features": ["user_id", "item_id", "implicit_interaction"],
        "seed": config["seed"],
    }, path)


def load_checkpoint(path: Path, device: torch.device):
    checkpoint = torch.load(path, map_location="cpu", weights_only=False)
    model = BPRMF(len(checkpoint["user_ids"]), len(checkpoint["item_ids"]), checkpoint["embedding_dim"])
    model.load_state_dict(checkpoint["state_dict"])
    model.to(device).eval()
    return model, checkpoint, {u: i for i, u in enumerate(checkpoint["user_ids"])}, {x: i for i, x in enumerate(checkpoint["item_ids"])}


def train_model(events: pd.DataFrame, item_ids: list[str], epochs: int, config: dict, device: torch.device):
    _, _, item_to_index = load_catalog()
    user_ids, user_to_index, positives_u, positives_i, seen = make_training_arrays(events, item_to_index)
    model = BPRMF(len(user_ids), len(item_ids), config["bpr"]["embedding_dim"]).to(device)
    optimizer = torch.optim.Adam(model.parameters(), lr=config["bpr"]["learning_rate"], weight_decay=config["bpr"]["weight_decay"])
    rng = np.random.default_rng(config["seed"])
    batch_size = config["bpr"]["batch_size"]
    neg_count = config["bpr"]["negative_samples"]
    losses = []
    for epoch in range(1, epochs + 1):
        epoch_users, negative = sample_negatives(positives_u, seen, len(item_ids), neg_count, rng)
        positive = np.repeat(positives_i, neg_count)
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
        losses.append(total / len(order))
    return model, user_ids, user_to_index, item_to_index, losses

