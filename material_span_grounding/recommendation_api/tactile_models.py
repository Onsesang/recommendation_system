from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


EvidenceSource = Literal[
    "review_qwen", "review_human_verified", "image_estimated", "metadata"
]
IntentSource = Literal[
    "explicit_structured", "deterministic_nlp", "agent_context"
]


def _probability(name: str, value: float) -> float:
    number = float(value)
    if not 0.0 <= number <= 1.0:
        raise ValueError(f"{name} must be between 0 and 1")
    return number


@dataclass(frozen=True)
class TactileClaim:
    claim_id: str
    product_id: str
    review_id: str
    reviewer_id: str | None
    original_span: str
    normalized_text: str
    sentiment: str = "neutral"
    intensity: str = "none"
    scope: str = "unknown"
    property_status: str = "present"
    confidence: float = 0.75
    source: EvidenceSource = "review_qwen"
    human_verified: bool = False
    rating: float | None = None
    verified_purchase: bool | None = None

    def __post_init__(self) -> None:
        for name in ("claim_id", "product_id", "review_id", "original_span", "normalized_text"):
            if not str(getattr(self, name)).strip():
                raise ValueError(f"{name} must not be empty")
        _probability("confidence", self.confidence)
        if self.source not in {
            "review_qwen",
            "review_human_verified",
            "image_estimated",
            "metadata",
        }:
            raise ValueError(f"Unsupported tactile source: {self.source}")
        if self.rating is not None and not 0.0 <= float(self.rating) <= 5.0:
            raise ValueError("rating must be between 0 and 5")

    def public_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value.pop("reviewer_id", None)
        return value


@dataclass(frozen=True)
class TactileEvidence:
    product_id: str
    claim_id: str
    claim: str
    original_span: str
    review_id: str
    rating: float | None
    verified_purchase: bool | None
    confidence: float
    source: EvidenceSource

    def __post_init__(self) -> None:
        _probability("confidence", self.confidence)


@dataclass
class ProductTactileProfile:
    product_id: str
    title: str
    category: str
    claims: list[TactileClaim]
    representative_claims: list[dict[str, Any]]
    embedding_ref: int | None
    reviewer_count: int
    review_count: int
    claim_count: int
    evidence_strength: float
    source_breakdown: dict[str, int]
    status: Literal["available", "insufficient_evidence"] = "available"

    def __post_init__(self) -> None:
        _probability("evidence_strength", self.evidence_strength)
        if min(self.reviewer_count, self.review_count, self.claim_count) < 0:
            raise ValueError("Profile counts must be non-negative")

    def public_dict(self, *, include_claims: bool = True) -> dict[str, Any]:
        value = {
            "product_id": self.product_id,
            "title": self.title,
            "category": self.category,
            "representative_claims": self.representative_claims,
            "embedding_ref": self.embedding_ref,
            "reviewer_count": self.reviewer_count,
            "review_count": self.review_count,
            "claim_count": self.claim_count,
            "evidence_strength": self.evidence_strength,
            "source_breakdown": self.source_breakdown,
            "status": self.status,
        }
        if include_claims:
            value["claims"] = [claim.public_dict() for claim in self.claims]
        return value


@dataclass(frozen=True)
class TactileIntent:
    current_product_id: str | None = None
    category: str | None = None
    query_text: str | None = None
    desired_more: tuple[str, ...] = ()
    desired_less: tuple[str, ...] = ()
    avoid: tuple[str, ...] = ()
    must_have: tuple[str, ...] = ()
    source: IntentSource = "explicit_structured"
    confidence: float = 1.0

    def __post_init__(self) -> None:
        _probability("confidence", self.confidence)
        if self.source not in {
            "explicit_structured",
            "deterministic_nlp",
            "agent_context",
        }:
            raise ValueError(f"Unsupported intent source: {self.source}")

    def public_dict(self) -> dict[str, Any]:
        value = asdict(self)
        for name in ("desired_more", "desired_less", "avoid", "must_have"):
            value[name] = list(value[name])
        return value


@dataclass(frozen=True)
class RecommendationCandidate:
    product_id: str
    base_score: float
    tactile_score: float
    constraint_score: float
    confidence_score: float
    diversity_score: float
    final_score: float
    score_breakdown: dict[str, float] = field(default_factory=dict)
    reason: dict[str, Any] = field(default_factory=dict)

    def public_dict(self) -> dict[str, Any]:
        return asdict(self)

