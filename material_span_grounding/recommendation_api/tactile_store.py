from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import numpy as np

from material_span.common import read_jsonl, sha256_file
from material_span.simple_m0_m1 import SEOYOUNG_TRAIN, infer_category

from .tactile_models import ProductTactileProfile, TactileClaim
from .tactile_normalization import ConceptMatch, concept_matches


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TARGET_ROOT = ROOT / "data/derived/dense_500_v2_1_targets"
DEFAULT_VERIFICATION_ROOT = ROOT / "data/vllm/dense_500/v2_1_ai_recall"
DEFAULT_SOURCE_REVIEWS = ROOT / "data/dense/reviews_product_dense.jsonl"
DEFAULT_CONFIG = ROOT / "configs/tactile_ranking.json"


def _read_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def _claim_confidence(row: dict[str, Any]) -> float:
    score = 0.78
    score += {
        "direct_touch": 0.12,
        "worn_experience": 0.10,
        "product_behavior": 0.06,
        "visual_only": -0.08,
        "unspecified": 0.0,
    }.get(str(row.get("evidence_basis")), 0.0)
    score += {"strong": 0.03, "moderate": 0.02, "slight": -0.02}.get(
        str(row.get("intensity")), 0.0
    )
    score += {"uncertain": -0.25, "comparative": -0.06}.get(
        str(row.get("property_status")), 0.0
    )
    return min(0.97, max(0.25, score))


