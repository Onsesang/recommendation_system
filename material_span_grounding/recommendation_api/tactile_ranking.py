from __future__ import annotations

import math
from collections import defaultdict
from typing import Any, Iterable

import numpy as np

from .tactile_models import RecommendationCandidate, TactileIntent
from .tactile_normalization import canonical_concept
from .tactile_store import TactileStore


RANKING_STRATEGIES = {
    "baseline",
    "global_history",
    "category_conditioned",
    "context_gated",
}


def _minmax(values: np.ndarray) -> np.ndarray:
    if not len(values):
        return values
    low = float(values.min())
    high = float(values.max())
    if high - low <= 1e-12:
        return np.full_like(values, 0.5, dtype=np.float32)
    return ((values - low) / (high - low)).astype(np.float32)


def _cosine01(left: np.ndarray, right: np.ndarray) -> float:
    denominator = float(np.linalg.norm(left) * np.linalg.norm(right))
    if denominator <= 1e-12:
        return 0.0
    return min(1.0, max(0.0, (float(left @ right) / denominator + 1.0) / 2.0))


class TactileRankingService:
    """Context-gated tactile ranking over the immutable TactileStore catalog."""

    def __init__(self, store: TactileStore) -> None:
        self.store = store
        self.ranking_config = dict(store.config["ranking"])
        self.alternative_config = dict(store.config["alternative"])

    def concept_signal(self, asin: str, concept_value: str) -> dict[str, Any] | None:
        concept = canonical_concept(concept_value)
        evidence = self.store.concepts(asin).get(concept, [])
        if not evidence:
            return None
        by_reviewer: dict[str, list[float]] = defaultdict(list)
        confidence_by_reviewer: dict[str, list[float]] = defaultdict(list)
        public_evidence: dict[str, dict[str, Any]] = {}
        for claim, match in evidence:
            reviewer = claim.reviewer_id or claim.review_id
            by_reviewer[reviewer].append(float(match.direction) * claim.confidence)
            confidence_by_reviewer[reviewer].append(claim.confidence)
            public_evidence.setdefault(claim.claim_id, claim.public_dict())
        reviewer_scores = [float(np.mean(values)) for values in by_reviewer.values()]
        reviewer_confidence = [
            float(np.mean(confidence_by_reviewer[reviewer])) for reviewer in by_reviewer
        ]
        return {
            "concept": concept,
            "score": float(np.mean(reviewer_scores)),
            "confidence": float(np.mean(reviewer_confidence)),
            "reviewer_count": len(by_reviewer),
            "evidence": list(public_evidence.values()),
        }

    def _mmr(self, rows: list[dict[str, Any]], top_k: int) -> list[dict[str, Any]]:
        relevance = float(self.ranking_config["mmr_relevance"])
        remaining = list(rows)
        selected: list[dict[str, Any]] = []
        while remaining and len(selected) < top_k:
            best_index = 0
            best_key = (-math.inf, "")
            for index, row in enumerate(remaining):
                vector = self.store.vector(row["product_id"])
                similarities = []
                if vector is not None:
                    for chosen in selected:
                        chosen_vector = self.store.vector(chosen["product_id"])
                        if chosen_vector is not None:
                            similarities.append(_cosine01(vector, chosen_vector))
                redundancy = max(similarities, default=0.0)
                selection_score = relevance * row["pre_mmr_score"] - (1.0 - relevance) * redundancy
                key = (selection_score, row["product_id"])
                if key > best_key:
                    best_key = key
                    best_index = index
                row["_candidate_diversity"] = 1.0 - redundancy
                row["_candidate_selection"] = selection_score
            chosen = remaining.pop(best_index)
            chosen["diversity_score"] = float(chosen.pop("_candidate_diversity"))
            chosen["selection_score"] = float(chosen.pop("_candidate_selection"))
            selected.append(chosen)
        for row in selected:
            row.pop("_candidate_diversity", None)
            row.pop("_candidate_selection", None)
        return selected

    def alternatives(
        self,
        *,
        anchor_product_id: str,
        direction: str,
        tactile_concept: str,
        top_k: int = 10,
    ) -> dict[str, Any]:
        self.store.require_feature("tactile_alternative")
        if direction not in {"more", "less"}:
            raise ValueError("direction must be more or less")
        if not 1 <= int(top_k) <= 50:
            raise ValueError("top_k must be between 1 and 50")
        if anchor_product_id not in self.store.product_metadata:
            raise KeyError(f"Unknown ASIN: {anchor_product_id}")
        concept = canonical_concept(tactile_concept)
        if concept.startswith("open:"):
            raise ValueError("tactile_concept must map to a supported presentation concept")
        anchor_meta = self.store.product_metadata[anchor_product_id]
        anchor_vector = self.store.vector(anchor_product_id)
        anchor_signal = self.concept_signal(anchor_product_id, concept)
        sign = 1.0 if direction == "more" else -1.0
        cfg = self.alternative_config
        rows = []
        for asin, meta in self.store.product_metadata.items():
            if asin == anchor_product_id or meta["category"] != anchor_meta["category"]:
                continue
            candidate_vector = self.store.vector(asin)
            signal = self.concept_signal(asin, concept)
            if candidate_vector is None or signal is None:
                continue
            if anchor_signal is None:
                raw_direction = sign * float(signal["score"])
            else:
                raw_direction = sign * (
                    float(signal["score"]) - float(anchor_signal["score"])
                )
            if raw_direction <= float(cfg["minimum_directional_support"]):
                continue
            directional = min(1.0, raw_direction / 2.0 if anchor_signal else raw_direction)
            anchor_similarity = (
                _cosine01(anchor_vector, candidate_vector)
                if anchor_vector is not None
                else 0.0
            )
            confidence = min(
                1.0,
                float(signal["confidence"])
                * (1.0 - math.exp(-float(signal["reviewer_count"]) / 3.0)),
            )
            constraint = 1.0
            final = (
                float(cfg["anchor_weight"]) * anchor_similarity
                + float(cfg["direction_weight"]) * directional
                + float(cfg["confidence_weight"]) * confidence
                + float(cfg["constraint_weight"]) * constraint
            )
            rows.append(
                {
                    "product_id": asin,
                    "title": meta["title"],
                    "category": meta["category"],
                    "anchor_similarity": anchor_similarity,
                    "tactile_improvement": directional,
                    "evidence_confidence": confidence,
                    "constraint_score": constraint,
                    "pre_mmr_score": final,
                    "score_breakdown": {
                        "anchor_similarity": anchor_similarity,
                        "tactile_improvement": directional,
                        "evidence_confidence": confidence,
                        "same_category": constraint,
                        "weighted_pre_mmr": final,
                    },
                    "reason": {
                        "preserved": ["same category", "similar review-derived tactile profile"],
                        "improved": [f"{direction} {concept}"],
                        "evidence": signal["evidence"][:3],
                    },
                }
            )
        rows.sort(key=lambda row: (-row["pre_mmr_score"], row["product_id"]))
        selected = self._mmr(rows, int(top_k))
        results = []
        for rank, row in enumerate(selected, 1):
            final = row.pop("pre_mmr_score")
            row["rank"] = rank
            row["final_score"] = final
            row["score_breakdown"]["diversity_score"] = row["diversity_score"]
            row["score_breakdown"]["mmr_selection_score"] = row.pop("selection_score")
            results.append(row)
        message = None
        if not results:
            message = "조건을 만족하는 충분한 review evidence가 있는 상품을 찾지 못했습니다."
        return {
            "anchor_product_id": anchor_product_id,
            "requested_change": {"direction": direction, "concept": concept},
            "anchor_evidence_status": "available" if anchor_signal else "insufficient_evidence",
            "comparison_claim_allowed": anchor_signal is not None,
            "count": len(results),
            "results": results,
            "message": message,
            "warning": (
                "Anchor similarity uses review-derived tactile target similarity; aligned image "
                "features are not present in the 495-product artifact."
            ),
        }

    def _history_profile(
        self, history: Iterable[str], *, category: str | None = None
    ) -> np.ndarray | None:
        vectors = []
        for asin in history:
            meta = self.store.product_metadata.get(asin)
            if meta is None or (category is not None and meta["category"] != category):
                continue
            vector = self.store.vector(asin)
            if vector is not None:
                vectors.append(vector)
        if not vectors:
            return None
        profile = np.mean(np.stack(vectors), axis=0)
        norm = float(np.linalg.norm(profile))
        return profile / max(norm, 1e-12)

    def _explicit_candidate_score(
        self, asin: str, intent: TactileIntent
    ) -> tuple[float, float, list[str], list[dict[str, Any]]]:
        requests = [
            *[(value, 1.0, "more") for value in intent.desired_more],
            *[(value, -1.0, "less") for value in intent.desired_less],
            *[(value, -1.0, "avoid") for value in intent.avoid],
            *[(value, 1.0, "must_have") for value in intent.must_have],
        ]
        if not requests:
            return 0.0, 0.0, [], []
        aligned = []
        conflicts = []
        reasons = []
        grounded_evidence: list[dict[str, Any]] = []
        for value, sign, kind in requests:
            signal = self.concept_signal(asin, value)
            if signal is None:
                if kind == "must_have":
                    conflicts.append(1.0)
                continue
            score = sign * float(signal["score"])
            aligned.append(score)
            if score < 0:
                conflicts.append(-score)
            if score > 0:
                reasons.append(f"{kind}:{signal['concept']}")
                for evidence in signal["evidence"]:
                    if evidence["claim_id"] not in {
                        row["claim_id"] for row in grounded_evidence
                    }:
                        grounded_evidence.append(evidence)
        return (
            float(np.mean(aligned)) if aligned else 0.0,
            float(np.mean(conflicts)) if conflicts else 0.0,
            reasons,
            grounded_evidence[:5],
        )

    def rerank(
        self,
        *,
        candidates: list[dict[str, Any]],
        strategy: str = "baseline",
        history_product_ids: list[str] | None = None,
        intent: TactileIntent | None = None,
        top_k: int = 10,
    ) -> dict[str, Any]:
        self.store.require_feature("tactile_reranking")
        if strategy not in RANKING_STRATEGIES:
            raise ValueError(f"strategy must be one of {sorted(RANKING_STRATEGIES)}")
        if not 1 <= int(top_k) <= 500:
            raise ValueError("top_k must be between 1 and 500")
        if not candidates:
            return {"strategy": strategy, "count": 0, "results": []}
        seen: set[str] = set()
        for row in candidates:
            asin = str(row.get("product_id") or "")
            if asin not in self.store.product_metadata:
                raise KeyError(f"Unknown ASIN: {asin}")
            if asin in seen:
                raise ValueError("candidate product IDs must be unique")
            seen.add(asin)
            if not math.isfinite(float(row.get("base_score", math.nan))):
                raise ValueError("base_score must be finite")
        history = list(history_product_ids or [])
        intent = intent or TactileIntent()
        category = intent.category
        global_profile = self._history_profile(history)
        category_profile = self._history_profile(history, category=category) if category else None
        base_values = _minmax(
            np.asarray([float(row["base_score"]) for row in candidates], dtype=np.float32)
        )
        cfg = self.ranking_config
        prepared = []
        explicit = bool(
            intent.desired_more or intent.desired_less or intent.avoid or intent.must_have
        )
        for row, base_score in zip(candidates, base_values):
            asin = str(row["product_id"])
            meta = self.store.product_metadata[asin]
            vector = self.store.vector(asin)
            tactile_raw = 0.0
            conflict = 0.0
            reasons: list[str] = []
            if strategy == "baseline":
                gate = 0.0
            elif strategy == "global_history":
                gate = float(cfg["global_history_gate"])
                tactile_raw = _cosine01(global_profile, vector) * 2.0 - 1.0 if global_profile is not None and vector is not None else 0.0
            elif strategy == "category_conditioned":
                same_category = category is not None and meta["category"] == category
                gate = float(cfg["same_category_gate"] if same_category else cfg["cross_category_gate"])
                profile = category_profile if same_category else global_profile
                tactile_raw = _cosine01(profile, vector) * 2.0 - 1.0 if profile is not None and vector is not None else 0.0
            else:
                same_category = category is None or meta["category"] == category
                gate = float(cfg["explicit_gate"] if explicit and same_category else cfg["cross_category_gate"] if explicit else 0.0)
                tactile_raw, conflict, reasons, grounded_evidence = self._explicit_candidate_score(
                    asin, intent
                )
            if strategy != "context_gated":
                grounded_evidence = []
            tactile_scaled = (tactile_raw + 1.0) / 2.0 if gate > 0 else 0.0
            profile = self.store._profile_cache[asin]
            confidence = float(profile.evidence_strength)
            constraint = 1.0 - conflict
            final = (
                float(cfg["base_weight"]) * float(base_score)
                + gate * float(cfg["tactile_weight"]) * tactile_scaled
                + gate * float(cfg["confidence_weight"]) * confidence
                + gate * float(cfg["constraint_weight"]) * constraint
                - gate * float(cfg["conflict_weight"]) * conflict
            )
            candidate = RecommendationCandidate(
                product_id=asin,
                base_score=float(base_score),
                tactile_score=tactile_raw,
                constraint_score=constraint,
                confidence_score=confidence,
                diversity_score=0.0,
                final_score=final,
                score_breakdown={
                    "input_base_score": float(row["base_score"]),
                    "normalized_base_score": float(base_score),
                    "tactile_score": tactile_raw,
                    "tactile_gate": gate,
                    "confidence_score": confidence,
                    "conflict_penalty": conflict,
                    "weighted_pre_mmr": final,
                },
                reason={
                    "matched_constraints": reasons,
                    "evidence": grounded_evidence,
                },
            ).public_dict()
            candidate["title"] = meta["title"]
            candidate["category"] = meta["category"]
            candidate["pre_mmr_score"] = candidate.pop("final_score")
            prepared.append(candidate)
        prepared.sort(key=lambda row: (-row["pre_mmr_score"], row["product_id"]))
        if strategy == "baseline":
            selected = prepared[: min(int(top_k), len(prepared))]
            for row in selected:
                row["diversity_score"] = 0.0
                row["selection_score"] = row["pre_mmr_score"]
        else:
            selected = self._mmr(prepared, min(int(top_k), len(prepared)))
        results = []
        for rank, row in enumerate(selected, 1):
            final = float(row.pop("pre_mmr_score"))
            row["rank"] = rank
            row["final_score"] = final
            row["score_breakdown"]["diversity_score"] = row["diversity_score"]
            row["score_breakdown"]["mmr_selection_score"] = row.pop("selection_score")
            results.append(row)
        return {
            "strategy": strategy,
            "tactile_gate_contract": {
                "explicit": cfg["explicit_gate"],
                "same_category_history": cfg["same_category_gate"],
                "global_history": cfg["global_history_gate"],
                "cross_category": cfg["cross_category_gate"],
            },
            "count": len(results),
            "results": results,
            "warning": (
                "global_history is a research ablation; purchase history is not proof that every "
                "tactile attribute was preferred."
            ),
        }
