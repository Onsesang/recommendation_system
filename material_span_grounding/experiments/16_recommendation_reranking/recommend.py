#!/usr/bin/env python3
from __future__ import annotations

from functools import lru_cache
from typing import Iterable

import numpy as np
import pandas as pd
import torch

from common import ARTIFACTS, CONFIG_PATH, MODELS, percentile_rank, read_json
from recommender_core import load_checkpoint, load_events


class RecommendationService:
    def __init__(self, device: str | None = None) -> None:
        self.config = read_json(CONFIG_PATH)
        self.selection = read_json(ARTIFACTS / "selection.json")
        self.device = torch.device(device or ("cuda" if torch.cuda.is_available() else "cpu"))
        self.model, self.checkpoint, self.user_map, self.item_map = load_checkpoint(MODELS / "bpr_final.pt", self.device)
        self.products = pd.read_parquet(ARTIFACTS / "product_tactile_profiles.parquet").sort_values("item_id").reset_index(drop=True)
        self.classes = read_json(ARTIFACTS / "tactile_profile_manifest.json")["classes"]
        self.item_tactile = self.products[self.classes].to_numpy(np.float64)
        self.events = load_events()
        self.history = self.events[self.events["split"].isin(["train", "validation"])].copy()

    @property
    def known_users(self) -> list[str]:
        return self.checkpoint["user_ids"]

    def _history(self, user_id: str) -> pd.DataFrame:
        history = self.history[self.history["user_id"] == user_id]
        if history.empty or user_id not in self.user_map:
            raise ValueError(f"unknown user_id or no tactile-eligible pre-test history: {user_id}")
        return history

    def recommend(self, user_id: str, desired_tactile: Iterable[str] | None = None, category_filter: str | None = None, top_k: int = 10) -> dict:
        history = self._history(user_id)
        desired = list(desired_tactile or [])
        invalid = sorted(set(desired) - set(self.classes))
        if invalid:
            raise ValueError(f"unknown tactile classes: {invalid}")
        with torch.inference_mode():
            user = torch.tensor([self.user_map[user_id]], device=self.device)
            base_all = self.model.all_scores(user)[0].cpu().numpy()
        seen = [self.item_map[item] for item in history["item_id"]]
        base_all[seen] = -np.inf
        eligible = np.ones(len(self.products), dtype=bool)
        if category_filter:
            eligible &= self.products["category"].to_numpy() == category_filter
        eligible[seen] = False
        available = np.flatnonzero(eligible)
        if not len(available):
            raise ValueError("no unseen eligible item remains after filtering")
        candidate_k = min(self.selection["candidate_k"], len(available))
        local = np.argpartition(base_all[available], -candidate_k)[-candidate_k:]
        candidates = available[local]
        candidates = candidates[np.argsort(-base_all[candidates], kind="stable")]
        base_norm = percentile_rank(base_all[candidates])
        history_products = history.merge(self.products[["item_id", "category", *self.classes]], on="item_id", how="inner")
        category_frequency = history_products["category"].value_counts(normalize=True).to_dict()
        category_raw = np.asarray([category_frequency.get(category, 0.0) for category in self.products.iloc[candidates]["category"]])
        category_norm = percentile_rank(category_raw)
        if desired:
            tactile_raw = self.item_tactile[candidates][:, [self.classes.index(name) for name in desired]].mean(axis=1)
            tactile_source = {"mode": "explicit", "classes": desired}
            user_profile = None
        else:
            user_profile = history_products[self.classes].to_numpy(np.float64).mean(axis=0)
            vectors = self.item_tactile[candidates]
            denominator = np.linalg.norm(vectors, axis=1) * np.linalg.norm(user_profile)
            tactile_raw = np.divide(vectors @ user_profile, denominator, out=np.zeros(len(vectors)), where=denominator > 0)
            tactile_source = {"mode": "historical", "history_items": len(history_products)}
        tactile_norm = percentile_rank(tactile_raw)
        beta, alpha = self.selection["beta_star"], self.selection["alpha_star"]
        category_score = (1-beta)*base_norm + beta*category_norm
        non_tactile_norm = percentile_rank(category_score)
        proposed_score = (1-alpha)*non_tactile_norm + alpha*tactile_norm
        method_scores = {"vanilla": base_norm, "category_aware": category_score, "proposed": proposed_score}
        output = {"user_id": user_id, "category_filter": category_filter, "tactile_source": tactile_source, "beta_star": beta, "alpha_star": alpha,
                  "explicit_alpha_note": "alpha_star was optimized for next-interaction validation, not explicit-query satisfaction", "methods": {}}
        for method, scores in method_scores.items():
            order = np.argsort(-scores, kind="stable")[:top_k]
            cards = []
            for position in order:
                item = self.products.iloc[candidates[position]]
                detail = []
                if user_profile is not None:
                    names = sorted(self.classes, key=lambda name: -min(user_profile[self.classes.index(name)], float(item[name])))[:3]
                    detail = [{"class": name, "user": float(user_profile[self.classes.index(name)]), "item": float(item[name])} for name in names]
                else:
                    detail = [{"class": name, "item_probability": float(item[name])} for name in desired]
                cards.append({"item_id": str(item.item_id), "category": str(item.category), "image_path": str(item.image_path),
                              "score": float(scores[position]), "vanilla_score_norm": float(base_norm[position]),
                              "category_score_norm": float(category_norm[position]), "tactile_score_norm": float(tactile_norm[position]),
                              "tactile_match_detail": detail})
            output["methods"][method] = cards
        return output


@lru_cache(maxsize=2)
def get_service(device: str | None = None) -> RecommendationService:
    return RecommendationService(device)


def recommend(user_id, desired_tactile=None, category_filter=None, top_k=10):
    return get_service().recommend(user_id, desired_tactile, category_filter, top_k)


if __name__ == "__main__":
    import argparse, json
    parser = argparse.ArgumentParser()
    parser.add_argument("user_id"); parser.add_argument("--desired-tactile", nargs="*", default=[])
    parser.add_argument("--category"); parser.add_argument("--top-k", type=int, default=10)
    args = parser.parse_args()
    print(json.dumps(recommend(args.user_id, args.desired_tactile, args.category, args.top_k), ensure_ascii=False, indent=2))

