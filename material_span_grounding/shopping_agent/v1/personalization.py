from __future__ import annotations

import hashlib
import math
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

import numpy as np

from recommendation_api.tactile_models import TactileIntent

from .database import AgentDatabase
from .tools import ShoppingTools


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, float(value)))


def _cosine01(left: np.ndarray, right: np.ndarray) -> float:
    return _clamp((float(left @ right) + 1.0) / 2.0)


def _age_days(value: str) -> float:
    created = datetime.fromisoformat(value)
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    return max(0.0, (datetime.now(timezone.utc) - created).total_seconds() / 86400.0)


class PersonalizedRanker:
    def __init__(
        self,
        database: AgentDatabase,
        tools: ShoppingTools,
        config: dict[str, Any],
    ) -> None:
        self.database = database
        self.tools = tools
        self.config = config
        weights = self.config["ranking"]
        names = [name for name in weights if name.endswith("_weight")]
        total = sum(float(weights[name]) for name in names)
        if not math.isclose(total, 1.0, abs_tol=1e-9):
            raise ValueError(f"Personalization ranking weights must sum to 1.0, got {total}")

    def _event_signals(self, user_id: str) -> list[dict[str, Any]]:
        event_config = self.config["events"]
        weights = event_config["weights"]
        half_life = float(event_config["behavior_half_life_days"])
        max_dwell = float(event_config["max_dwell_ms"])
        signals = []
        for event in self.database.list_events(user_id):
            if not self.tools.product_exists(str(event["product_id"])):
                continue
            raw_weight = float(weights.get(event["event_type"], 0.0))
            if event["event_type"] == "product_dwell":
                dwell = min(max_dwell, max(0.0, float(event["context"].get("dwell_ms", 0))))
                raw_weight *= dwell / max_dwell
            decay = 0.5 ** (_age_days(event["created_at"]) / half_life)
            value = {**event, "signal_weight": raw_weight * decay}
            signals.append(value)
        return signals

    def _attribute_score(
        self,
        title: str,
        category: str,
        preferences: list[dict[str, Any]],
    ) -> tuple[float, list[str]]:
        normalized = title.casefold()
        values: list[float] = []
        matched: list[str] = []
        for pref in preferences:
            if pref["attribute_type"] not in {"color", "style"}:
                continue
            if pref.get("scope_category") and pref["scope_category"] != category:
                continue
            if str(pref["attribute"]).casefold() not in normalized:
                continue
            sign = -1.0 if pref["direction"] == "avoid" else 1.0
            values.append(sign * float(pref["strength"]) * float(pref["confidence"]))
            matched.append(f"{pref['attribute_type']}:{pref['attribute']}:{pref['direction']}")
        return (sum(values) / max(1, len(values)) if values else 0.0), matched

    def _behavior_scores(
        self,
        candidate_id: str,
        category: str,
        signals: list[dict[str, Any]],
    ) -> tuple[float, float, float]:
        multimodal = self.tools.catalog.multimodal
        if multimodal is None or not signals:
            return 0.0, 0.0, 0.0
        candidate_image = multimodal.image_vector(candidate_id)
        candidate_tactile = multimodal.tactile_vector(candidate_id)
        design_numerator = tactile_numerator = denominator = category_positive = 0.0
        gate_cross = float(self.config["ranking"]["cross_category_behavior_gate"])
        for signal in signals:
            weight = float(signal["signal_weight"])
            anchor_id = str(signal["product_id"])
            anchor_category = self.tools.catalog.product_metadata[anchor_id]["category"]
            gate = 1.0 if anchor_category == category else gate_cross
            magnitude = abs(weight) * gate
            if magnitude <= 0:
                continue
            signed = 1.0 if weight >= 0 else -1.0
            design_numerator += signed * magnitude * _cosine01(
                candidate_image, multimodal.image_vector(anchor_id)
            )
            tactile_numerator += signed * magnitude * _cosine01(
                candidate_tactile, multimodal.tactile_vector(anchor_id)
            )
            denominator += magnitude
            if anchor_category == category and weight > 0:
                category_positive += weight
        if denominator == 0:
            return 0.0, 0.0, 0.0
        return (
            _clamp(design_numerator / denominator, -1.0, 1.0),
            _clamp(tactile_numerator / denominator, -1.0, 1.0),
            _clamp(category_positive / 2.0),
        )

    def _cart_score(self, candidate_id: str, category: str, cart_ids: list[str]) -> float:
        multimodal = self.tools.catalog.multimodal
        if multimodal is None:
            return 0.0
        scores = []
        for anchor_id in cart_ids:
            if anchor_id == candidate_id or not self.tools.product_exists(anchor_id):
                continue
            anchor_category = self.tools.catalog.product_metadata[anchor_id]["category"]
            if anchor_category != category:
                continue
            design = _cosine01(
                multimodal.image_vector(candidate_id), multimodal.image_vector(anchor_id)
            )
            tactile = _cosine01(
                multimodal.tactile_vector(candidate_id), multimodal.tactile_vector(anchor_id)
            )
            scores.append((design + tactile) / 2.0)
        return max(scores, default=0.0)

    @staticmethod
    def _exploration(user_id: str, product_id: str) -> float:
        digest = hashlib.sha256(f"{user_id}:{product_id}".encode()).digest()
        return int.from_bytes(digest[:4], "big") / (2**32 - 1)

    def rank(
        self,
        user_id: str,
        candidates: list[dict[str, Any]],
        *,
        intent: TactileIntent,
        limit: int,
    ) -> dict[str, Any]:
        limit = max(1, min(int(limit), int(self.config["ranking"]["max_result_size"])))
        preferences = self.database.list_preferences(user_id)
        signals = self._event_signals(user_id)
        cart_ids = [str(row["product_id"]) for row in self.database.list_cart(user_id)]
        tactile_by_id = self.tools.tactile.tactile_scores(candidates, intent)
        weights = self.config["ranking"]
        rows = []
        explicit_tactile = bool(
            intent.desired_more or intent.desired_less or intent.avoid or intent.must_have
        )
        for candidate in candidates:
            product_id = str(candidate["product_id"])
            category = str(candidate["category"])
            base = _clamp(float(candidate.get("relevance_score", 0.0)))
            tactile_row = tactile_by_id.get(product_id, {})
            raw_tactile = float(tactile_row.get("tactile_score", 0.0))
            tactile_score = _clamp((raw_tactile + 1.0) / 2.0) if explicit_tactile else 0.0
            attribute_score, matched_attributes = self._attribute_score(
                str(candidate["title"]), category, preferences
            )
            behavior_design, behavior_tactile, category_affinity = self._behavior_scores(
                product_id, category, signals
            )
            cart_score = self._cart_score(product_id, category, cart_ids)
            exploration = self._exploration(user_id, product_id)
            contributions = {
                "query_relevance": float(weights["query_relevance_weight"]) * base,
                "explicit_tactile": float(weights["explicit_tactile_weight"]) * tactile_score,
                "explicit_attribute": float(weights["explicit_attribute_weight"]) * attribute_score,
                "behavior_design": float(weights["behavior_design_weight"]) * behavior_design,
                "behavior_tactile": float(weights["behavior_tactile_weight"]) * behavior_tactile,
                "cart_context": float(weights["cart_context_weight"]) * cart_score,
                "category_affinity": float(weights["category_affinity_weight"]) * category_affinity,
                "exploration": float(weights["exploration_weight"]) * exploration,
            }
            final = _clamp(sum(contributions.values()))
            reasons = []
            if matched_attributes:
                reasons.append("저장된 색상·스타일 취향")
            if explicit_tactile and tactile_score > 0:
                reasons.append("대화의 촉감 조건")
            if behavior_design > 0.15:
                reasons.append("최근 본 상품의 디자인")
            if behavior_tactile > 0.15 and float(weights["behavior_tactile_weight"]) > 0:
                reasons.append("최근 본 상품의 촉감")
            if cart_score > 0.5:
                reasons.append("장바구니 상품과의 유사성")
            value = {
                **candidate,
                "personalized_score": final,
                "personalization_reasons": reasons,
                "score_breakdown": {
                    **candidate.get("score_breakdown", {}),
                    "personalization_inputs": {
                        "query_relevance": base,
                        "explicit_tactile": tactile_score,
                        "explicit_attribute": attribute_score,
                        "behavior_design": behavior_design,
                        "behavior_tactile": behavior_tactile,
                        "cart_context": cart_score,
                        "category_affinity": category_affinity,
                        "exploration": exploration,
                    },
                    "personalization_weighted": contributions,
                    "personalized_final_score": final,
                },
            }
            rows.append(value)
        rows.sort(key=lambda row: (-row["personalized_score"], row["product_id"]))
        return {
            "results": rows[:limit],
            "profile_summary": {
                "preference_count": len(preferences),
                "behavior_event_count": len(signals),
                "cart_item_count": len(cart_ids),
                "personalization_applied": bool(preferences or signals or cart_ids),
            },
        }

