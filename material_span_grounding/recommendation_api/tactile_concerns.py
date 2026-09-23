from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Mapping

from .tactile_models import TactileClaim, TactileEvidence
from .tactile_normalization import canonical_concept


@dataclass(frozen=True)
class ConcernPolicy:
    """Precision-oriented policy, overlaid by ``config["concern"]`` values."""

    min_reviewers: int = 2
    min_negative_ratio: float = 0.5
    minimum_score: float = 0.18
    reviewer_saturation: float = 4.0
    verified_purchase_bonus: float = 0.05
    human_verified_bonus: float = 0.1
    min_direction_agreement: float = 2.0 / 3.0
    rating_influence: float = 0.2
    moderate_severity_score: float = 0.35
    high_severity_score: float = 0.6
    evidence_limit: int = 5

    @classmethod
    def from_config(
        cls,
        values: Mapping[str, Any] | None,
        *,
        evidence_limit: int | None = None,
    ) -> "ConcernPolicy":
        source = dict(values or {})
        if evidence_limit is not None:
            source.setdefault("evidence_limit", evidence_limit)
        known = {name for name in cls.__dataclass_fields__}
        policy = cls(**{name: source[name] for name in known if name in source})
        policy._validate()
        return policy

    def _validate(self) -> None:
        if self.min_reviewers < 2:
            raise ValueError("concern.min_reviewers must be at least 2")
        if self.reviewer_saturation <= 0:
            raise ValueError("concern.reviewer_saturation must be positive")
        if self.evidence_limit < 1:
            raise ValueError("concern.evidence_limit must be positive")
        for name in (
            "min_negative_ratio",
            "minimum_score",
            "verified_purchase_bonus",
            "human_verified_bonus",
            "min_direction_agreement",
            "rating_influence",
            "moderate_severity_score",
            "high_severity_score",
        ):
            value = float(getattr(self, name))
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"concern.{name} must be between 0 and 1")
        if self.high_severity_score < self.moderate_severity_score:
            raise ValueError("concern severity thresholds must be increasing")


def _reviewer_key(claim: TactileClaim) -> str:
    # Review ID is a privacy-safe internal fallback when the source has no reviewer ID.
    return claim.reviewer_id or f"review:{claim.review_id}"


def _is_negative(claim: TactileClaim) -> bool:
    # A low overall star rating can corroborate an explicit tactile complaint, but it must
    # never turn a neutral tactile statement into a concern by itself.
    return claim.sentiment.casefold() == "negative"


def _rating_support(claim: TactileClaim) -> float | None:
    if claim.rating is None:
        return None
    return (6.0 - float(claim.rating)) / 5.0


def _best_claim(
    evidence: list[tuple[TactileClaim, Any]], direction: int
) -> TactileClaim:
    candidates = [claim for claim, match in evidence if match.direction == direction]
    return sorted(
        candidates,
        key=lambda claim: (
            -int(claim.human_verified),
            -int(claim.verified_purchase is True),
            -claim.confidence,
            claim.rating if claim.rating is not None else 6.0,
            claim.claim_id,
        ),
    )[0]


def _public_evidence(claim: TactileClaim) -> dict[str, Any]:
    return TactileEvidence(
        product_id=claim.product_id,
        claim_id=claim.claim_id,
        claim=claim.normalized_text,
        original_span=claim.original_span,
        review_id=claim.review_id,
        rating=claim.rating,
        verified_purchase=claim.verified_purchase,
        confidence=claim.confidence,
        source=claim.source,
    ).__dict__