class TactileStore:
    """Validated in-memory cache over review-grounded v2.1 tactile artifacts."""

    def __init__(
        self,
        *,
        target_root: Path = DEFAULT_TARGET_ROOT,
        verification_root: Path = DEFAULT_VERIFICATION_ROOT,
        source_reviews_path: Path = DEFAULT_SOURCE_REVIEWS,
        metadata_path: Path = SEOYOUNG_TRAIN,
        config_path: Path = DEFAULT_CONFIG,
    ) -> None:
        self.target_root = Path(target_root)
        self.verification_root = Path(verification_root)
        self.source_reviews_path = Path(source_reviews_path)
        self.config = _read_json(Path(config_path))
        self.feature_flags = dict(self.config["feature_flags"])

        manifest = _read_json(self.target_root / "manifest.json")
        if manifest.get("status") != "complete":
            raise ValueError("Tactile target manifest is not complete")
        self.manifest = manifest
        products = _read_json(self.target_root / "products.json")
        vectors_path = self.target_root / "product_material_targets.npz"
        with np.load(vectors_path, allow_pickle=False) as arrays:
            asins = [str(value) for value in arrays["asins"]]
            vectors = np.asarray(arrays["material"], dtype=np.float32)
        product_asins = [str(row["asin"]) for row in products]
        if asins != product_asins or vectors.shape != (len(asins), 384):
            raise ValueError("Tactile product metadata/vector contract mismatch")
        if not np.isfinite(vectors).all():
            raise ValueError("Tactile vectors contain non-finite values")
        if not np.allclose(np.linalg.norm(vectors, axis=1), 1.0, atol=1e-5):
            raise ValueError("Tactile vectors must be L2-normalized")
        expected_vector_hash = manifest.get("outputs", {}).get("vectors_sha256")
        if expected_vector_hash and sha256_file(vectors_path) != expected_vector_hash:
            raise ValueError("Tactile vectors SHA-256 does not match manifest")

        self.target_asins = asins
        self.target_vectors = vectors
        self.target_index = {asin: index for index, asin in enumerate(asins)}
        self.target_product_by_asin = {str(row["asin"]): row for row in products}

        reviews = read_jsonl(self.source_reviews_path)
        self.review_by_id = {str(row["review_id"]): row for row in reviews}
        self.source_asins = sorted({str(row["asin"]) for row in reviews})
        metadata = {str(row["asin"]): row for row in _read_json(Path(metadata_path))}
        self.product_metadata: dict[str, dict[str, Any]] = {}
        for asin in self.source_asins:
            target_product = self.target_product_by_asin.get(asin, {})
            source_meta = metadata.get(asin, {})
            title = str(target_product.get("title") or source_meta.get("title") or "")
            self.product_metadata[asin] = {
                "product_id": asin,
                "title": title,
                "category": str(target_product.get("category") or infer_category(title)),
                "image_url": f"/images/{asin}.jpg",
            }

        run = _read_json(self.verification_root / "verification_run.json")
        verification_path = self.verification_root / "semantic_verifications.jsonl"
        if run.get("status") != "complete" or sha256_file(verification_path) != run.get(
            "output_sha256"
        ):
            raise ValueError("Semantic verification provenance is incomplete or changed")
        rows = read_jsonl(verification_path)
        accepted = [row for row in rows if row.get("status") == "success" and row.get("accepted")]
        if len(accepted) != int(run["accepted"]):
            raise ValueError("Accepted tactile claim count does not match verification manifest")

        self.claims_by_asin: dict[str, list[TactileClaim]] = defaultdict(list)
        for row in accepted:
            review = self.review_by_id.get(str(row["review_id"]), {})
            claim = TactileClaim(
                claim_id=str(row["span_id"]),
                product_id=str(row["asin"]),
                review_id=str(row["review_id"]),
                reviewer_id=str(row.get("user_id") or review.get("user_id") or "") or None,
                original_span=str(row["quote"]),
                normalized_text=str(row.get("claim") or row["quote"]),
                sentiment=str(row.get("sentiment") or "neutral"),
                intensity=str(row.get("intensity") or "none"),
                scope=str(row.get("scope") or "unknown"),
                property_status=str(row.get("property_status") or "present"),
                confidence=_claim_confidence(row),
                source="review_qwen",
                human_verified=False,
                rating=float(review["rating"]) if review.get("rating") is not None else None,
                verified_purchase=(
                    bool(review["verified_purchase"])
                    if review.get("verified_purchase") is not None
                    else None
                ),
            )
            self.claims_by_asin[claim.product_id].append(claim)

        self._concept_cache: dict[str, dict[str, list[tuple[TactileClaim, ConceptMatch]]]] = {}
        self._profile_cache = {
            asin: self._build_profile(asin) for asin in self.source_asins
        }

    def require_feature(self, name: str) -> None:
        if not self.feature_flags.get(name, False):
            raise LookupError(f"Feature disabled: {name}")

    def vector(self, asin: str) -> np.ndarray | None:
        index = self.target_index.get(asin)
        return None if index is None else self.target_vectors[index]

    def concepts(self, asin: str) -> dict[str, list[tuple[TactileClaim, ConceptMatch]]]:
        if asin not in self.product_metadata:
            raise KeyError(f"Unknown ASIN: {asin}")
        if asin not in self._concept_cache:
            grouped: dict[str, list[tuple[TactileClaim, ConceptMatch]]] = defaultdict(list)
            for claim in self.claims_by_asin.get(asin, []):
                for match in concept_matches(
                    claim.normalized_text, property_status=claim.property_status
                ):
                    grouped[match.concept].append((claim, match))
            self._concept_cache[asin] = dict(grouped)
        return self._concept_cache[asin]

    def _representative_claims(self, asin: str) -> list[dict[str, Any]]:
        rows = []
        for concept, evidence in self.concepts(asin).items():
            reviewers = {claim.reviewer_id or claim.review_id for claim, _ in evidence}
            sentiments = Counter(claim.sentiment for claim, _ in evidence)
            directions = Counter(match.direction for _, match in evidence)
            best = sorted(
                evidence,
                key=lambda pair: (-pair[0].confidence, pair[0].claim_id),
            )[0]
            rows.append(
                {
                    "concept": concept,
                    "label": best[1].label,
                    "open_vocabulary": best[1].open_vocabulary,
                    "reviewer_count": len(reviewers),
                    "evidence_count": len({claim.review_id for claim, _ in evidence}),
                    "mean_confidence": sum(claim.confidence for claim, _ in evidence) / len(evidence),
                    "sentiment_distribution": dict(sorted(sentiments.items())),
                    "direction_distribution": {
                        "present": directions[1],
                        "absent": directions[-1],
                    },
                    "representative_evidence": [best[0].public_dict()],
                }
            )
        rows.sort(
            key=lambda row: (
                -row["reviewer_count"],
                -row["evidence_count"],
                row["concept"],
            )
        )
        return rows[: int(self.config["profile"]["representative_claims"])]

    def _build_profile(self, asin: str) -> ProductTactileProfile:
        meta = self.product_metadata[asin]
        claims = self.claims_by_asin.get(asin, [])
        reviewers = {claim.reviewer_id or claim.review_id for claim in claims}
        reviews = {claim.review_id for claim in claims}
        sources = Counter(claim.source for claim in claims)
        if claims:
            support = 1.0 - math.exp(-len(reviewers) / 3.0)
            mean_confidence = sum(claim.confidence for claim in claims) / len(claims)
            evidence_strength = min(1.0, support * mean_confidence)
            status = "available"
        else:
            evidence_strength = 0.0
            status = "insufficient_evidence"
        return ProductTactileProfile(
            product_id=asin,
            title=meta["title"],
            category=meta["category"],
            claims=list(claims),
            representative_claims=self._representative_claims(asin) if claims else [],
            embedding_ref=self.target_index.get(asin),
            reviewer_count=len(reviewers),
            review_count=len(reviews),
            claim_count=len(claims),
            evidence_strength=evidence_strength,
            source_breakdown=dict(sorted(sources.items())),
            status=status,
        )

    def profile(self, asin: str, *, include_claims: bool = True) -> dict[str, Any]:
        if asin not in self._profile_cache:
            raise KeyError(f"Unknown ASIN: {asin}")
        return self._profile_cache[asin].public_dict(include_claims=include_claims)

    def list_products(self, *, offset: int = 0, limit: int = 50) -> dict[str, Any]:
        if offset < 0 or not 1 <= limit <= 200:
            raise ValueError("offset must be non-negative and limit must be between 1 and 200")
        selected = self.source_asins[offset : offset + limit]
        return {
            "total": len(self.source_asins),
            "offset": offset,
            "limit": limit,
            "items": [
                {
                    **self.product_metadata[asin],
                    "tactile_status": self._profile_cache[asin].status,
                    "reviewer_count": self._profile_cache[asin].reviewer_count,
                    "claim_count": self._profile_cache[asin].claim_count,
                }
                for asin in selected
            ],
        }

    def health(self) -> dict[str, Any]:
        available = sum(profile.status == "available" for profile in self._profile_cache.values())
        return {
            "status": "ok",
            "service": "tactile-backend",
            "source_products": len(self.source_asins),
            "profile_products": available,
            "insufficient_evidence_products": len(self.source_asins) - available,
            "accepted_claims": sum(len(rows) for rows in self.claims_by_asin.values()),
            "target_dimension": int(self.target_vectors.shape[1]),
            "feature_flags": self.feature_flags,
            "request_time_llm": False,
            "label_source": self.manifest.get("label_source"),
        }

