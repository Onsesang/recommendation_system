from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict
from typing import Any

from .tactile_models import TactileClaim, TactileEvidence
from .tactile_normalization import ConceptMatch
from .tactile_store import TactileStore


DEFAULT_EVIDENCE_LIMIT = 3
MAX_PRODUCTS = 20
MAX_EVIDENCE_LIMIT = 10


def _validate_product_ids(product_ids: Sequence[str]) -> list[str]:
    if isinstance(product_ids, (str, bytes)) or not isinstance(product_ids, Sequence):
        raise ValueError("product_ids must be an array of product IDs")
    values = list(product_ids)
    if not 2 <= len(values) <= MAX_PRODUCTS:
        raise ValueError(f"product_ids must contain between 2 and {MAX_PRODUCTS} products")
    if any(not isinstance(value, str) or not value.strip() for value in values):
        raise ValueError("every product_id must be a non-empty string")
    normalized = [value.strip() for value in values]
    if len(set(normalized)) != len(normalized):
        raise ValueError("product_ids must not contain duplicates")
    return normalized


def _validate_evidence_limit(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("evidence_limit must be an integer")
    if not 1 <= value <= MAX_EVIDENCE_LIMIT:
        raise ValueError(f"evidence_limit must be between 1 and {MAX_EVIDENCE_LIMIT}")
    return value


def _evidence_dict(claim: TactileClaim) -> dict[str, Any]:
    """Build public, traceable evidence without exposing the reviewer identifier."""
    return asdict(
        TactileEvidence(
            product_id=claim.product_id,
            claim_id=claim.claim_id,
            claim=claim.normalized_text,
            original_span=claim.original_span,
            review_id=claim.review_id,
            rating=claim.rating,
            verified_purchase=claim.verified_purchase,
            confidence=claim.confidence,
            source=claim.source,
        )
    )


def _product_dimension(
    evidence: list[tuple[TactileClaim, ConceptMatch]], *, evidence_limit: int
) -> dict[str, Any]:
    if not evidence:
        return {
            "status": "insufficient_evidence",
            "summary": "insufficient_evidence",
            "direction": None,
            "confidence": None,
            "reviewer_count": 0,
            "evidence_count": 0,
            "evidence": [],
        }

    # A duplicated extraction from the same span must not increase support or appear twice.
    unique: dict[str, tuple[TactileClaim, ConceptMatch]] = {}
    for claim, match in evidence:
        unique.setdefault(claim.claim_id, (claim, match))
    rows = list(unique.values())
    directions = {match.direction for _, match in rows}
    reviewers = {claim.reviewer_id or claim.review_id for claim, _ in rows}
    reviews = {claim.review_id for claim, _ in rows}

    if directions == {1}:
        status = "supported"
        direction = "present"
    elif directions == {-1}:
        status = "contradicted"
        direction = "absent"
    else:
        status = "conflicting"
        direction = "conflicting"

    ranked = sorted(
        rows,
        key=lambda pair: (-pair[0].confidence, pair[0].claim_id),
    )
    representative_claim, representative_match = ranked[0]
    if status == "supported":
        summary = representative_match.label
    elif status == "contradicted":
        summary = f"not {representative_match.label}"
    else:
        summary = "conflicting_evidence"

    # This is the mean confidence of actual supporting/contradicting claims, not an
    # inferred tactile intensity or an invented "medium" value.
    confidence = sum(claim.confidence for claim, _ in rows) / len(rows)
    return {
        "status": status,
        "summary": summary,
        "direction": direction,
        "confidence": round(confidence, 6),
        "reviewer_count": len(reviewers),
        "evidence_count": len(reviews),
        "evidence": [_evidence_dict(claim) for claim, _ in ranked[:evidence_limit]],
    }


def _classifications(product_values: Mapping[str, Mapping[str, Any]]) -> list[str]:
    statuses = [str(value["status"]) for value in product_values.values()]
    observed = [status for status in statuses if status != "insufficient_evidence"]
    missing = len(observed) != len(statuses)
    directions = {
        str(value["direction"])
        for value in product_values.values()
        if value["direction"] in {"present", "absent"}
    }
    has_conflict = "conflicting" in observed or directions == {"present", "absent"}

    categories: list[str] = []
    if not missing and not has_conflict and len(set(observed)) == 1:
        categories.append("common")
    if len(set(statuses)) > 1:
        categories.append("different")
    if missing and observed:
        categories.append("one_sided")
    if has_conflict:
        categories.append("conflicting")
    return categories


class TactileComparisonService:
    """Deterministic, review-grounded tactile comparison over a ``TactileStore``."""

    def __init__(self, store: TactileStore) -> None:
        self.store = store

    def compare_request(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        """Validate a JSON-like POST body and compare its products."""
        if not isinstance(payload, Mapping):
            raise ValueError("request body must be an object")
        if "product_ids" not in payload:
            raise ValueError("product_ids is required")
        return self.compare(
            payload["product_ids"],
            evidence_limit=payload.get("evidence_limit", DEFAULT_EVIDENCE_LIMIT),
        )

    def compare(
        self,
        product_ids: Sequence[str],
        *,
        evidence_limit: int = DEFAULT_EVIDENCE_LIMIT,
    ) -> dict[str, Any]:
        self.store.require_feature("tactile_comparison")
        products = _validate_product_ids(product_ids)
        limit = _validate_evidence_limit(evidence_limit)

        unknown = [
            product_id
            for product_id in products
            if product_id not in self.store.product_metadata
        ]
        if unknown:
            raise KeyError(f"Unknown product_id: {unknown[0]}")

        concept_by_product = {
            product_id: self.store.concepts(product_id) for product_id in products
        }
        concepts = sorted(
            {
                concept
                for grouped in concept_by_product.values()
                for concept in grouped
            }
        )
        dimensions: list[dict[str, Any]] = []
        groups: dict[str, list[str]] = {
            "common": [],
            "different": [],
            "one_sided": [],
            "conflicting": [],
        }
        insufficient: dict[str, list[str]] = {}

        for concept in concepts:
            values = {
                product_id: _product_dimension(
                    concept_by_product[product_id].get(concept, []),
                    evidence_limit=limit,
                )
                for product_id in products
            }
            categories = _classifications(values)
            for category in categories:
                groups[category].append(concept)
            absent_products = [
                product_id
                for product_id, value in values.items()
                if value["status"] == "insufficient_evidence"
            ]
            if absent_products:
                insufficient[concept] = absent_products
            dimensions.append(
                {
                    "concept": concept,
                    "classifications": categories,
                    "products": values,
                }
            )

        product_status = {
            product_id: (
                "available"
                if self.store.claims_by_asin.get(product_id)
                else "insufficient_evidence"
            )
            for product_id in products
        }
        return {
            "status": "available" if dimensions else "insufficient_evidence",
            "products": products,
            "product_evidence_status": product_status,
            "dimensions": dimensions,
            "groups": groups,
            "insufficient_evidence": insufficient,
            "evidence_policy": {
                "source": "review_claims",
                "max_evidence_per_product_dimension": limit,
                "missing_value": "insufficient_evidence",
            },
        }


def compare_products(
    store: TactileStore,
    product_ids: Sequence[str],
    *,
    evidence_limit: int = DEFAULT_EVIDENCE_LIMIT,
) -> dict[str, Any]:
    """Convenience entry point suitable for an HTTP POST handler."""
    return TactileComparisonService(store).compare(
        product_ids, evidence_limit=evidence_limit
    )