class TactileConcernDetector:
    """Detect repeated, independently supported tactile concerns without an LLM."""

    def __init__(
        self,
        store: Any,
        *,
        config: Mapping[str, Any] | None = None,
    ) -> None:
        self.store = store
        store_config = getattr(store, "config", {})
        concern_config = config if config is not None else store_config.get("concern", {})
        evidence_limit = store_config.get("profile", {}).get("public_evidence_per_concept")
        self.policy = ConcernPolicy.from_config(
            concern_config,
            evidence_limit=int(evidence_limit) if evidence_limit is not None else None,
        )

    def detect(self, product_id: str) -> dict[str, Any]:
        self.store.require_feature("tactile_concern")
        if product_id not in self.store.product_metadata:
            raise KeyError(f"Unknown ASIN: {product_id}")

        metadata = self.store.product_metadata[product_id]
        grouped = self.store.concepts(product_id)
        if not grouped:
            return {
                "product_id": product_id,
                "title": metadata.get("title", ""),
                "category": metadata.get("category", ""),
                "status": "insufficient_evidence",
                "concerns": [],
            }

        concerns = []
        for concept, evidence in grouped.items():
            concern = self._score_concept(product_id, concept, evidence)
            if concern is not None:
                concerns.append(concern)
        concerns.sort(
            key=lambda row: (-row["concern_score"], -row["reviewer_count"], row["property"])
        )
        return {
            "product_id": product_id,
            "title": metadata.get("title", ""),
            "category": metadata.get("category", ""),
            "status": "available" if concerns else "no_qualifying_concerns",
            "concerns": concerns,
        }

    def _score_concept(
        self,
        product_id: str,
        concept: str,
        evidence: list[tuple[TactileClaim, Any]],
    ) -> dict[str, Any] | None:
        by_reviewer: dict[str, list[tuple[TactileClaim, Any]]] = {}
        for claim, match in evidence:
            by_reviewer.setdefault(_reviewer_key(claim), []).append((claim, match))

        all_reviewers = len(by_reviewer)
        negative_by_reviewer = {
            reviewer: [(claim, match) for claim, match in rows if _is_negative(claim)]
            for reviewer, rows in by_reviewer.items()
        }
        negative_by_reviewer = {
            reviewer: rows for reviewer, rows in negative_by_reviewer.items() if rows
        }
        negative_reviewers = len(negative_by_reviewer)
        if negative_reviewers < self.policy.min_reviewers:
            return None

        negative_ratio = negative_reviewers / all_reviewers
        if negative_ratio < self.policy.min_negative_ratio:
            return None

        reviewer_directions: dict[str, int | None] = {}
        for reviewer, rows in negative_by_reviewer.items():
            weights = {-1: 0.0, 1: 0.0}
            for claim, match in rows:
                weights[match.direction] += claim.confidence
            if math.isclose(weights[-1], weights[1]):
                reviewer_directions[reviewer] = None
            else:
                reviewer_directions[reviewer] = 1 if weights[1] > weights[-1] else -1

        direction_counts = {
            direction: sum(value == direction for value in reviewer_directions.values())
            for direction in (-1, 1)
        }
        dominant_direction = 1 if direction_counts[1] >= direction_counts[-1] else -1
        agreement = direction_counts[dominant_direction] / negative_reviewers
        if agreement < self.policy.min_direction_agreement:
            return None

        selected = [
            _best_claim(negative_by_reviewer[reviewer], dominant_direction)
            for reviewer, direction in reviewer_directions.items()
            if direction == dominant_direction
        ]
        selected.sort(
            key=lambda claim: (
                -int(claim.human_verified),
                -int(claim.verified_purchase is True),
                -claim.confidence,
                claim.rating if claim.rating is not None else 6.0,
                claim.claim_id,
            )
        )

        verified_ratio = sum(claim.verified_purchase is True for claim in selected) / len(selected)
        human_ratio = sum(claim.human_verified for claim in selected) / len(selected)
        confidence = min(
            1.0,
            sum(claim.confidence for claim in selected) / len(selected)
            + self.policy.verified_purchase_bonus * verified_ratio
            + self.policy.human_verified_bonus * human_ratio,
        )
        rating_values = [value for claim in selected if (value := _rating_support(claim)) is not None]
        rating_support = sum(rating_values) / len(rating_values) if rating_values else None
        rating_factor = (
            1.0
            if rating_support is None
            else 1.0 - self.policy.rating_influence * (1.0 - rating_support)
        )
        reviewer_support = 1.0 - math.exp(
            -negative_reviewers / self.policy.reviewer_saturation
        )
        score = reviewer_support * negative_ratio * confidence * agreement * rating_factor
        if score < self.policy.minimum_score:
            return None

        if score >= self.policy.high_severity_score:
            severity = "high"
        elif score >= self.policy.moderate_severity_score:
            severity = "moderate"
        else:
            severity = "low"

        label = next(
            match.label
            for claim, match in evidence
            if match.direction == dominant_direction
        )
        desired_direction = "less" if dominant_direction == 1 else "more"
        alternative_action = None
        if not canonical_concept(concept).startswith("open:"):
            alternative_action = {
                "type": "tactile_alternatives",
                "current_product_id": product_id,
                "tactile_concept": concept,
                "desired_direction": desired_direction,
            }
        return {
            "property": concept,
            "label": label,
            "category": self.store.product_metadata[product_id].get("category", ""),
            "severity": severity,
            "reviewer_count": negative_reviewers,
            "total_reviewer_count": all_reviewers,
            "negative_ratio": round(negative_ratio, 6),
            "confidence": round(confidence, 6),
            "agreement": round(agreement, 6),
            "rating_support": None if rating_support is None else round(rating_support, 6),
            "verified_purchase_ratio": round(verified_ratio, 6),
            "human_verified_ratio": round(human_ratio, 6),
            "concern_score": round(score, 6),
            "evidence": [
                _public_evidence(claim) for claim in selected[: self.policy.evidence_limit]
            ],
            "alternative_action": alternative_action,
            "alternative_unavailable_reason": (
                None
                if alternative_action is not None
                else "open_vocabulary_direction_not_supported"
            ),
        }


def detect_tactile_concerns(
    store: Any,
    product_id: str,
    *,
    config: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return TactileConcernDetector(store, config=config).detect(product_id)
