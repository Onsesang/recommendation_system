from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any, Iterable

from .tactile_models import TactileClaim
from .tactile_normalization import ConceptMatch
from .tactile_store import TactileStore


_KOREAN_LABELS = {
    "softness": ("부드러움", "부드럽다고", "부드럽지 않다고"),
    "scratchiness": ("까슬거림", "까슬거린다고", "까슬거리지 않는다고"),
    "itchiness": ("가려움", "가렵다고", "가렵지 않다고"),
    "roughness": ("거친 촉감", "거칠다고", "거칠지 않다고"),
    "weight_lightness": ("가벼운 무게감", "가볍다고", "가볍지 않다고"),
    "heaviness": ("무거운 무게감", "무겁다고", "무겁지 않다고"),
    "thinness": ("얇은 두께", "얇다고", "얇지 않다고"),
    "thickness": ("두꺼운 두께", "두껍다고", "두껍지 않다고"),
    "sheerness": ("비침", "비친다고", "비치지 않는다고"),
    "opacity": ("불투명함", "불투명하다고", "불투명하지 않다고"),
    "stretchiness": ("신축성", "신축성이 있다고", "신축성이 없다고"),
    "stiffness": ("뻣뻣함", "뻣뻣하다고", "뻣뻣하지 않다고"),
    "breathability": ("통기성", "통기성이 있다고", "통기성이 부족하다고"),
    "warmth": ("따뜻함", "따뜻하다고", "따뜻하지 않다고"),
    "coolness": ("시원함", "시원하다고", "시원하지 않다고"),
    "flowiness": ("흐르는 듯한 촉감", "유연하게 흐른다고", "유연하게 흐르지 않는다고"),
    "linting": ("보풀·먼지 묻음", "보풀이나 먼지가 묻는다고", "보풀이나 먼지가 묻지 않는다고"),
    "pilling": ("필링", "필링이 생긴다고", "필링이 생기지 않는다고"),
}
_SENTIMENTS = ("positive", "neutral", "negative", "unknown")


@dataclass(frozen=True)
class _ReviewerEvidence:
    reviewer_key: str
    vote: int
    representative: tuple[TactileClaim, ConceptMatch]
    pairs: tuple[tuple[TactileClaim, ConceptMatch], ...]


def _reviewer_key(claim: TactileClaim) -> str:
    # review_id is deliberately the fallback: no private reviewer identifier is returned.
    return claim.reviewer_id or claim.review_id


def _sentiment(value: str) -> str:
    normalized = str(value).casefold()
    return normalized if normalized in _SENTIMENTS[:-1] else "unknown"


def _reviewer_evidence(
    evidence: Iterable[tuple[TactileClaim, ConceptMatch]],
) -> list[_ReviewerEvidence]:
    grouped: dict[str, list[tuple[TactileClaim, ConceptMatch]]] = defaultdict(list)
    for pair in evidence:
        grouped[_reviewer_key(pair[0])].append(pair)

    rows = []
    for reviewer_key, pairs in grouped.items():
        directions = {match.direction for _, match in pairs}
        vote = next(iter(directions)) if len(directions) == 1 else 0
        representative = min(
            pairs,
            key=lambda pair: (-pair[0].confidence, pair[0].claim_id),
        )
        rows.append(
            _ReviewerEvidence(
                reviewer_key=reviewer_key,
                vote=vote,
                representative=representative,
                pairs=tuple(pairs),
            )
        )
    return sorted(rows, key=lambda row: (-row.representative[0].confidence, row.reviewer_key))


def _display_terms(concept: str, fallback_label: str) -> tuple[str, str, str]:
    if concept in _KOREAN_LABELS:
        return _KOREAN_LABELS[concept]
    # Unknown open-vocabulary claims are quoted, not assigned an invented Korean meaning.
    label = fallback_label.strip()
    return (f"‘{label}’", f"‘{label}’라고", f"‘{label}’가 아니라고")


def _display_text(
    *,
    label: str,
    present_phrase: str,
    absent_phrase: str,
    reviewer_count: int,
    present: int,
    absent: int,
    mixed: int,
) -> str:
    contradictory = (present > 0 and absent > 0) or mixed > 0
    if contradictory:
        parts = []
        if present:
            parts.append(f"있다는 의견 {present}명")
        if absent:
            parts.append(f"없다는 의견 {absent}명")
        if mixed:
            parts.append(f"한 리뷰 안에서 엇갈린 의견 {mixed}명")
        return f"{label} 특성에 대한 구매자 의견이 엇갈립니다({', '.join(parts)})."

    phrase = present_phrase if present else absent_phrase
    if reviewer_count == 1:
        return f"구매자 1명이 {phrase} 언급했습니다."
    return f"서로 다른 구매자 {reviewer_count}명이 {phrase} 언급했습니다."


