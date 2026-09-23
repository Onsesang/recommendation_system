from __future__ import annotations

import math
import re
import time
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from .config import DemoConfig
from .models import TACTILE_CLASSES, StructuredQuery


TACTILE_LABELS_KO = {
    "soft": "부드러움",
    "firm": "탄탄함",
    "smooth": "매끄러움",
    "rough": "거침/까슬함",
    "non_elastic": "신축성 없음",
    "elastic": "신축성",
    "thin": "얇음",
    "thick": "두꺼움",
    "flexible": "유연함",
    "stiff": "뻣뻣함",
    "warm": "따뜻함",
    "cool": "시원함",
    "spongy": "폭신함",
    "crisp": "각 잡힌 느낌",
}

CATEGORY_LABELS_KO = {
    "shirt": "셔츠",
    "tshirt": "티셔츠",
    "sweater": "니트/스웨터",
    "jacket": "자켓",
    "coat": "코트",
    "pants": "바지",
    "jeans": "청바지",
    "dress": "원피스/드레스",
    "skirt": "스커트",
    "hoodie": "후드",
    "cardigan": "가디건",
    "top": "상의",
    "outerwear": "아우터",
    "underwear": "언더웨어",
    "sleepwear": "잠옷",
    "swimwear": "수영복",
    "accessory": "액세서리",
}


@dataclass(frozen=True)
class CategorySpec:
    broad_categories: tuple[str, ...]
    title_pattern: str | None = None


CATEGORY_SPECS = {
    "shirt": CategorySpec(("top",), r"\b(?:shirt|blouse)\b"),
    "tshirt": CategorySpec(("top",), r"\b(?:t[- ]?shirt|tee)\b"),
    "sweater": CategorySpec(("sweater",)),
    "jacket": CategorySpec(("outerwear",), r"\bjacket\b"),
    "coat": CategorySpec(("outerwear",), r"\bcoat\b"),
    "pants": CategorySpec(("pants",)),
    "jeans": CategorySpec(("pants",), r"\b(?:jeans?|denim)\b"),
    "dress": CategorySpec(("dress",)),
    "skirt": CategorySpec(("skirt",)),
    "hoodie": CategorySpec(("top", "sweater", "outerwear"), r"\bhood(?:ie|ed)\b"),
    "cardigan": CategorySpec(("sweater",), r"\bcardigan\b"),
    "top": CategorySpec(("top",)),
    "outerwear": CategorySpec(("outerwear",)),
    "underwear": CategorySpec(("underwear",)),
    "sleepwear": CategorySpec(("sleepwear",)),
    "swimwear": CategorySpec(("swimwear",)),
    "accessory": CategorySpec(("accessory",)),
}