def _representative_pairs(
    reviewers: list[_ReviewerEvidence], limit: int
) -> list[tuple[TactileClaim, ConceptMatch]]:
    """Choose exact spans with reviewer diversity and both sides of a conflict."""
    if limit <= 0:
        return []
    candidates: list[tuple[TactileClaim, ConceptMatch]] = []
    for reviewer in reviewers:
        # A mixed reviewer may need two spans to make the contradiction inspectable.
        by_direction: dict[int, tuple[TactileClaim, ConceptMatch]] = {}
        for pair in reviewer.pairs:
            direction = pair[1].direction
            current = by_direction.get(direction)
            if current is None or (-pair[0].confidence, pair[0].claim_id) < (
                -current[0].confidence,
                current[0].claim_id,
            ):
                by_direction[direction] = pair
        candidates.extend(by_direction.values())

    candidates.sort(key=lambda pair: (-pair[0].confidence, pair[0].claim_id))
    selected: list[tuple[TactileClaim, ConceptMatch]] = []
    # Reserve evidence for each observed direction before filling by confidence.
    for direction in (1, -1):
        pair = next((candidate for candidate in candidates if candidate[1].direction == direction), None)
        if pair is not None and pair not in selected and len(selected) < limit:
            selected.append(pair)
    for pair in candidates:
        if pair not in selected and len(selected) < limit:
            selected.append(pair)
    return selected


class TactileDescriptionService:
    """Build conservative, review-grounded Korean tactile descriptions.

    The service is transport independent so the same contract can be wired to an HTTP
    handler, CLI, or offline evaluation without duplicating aggregation logic.
    """

    def __init__(self, store: TactileStore) -> None:
        self.store = store
        self.evidence_limit = int(store.config["profile"]["public_evidence_per_concept"])

    def describe(self, product_id: str) -> dict[str, Any]:
        self.store.require_feature("tactile_summary")
        if product_id not in self.store.product_metadata:
            raise KeyError(f"Unknown ASIN: {product_id}")

        meta = self.store.product_metadata[product_id]
        claims = self.store.claims_by_asin.get(product_id, [])
        if not claims:
            return {
                "product_id": product_id,
                "title": meta["title"],
                "status": "insufficient_evidence",
                "summary": [],
                "reviewer_count": 0,
                "review_count": 0,
                "claim_count": 0,
                "source_breakdown": {},
                "message": "구매자 리뷰에서 촉감·소재 관련 근거를 찾지 못했습니다.",
            }

        summaries = [
            self._concept_summary(concept, evidence)
            for concept, evidence in self.store.concepts(product_id).items()
        ]
        summaries.sort(
            key=lambda row: (-row["reviewer_count"], -row["confidence"], row["concept"])
        )
        reviewers = {_reviewer_key(claim) for claim in claims}
        reviews = {claim.review_id for claim in claims}
        sources = Counter(claim.source for claim in claims)
        return {
            "product_id": product_id,
            "title": meta["title"],
            "status": "available",
            "summary": summaries,
            "reviewer_count": len(reviewers),
            "review_count": len(reviews),
            "claim_count": len({claim.claim_id for claim in claims}),
            "source_breakdown": dict(sorted(sources.items())),
            "message": "구매자 리뷰에서 확인된 촉감·소재 의견입니다.",
        }

    def _concept_summary(
        self, concept: str, evidence: list[tuple[TactileClaim, ConceptMatch]]
    ) -> dict[str, Any]:
        reviewers = _reviewer_evidence(evidence)
        votes = Counter(row.vote for row in reviewers)
        sentiments = Counter(_sentiment(row.representative[0].sentiment) for row in reviewers)
        sources = Counter(row.representative[0].source for row in reviewers)
        present, absent, mixed = votes[1], votes[-1], votes[0]
        contradictory = (present > 0 and absent > 0) or mixed > 0
        fallback_label = reviewers[0].representative[1].label
        display_label, present_phrase, absent_phrase = _display_terms(concept, fallback_label)
        dominant = max(present, absent)
        agreement_ratio = dominant / len(reviewers) if reviewers else 0.0
        mean_confidence = (
            sum(row.representative[0].confidence for row in reviewers) / len(reviewers)
            if reviewers
            else 0.0
        )
        confidence = max(0.0, min(1.0, mean_confidence * agreement_ratio))
        selected = _representative_pairs(reviewers, self.evidence_limit)
        evidence_details = [
            {
                "claim_id": claim.claim_id,
                "review_id": claim.review_id,
                "original_span": claim.original_span,
                "direction": "present" if match.direction == 1 else "absent",
                "sentiment": _sentiment(claim.sentiment),
                "confidence": claim.confidence,
                "source": claim.source,
                "human_verified": claim.human_verified,
                "verified_purchase": claim.verified_purchase,
            }
            for claim, match in selected
        ]
        return {
            "concept": concept,
            "label": fallback_label,
            "display_label": display_label,
            "display_text": _display_text(
                label=display_label,
                present_phrase=present_phrase,
                absent_phrase=absent_phrase,
                reviewer_count=len(reviewers),
                present=present,
                absent=absent,
                mixed=mixed,
            ),
            "reviewer_count": len(reviewers),
            "confidence": round(confidence, 3),
            "agreement_ratio": round(agreement_ratio, 3),
            "contradictory": contradictory,
            "sentiment_distribution": {
                "positive": sentiments["positive"],
                "neutral": sentiments["neutral"],
                "negative": sentiments["negative"],
                **({"unknown": sentiments["unknown"]} if sentiments["unknown"] else {}),
            },
            "direction_distribution": {
                "present": present,
                "absent": absent,
                "mixed": mixed,
            },
            "source_breakdown": dict(sorted(sources.items())),
            "representative_evidence": [row["original_span"] for row in evidence_details],
            "evidence_details": evidence_details,
        }


def describe_product_tactile(store: TactileStore, product_id: str) -> dict[str, Any]:
    """Functional entry point for callers that do not retain a service instance."""
    return TactileDescriptionService(store).describe(product_id)