class ExplicitTactileRecommender:
    """Vectorized full-catalog ranking over the frozen Last2 probability cache."""

    def __init__(
        self,
        config: DemoConfig | None = None,
        *,
        metadata: pd.DataFrame | None = None,
        profiles: pd.DataFrame | None = None,
    ) -> None:
        started = time.perf_counter()
        self.config = config or DemoConfig.load()
        if metadata is None:
            metadata = pd.read_parquet(
                self.config.metadata_path,
                columns=["iid", "parent_asin", "train_count", "title", "category", "image_url"],
            )
        if profiles is None:
            profiles = pd.read_parquet(
                self.config.profiles_path,
                columns=["iid", "parent_asin", *TACTILE_CLASSES],
            )
        metadata = metadata.sort_values("iid").reset_index(drop=True)
        if not np.array_equal(metadata["iid"].to_numpy(), np.arange(len(metadata))):
            raise ValueError("metadata iid must be contiguous and aligned to row positions")
        profiles = profiles.sort_values("iid").reset_index(drop=True)
        ids = profiles["iid"].to_numpy(dtype=np.int32, copy=True)
        if ids.size == 0 or ids.min() < 0 or ids.max() >= len(metadata):
            raise ValueError("Last2 profile iid is outside the metadata catalog")
        expected_asins = metadata["parent_asin"].to_numpy()[ids].astype(str)
        if not np.array_equal(expected_asins, profiles["parent_asin"].astype(str).to_numpy()):
            raise ValueError("metadata and Last2 profile ASINs are not aligned")

        self.iids = ids
        self.asins = expected_asins
        self.titles = metadata["title"].fillna("제목 정보 없음").astype(str).to_numpy()[ids]
        self.categories = metadata["category"].fillna("other").astype(str).to_numpy()[ids]
        self.image_urls = metadata["image_url"].fillna("").astype(str).to_numpy()[ids]
        self.train_counts = metadata["train_count"].fillna(0).to_numpy(dtype=np.int32)[ids]
        self.matrix = profiles[list(TACTILE_CLASSES)].to_numpy(dtype=np.float32, copy=True)
        if not np.isfinite(self.matrix).all() or (self.matrix < 0).any() or (self.matrix > 1).any():
            raise ValueError("Last2 probabilities must be finite and within [0, 1]")
        self._class_index = {name: i for i, name in enumerate(TACTILE_CLASSES)}
        self._iid_to_row = np.full(len(metadata), -1, dtype=np.int32)
        self._iid_to_row[ids] = np.arange(len(ids), dtype=np.int32)
        self._category_cache: dict[str, tuple[np.ndarray, bool]] = {}
        self.load_seconds = time.perf_counter() - started

    def _candidate_rows(self, category: str | None) -> tuple[np.ndarray, bool]:
        if category is None:
            return np.arange(len(self.iids), dtype=np.int32), False
        cached = self._category_cache.get(category)
        if cached is not None:
            return cached
        spec = CATEGORY_SPECS[category]
        broad_mask = np.isin(self.categories, spec.broad_categories)
        broad_rows = np.flatnonzero(broad_mask).astype(np.int32)
        relaxed = False
        rows = broad_rows
        if spec.title_pattern:
            broad_titles = pd.Series(self.titles[broad_rows], copy=False)
            specific = broad_titles.str.contains(
                spec.title_pattern, case=False, regex=True, na=False
            ).to_numpy()
            specific_rows = broad_rows[specific]
            if len(specific_rows) >= self.config.specific_category_min_candidates:
                rows = specific_rows
            else:
                relaxed = True
        self._category_cache[category] = (rows, relaxed)
        return rows, relaxed

    def _class_weight(self, tactile_class: str, requested: float) -> float:
        return float(requested) * float(
            self.config.class_weight_overrides.get(tactile_class, 1.0)
        )

    def recommend(self, query: StructuredQuery, *, top_k: int | None = None) -> dict[str, Any]:
        requested_k = self.config.default_top_k if top_k is None else int(top_k)
        if not 1 <= requested_k <= self.config.maximum_top_k:
            raise ValueError(f"top_k must be in [1, {self.config.maximum_top_k}]")
        candidates, category_relaxed = self._candidate_rows(query.category)
        if not len(candidates):
            return self._payload(query, [], 0, category_relaxed, "no_category_candidates")

        numerator = np.zeros(len(candidates), dtype=np.float32)
        total_weight = 0.0
        terms: list[tuple[str, str, float]] = []
        for direction, constraints in (
            ("positive", query.constraints),
            ("negative", query.negative_constraints),
        ):
            for constraint in constraints:
                weight = self._class_weight(constraint.tactile_class, constraint.weight)
                values = self.matrix[candidates, self._class_index[constraint.tactile_class]]
                numerator += weight * (values if direction == "positive" else 1.0 - values)
                total_weight += weight
                terms.append((direction, constraint.tactile_class, weight))

        if total_weight:
            scores = numerator / total_weight
            order = np.lexsort(
                (self.asins[candidates], -self.train_counts[candidates], -scores)
            )
            mode = "last2_explicit_tactile"
        else:
            scores = np.zeros(len(candidates), dtype=np.float32)
            order = np.lexsort((self.asins[candidates], -self.train_counts[candidates]))
            mode = "initial_popularity"

        selected = order[: min(requested_k, len(order))]
        rows = [
            self._product(
                int(candidates[position]),
                rank=rank,
                score=float(scores[position]),
                terms=terms,
                total_weight=total_weight,
                ranking_mode=mode,
            )
            for rank, position in enumerate(selected, 1)
        ]
        for row in rows:
            self.validate_reason(row)
        return self._payload(query, rows, len(candidates), category_relaxed, mode)

    def initial_recommendations(self) -> dict[str, Any]:
        return self.recommend(
            StructuredQuery(source="initial_catalog"),
            top_k=self.config.initial_catalog_size,
        )

    def _product(
        self,
        row_index: int,
        *,
        rank: int,
        score: float,
        terms: list[tuple[str, str, float]],
        total_weight: float,
        ranking_mode: str,
    ) -> dict[str, Any]:
        all_predictions = {
            name: float(self.matrix[row_index, column])
            for column, name in enumerate(TACTILE_CLASSES)
        }
        selected_scores = {name: all_predictions[name] for _, name, _ in terms}
        breakdown_terms = []
        reason_parts = []
        for direction, tactile_class, weight in terms:
            raw = all_predictions[tactile_class]
            match_component = raw if direction == "positive" else 1.0 - raw
            breakdown_terms.append(
                {
                    "direction": direction,
                    "class": tactile_class,
                    "raw_probability": raw,
                    "match_component": match_component,
                    "weight": weight,
                    "weighted_component": weight * match_component,
                }
            )
            label = TACTILE_LABELS_KO[tactile_class]
            if direction == "positive":
                reason_parts.append(f"{label} {raw:.2f}")
            else:
                reason_parts.append(f"{label} 예측 {raw:.2f}(낮을수록 조건에 부합)")

        if reason_parts:
            reason = (
                "이미지 기반 Last2 촉각 예측에서 "
                + ", ".join(reason_parts)
                + f"이며 종합 일치 점수는 {score:.2f}입니다."
            )
        else:
            reason = "기존 Amazon 상호작용 수를 기준으로 첫 화면에 표시한 상품입니다."

        return {
            "rank": rank,
            "iid": int(self.iids[row_index]),
            "item_id": str(self.asins[row_index]),
            "parent_asin": str(self.asins[row_index]),
            "title": str(self.titles[row_index]),
            "category": str(self.categories[row_index]),
            "image_url": str(self.image_urls[row_index]) or None,
            "score": score,
            "tactile_match": score if terms else None,
            "train_count": int(self.train_counts[row_index]),
            "tactile_scores": selected_scores,
            "all_tactile_predictions": all_predictions,
            "reason": reason,
            "reason_evidence": breakdown_terms,
            "score_breakdown": {
                "ranking_mode": ranking_mode,
                "formula": "sum(weight * P(positive) + weight * (1-P(negative))) / sum(weight)",
                "terms": breakdown_terms,
                "total_weight": total_weight,
                "final_tactile_match": score if terms else None,
                "tie_breakers": ["train_count_desc", "parent_asin_asc"],
            },
        }

    def validate_reason(self, product: dict[str, Any], *, atol: float = 1e-7) -> None:
        """Fail closed when explanation evidence differs from the source Last2 row."""
        iid = int(product["iid"])
        if iid < 0 or iid >= len(self._iid_to_row) or self._iid_to_row[iid] < 0:
            raise AssertionError(f"unknown tactile iid in explanation: {iid}")
        row_index = int(self._iid_to_row[iid])
        for term in product["reason_evidence"]:
            tactile_class = term["class"]
            original = float(self.matrix[row_index, self._class_index[tactile_class]])
            displayed = float(term["raw_probability"])
            if not math.isclose(original, displayed, rel_tol=0.0, abs_tol=atol):
                raise AssertionError(
                    f"reason probability mismatch for iid={iid}, class={tactile_class}"
                )
            if f"{displayed:.2f}" not in product["reason"]:
                raise AssertionError(
                    f"formatted evidence missing from reason for iid={iid}, class={tactile_class}"
                )

    def _payload(
        self,
        query: StructuredQuery,
        products: list[dict[str, Any]],
        candidate_count: int,
        category_relaxed: bool,
        ranking_mode: str,
    ) -> dict[str, Any]:
        return {
            "interpreted_query": query.public_dict(),
            "products": products,
            "result_count": len(products),
            "retrieval": {
                "candidate_count": candidate_count,
                "requested_category": query.category,
                "catalog_category_filter": (
                    list(CATEGORY_SPECS[query.category].broad_categories)
                    if query.category
                    else None
                ),
                "specific_category_relaxed": category_relaxed,
                "ranking_mode": ranking_mode,
                "vectorized": True,
            },
            "provenance": {
                "last2_profiles": str(self.config.profiles_path),
                "metadata": str(self.config.metadata_path),
                "checkpoint": str(self.config.checkpoint_path),
                "checkpoint_sha256": self.config.checkpoint_sha256,
                "evidence_source": "image_estimated",
                "new_inference_performed": False,
            },
        }
