from __future__ import annotations

import hashlib
import json
import math
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np

from .store import DEFAULT_IMAGE_ROOT, DEFAULT_PRODUCTS, DEFAULT_VECTORS, _normalize
from .multimodal_index import DEFAULT_MULTIMODAL_ROOT, MultimodalProductIndex
from .tactile_agent import parse_tactile_intent
from .tactile_ranking import TactileRankingService
from .tactile_store import TactileStore


_TOKEN = re.compile(r"[a-z0-9]+")
_STOPWORDS = {
    "a",
    "an",
    "and",
    "for",
    "of",
    "the",
    "to",
    "with",
    "women",
    "womens",
    "men",
    "mens",
    "girls",
    "boys",
}


def _tokens(value: str) -> set[str]:
    return {
        token
        for token in _TOKEN.findall(value.casefold().replace("'", ""))
        if len(token) > 1 and token not in _STOPWORDS
    }


def _normalized_title(value: str) -> tuple[str, ...]:
    """Keep word order while ignoring punctuation/case for product identity."""
    return tuple(_TOKEN.findall(value.casefold().replace("'", "")))


def _jaccard(left: set[str], right: set[str]) -> float:
    return len(left & right) / len(left | right) if left and right else 0.0


def _page(value: Any, name: str, *, maximum: int | None = None) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be an integer")
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if number < 1 or (maximum is not None and number > maximum):
        suffix = f" between 1 and {maximum}" if maximum is not None else " positive"
        raise ValueError(f"{name} must be{suffix}")
    return number


class TactileCatalogService:
    """Catalog pagination, natural-language discovery, and related-product retrieval."""

    def __init__(
        self,
        store: TactileStore,
        *,
        legacy_products_path: Path = DEFAULT_PRODUCTS,
        legacy_vectors_path: Path = DEFAULT_VECTORS,
        image_root: Path = DEFAULT_IMAGE_ROOT,
        multimodal_root: Path = DEFAULT_MULTIMODAL_ROOT,
    ) -> None:
        self.store = store
        self.ranking = TactileRankingService(store)
        self.multimodal: MultimodalProductIndex | None = None
        self._title_tokens = {
            asin: _tokens(meta["title"]) for asin, meta in store.product_metadata.items()
        }
        self._visual_by_asin: dict[str, np.ndarray] = {}
        self._visual_method = "unavailable"
        self._identity_by_asin = self._build_product_identities(Path(image_root))
        self.catalog_asins = self._deduplicate(self.store.source_asins)
        multimodal_root = Path(multimodal_root)
        stage2_path = multimodal_root / "stage2_manifest.json"
        master_path = multimodal_root / "product_master.json"
        if stage2_path.is_file() and master_path.is_file():
            self.multimodal = MultimodalProductIndex(multimodal_root)
            stage2 = json.loads(stage2_path.read_text(encoding="utf-8"))
            # Resolve beside the manifest; its absolute path belongs to the build machine.
            vectors_path = multimodal_root / Path(stage2["outputs"]["vectors"]).name
            if vectors_path.is_file():
                with np.load(vectors_path, allow_pickle=False) as arrays:
                    design_asins = [str(value) for value in arrays["asins"]]
                    design_vectors = _normalize(np.asarray(arrays["image"], dtype=np.float32))
                vector_by_representative = dict(zip(design_asins, design_vectors))
                for row in json.loads(master_path.read_text(encoding="utf-8")):
                    vector = vector_by_representative.get(str(row["product_id"]))
                    if vector is None:
                        continue
                    for asin in row.get("alias_product_ids", [row["product_id"]]):
                        if str(asin) in store.product_metadata:
                            self._visual_by_asin[str(asin)] = vector
                self._visual_method = "fashionclip_full_catalog"
                self.catalog_asins = list(self.multimodal.product_ids)
                self.product_metadata = {
                    product_id: {
                        "product_id": product_id,
                        "title": str(row["title"]),
                        "category": str(row["category"]),
                        "image_url": str(row["image_url"]),
                    }
                    for product_id, row in self.multimodal.product_by_id.items()
                }
                self._title_tokens = {
                    product_id: _tokens(row["title"])
                    for product_id, row in self.product_metadata.items()
                }
                self._identity_by_asin = dict(self.multimodal.canonical_by_id)
        if not hasattr(self, "product_metadata"):
            self.product_metadata = self.store.product_metadata
        products_path = Path(legacy_products_path)
        vectors_path = Path(legacy_vectors_path)
        if not self._visual_by_asin and products_path.is_file() and vectors_path.is_file():
            with np.load(vectors_path, allow_pickle=False) as arrays:
                legacy_asins = [str(value) for value in arrays["asins"]]
                images = _normalize(np.asarray(arrays["image"], dtype=np.float32))
            self._visual_by_asin = {
                asin: images[index]
                for index, asin in enumerate(legacy_asins)
                if asin in store.product_metadata
            }
            self._visual_method = "legacy_qwen_partial_catalog"

    def _build_product_identities(self, image_root: Path) -> dict[str, str]:
        """Group duplicate records without collapsing unrelated placeholder images."""
        asins = self.store.source_asins
        parent = {asin: asin for asin in asins}

        def find(asin: str) -> str:
            while parent[asin] != asin:
                parent[asin] = parent[parent[asin]]
                asin = parent[asin]
            return asin

        def union(left: str, right: str) -> None:
            left_root, right_root = find(left), find(right)
            if left_root != right_root:
                parent[max(left_root, right_root)] = min(left_root, right_root)

        by_title: dict[tuple[str, ...], list[str]] = defaultdict(list)
        by_image: dict[str, list[str]] = defaultdict(list)
        for asin in asins:
            title = self.store.product_metadata[asin]["title"]
            title_key = _normalized_title(title)
            if title_key:
                by_title[title_key].append(asin)
            image_path = image_root / f"{asin}.jpg"
            if image_path.is_file():
                by_image[hashlib.sha256(image_path.read_bytes()).hexdigest()].append(asin)

        for members in by_title.values():
            for asin in members[1:]:
                union(members[0], asin)

        # Exact duplicate images can be a shared placeholder. Require the same inferred
        # category and meaningful title overlap before treating different titles as one item.
        for members in by_image.values():
            for index, left in enumerate(members):
                left_meta = self.store.product_metadata[left]
                for right in members[index + 1 :]:
                    right_meta = self.store.product_metadata[right]
                    if (
                        left_meta["category"] == right_meta["category"]
                        and _jaccard(self._title_tokens[left], self._title_tokens[right]) >= 0.4
                    ):
                        union(left, right)

        return {asin: find(asin) for asin in asins}

    def _deduplicate(self, asins: list[str]) -> list[str]:
        """Keep the first/highest-ranked record from each visible product family."""
        seen: set[str] = set()
        result: list[str] = []
        for asin in asins:
            identity = self._identity_by_asin[asin]
            if identity not in seen:
                seen.add(identity)
                result.append(asin)
        return result

    def _public_product(
        self, asin: str, *, rank: int | None = None, extra: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        profile = self.store._profile_cache.get(asin)
        value = {
            **self.product_metadata[asin],
            "tactile_status": (
                profile.status if profile is not None else "image_predicted"
            ),
            "reviewer_count": profile.reviewer_count if profile is not None else 0,
            "claim_count": profile.claim_count if profile is not None else 0,
        }
        if self.multimodal is not None:
            value.update(self.multimodal.target_info(asin))
        if rank is not None:
            value["rank"] = rank
        if extra:
            value.update(extra)
        return value

    def multimodal_health(self) -> dict[str, Any]:
        if self.multimodal is None:
            return {"status": "unavailable"}
        source_counts: dict[str, int] = defaultdict(int)
        for source in self.multimodal.source:
            source_counts[source] += 1
        return {
            "status": "ok",
            "service": "multimodal-product-index",
            "catalog_products": len(self.multimodal.product_ids),
            "design_embedding": {
                "model": "patrickjohncyh/fashion-clip",
                "dimension": int(self.multimodal.image.shape[1]),
                "coverage": 1.0,
            },
            "tactile_target": {
                "model": "ridge",
                "dimension": int(self.multimodal.hybrid_tactile.shape[1]),
                "source_counts": dict(sorted(source_counts.items())),
            },
            "weights": self.store.config["related"],
        }

    def multimodal_evaluation(self) -> dict[str, Any]:
        if self.multimodal is None:
            raise LookupError("Multimodal index is unavailable")
        return json.loads(
            (self.multimodal.root / "coldstart_evaluation.json").read_text(encoding="utf-8")
        )

    def _paginate(
        self,
        asins: list[str],
        *,
        page: int,
        page_size: int,
        extras: dict[str, dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        page = _page(page, "page")
        page_size = _page(page_size, "page_size", maximum=100)
        total = len(asins)
        total_pages = max(1, math.ceil(total / page_size))
        if page > total_pages:
            raise ValueError(f"page exceeds total_pages ({total_pages})")
        start = (page - 1) * page_size
        selected = asins[start : start + page_size]
        return {
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": total_pages,
            "has_previous": page > 1,
            "has_next": page < total_pages,
            "items": [
                self._public_product(
                    asin,
                    rank=start + offset + 1,
                    extra=(extras or {}).get(asin),
                )
                for offset, asin in enumerate(selected)
            ],
        }

    def catalog(self, *, page: int = 1, page_size: int = 30) -> dict[str, Any]:
        result = self._paginate(
            self.catalog_asins, page=page, page_size=page_size
        )
        result["mode"] = "catalog"
        return result

    def search(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ValueError("request body must be an object")
        query = payload.get("query_text") or payload.get("message")
        if not isinstance(query, str) or not query.strip():
            raise ValueError("query_text must be a non-empty string")
        page = _page(payload.get("page", 1), "page")
        page_size = _page(payload.get("page_size", 30), "page_size", maximum=100)
        intent = parse_tactile_intent(query)
        query_tokens = _tokens(query)
        pool = [
            asin
            for asin in self.catalog_asins
            if intent.category is None
            or self.product_metadata[asin]["category"] == intent.category
        ]
        candidates = []
        for asin in pool:
            lexical = _jaccard(query_tokens, self._title_tokens[asin])
            profile = self.store._profile_cache.get(asin)
            evidence = profile.evidence_strength if profile is not None else 0.0
            # Lexical relevance is primary when title terms overlap. With Korean tactile queries,
            # category and evidence quality form a neutral retrieval base before intent reranking.
            base_score = 0.65 * lexical + 0.25 * evidence + 0.10
            candidates.append({"product_id": asin, "base_score": base_score})
        ranked = self.ranking.rerank(
            candidates=candidates,
            strategy="context_gated",
            intent=intent,
            top_k=len(candidates),
        ) if candidates else {"results": []}
        ranked["results"].sort(
            key=lambda row: (-row["final_score"], row["product_id"])
        )
        ordered = self._deduplicate(
            [row["product_id"] for row in ranked["results"]]
        )
        extras = {
            row["product_id"]: {
                "relevance_score": row["final_score"],
                "score_breakdown": row["score_breakdown"],
                "matched_tactile_constraints": row["reason"]["matched_constraints"],
                "matched_evidence": row["reason"].get("evidence", []),
            }
            for row in ranked["results"]
        }
        result = self._paginate(
            ordered, page=page, page_size=page_size, extras=extras
        )
        result.update(
            {
                "mode": "natural_language_search",
                "query_text": query.strip(),
                "intent": intent.public_dict(),
                "message": (
                    "자연어 조건과 실제 상품·리뷰 근거를 기준으로 정렬했습니다."
                    if ordered
                    else "조건에 맞는 상품을 찾지 못했습니다."
                ),
            }
        )
        return result

    def related(self, asin: str, *, limit: int = 10) -> dict[str, Any]:
        if asin not in self.product_metadata:
            raise KeyError(f"Unknown ASIN: {asin}")
        limit = _page(limit, "limit", maximum=30)
        anchor_meta = self.product_metadata[asin]
        anchor_title = self._title_tokens[asin]
        anchor_visual = self._visual_by_asin.get(asin)
        anchor_tactile = (
            self.multimodal.tactile_vector(asin)
            if self.multimodal is not None
            else self.store.vector(asin)
        )
        same_category = [
            candidate
            for candidate, meta in self.product_metadata.items()
            if (
                self._identity_by_asin[candidate] != self._identity_by_asin[asin]
                and meta["category"] == anchor_meta["category"]
            )
        ]

        design_rows = []
        related_config = self.store.config["related"]
        design_image_weight = float(related_config["design_image_weight"])
        design_title_weight = float(related_config["design_title_weight"])
        for candidate in same_category:
            title_similarity = _jaccard(anchor_title, self._title_tokens[candidate])
            candidate_visual = self._visual_by_asin.get(candidate)
            visual_similarity = (
                float(anchor_visual @ candidate_visual)
                if anchor_visual is not None and candidate_visual is not None
                else None
            )
            visual01 = (visual_similarity + 1.0) / 2.0 if visual_similarity is not None else 0.0
            # Category is an eligibility constraint. Full-catalog image similarity is primary.
            score = design_title_weight * title_similarity + (
                design_image_weight * visual01 if visual_similarity is not None else 0.0
            )
            design_rows.append((candidate, score, title_similarity, visual_similarity))
        design_rows.sort(key=lambda row: (-row[1], row[0]))
        design_candidates = self._deduplicate([row[0] for row in design_rows])
        design_by_asin = {row[0]: row for row in design_rows}
        design_rows = [design_by_asin[candidate] for candidate in design_candidates]

        tactile_rows = []
        tactile_similarity_weight = float(related_config["tactile_similarity_weight"])
        tactile_confidence_weight = float(related_config["tactile_confidence_weight"])
        if anchor_tactile is not None:
            for candidate in same_category:
                vector = (
                    self.multimodal.tactile_vector(candidate)
                    if self.multimodal is not None
                    else self.store.vector(candidate)
                )
                if vector is None:
                    continue
                cosine = float(anchor_tactile @ vector)
                confidence = (
                    self.multimodal.target_info(candidate)["tactile_target_confidence"]
                    if self.multimodal is not None
                    else self.store._profile_cache[candidate].evidence_strength
                )
                score = (
                    tactile_similarity_weight * ((cosine + 1.0) / 2.0)
                    + tactile_confidence_weight * confidence
                )
                tactile_rows.append((candidate, score, cosine, confidence))
            tactile_rows.sort(key=lambda row: (-row[1], row[0]))
            tactile_candidates = self._deduplicate([row[0] for row in tactile_rows])
            tactile_by_asin = {row[0]: row for row in tactile_rows}
            tactile_rows = [tactile_by_asin[candidate] for candidate in tactile_candidates]

        return {
            "product_id": asin,
            "category": anchor_meta["category"],
            "anchor_target": (
                self.multimodal.target_info(asin) if self.multimodal is not None else None
            ),
            "design_similar": [
                self._public_product(
                    candidate,
                    rank=index,
                    extra={
                        "relevance_score": score,
                        "title_style_similarity": title_similarity,
                        "visual_similarity": visual_similarity,
                        "score_breakdown": {
                            "image_similarity_01": ((visual_similarity + 1.0) / 2.0) if visual_similarity is not None else 0.0,
                            "title_style_similarity": title_similarity,
                            "weighted_image": design_image_weight * ((visual_similarity + 1.0) / 2.0) if visual_similarity is not None else 0.0,
                            "weighted_title": design_title_weight * title_similarity,
                            "final_score": score,
                        },
                        "method": (
                            "same_category_fashionclip_image_plus_title"
                            if self._visual_method == "fashionclip_full_catalog"
                            else "same_category_title_plus_frozen_visual"
                            if visual_similarity is not None
                            else "same_category_title_metadata"
                        ),
                    },
                )
                for index, (candidate, score, title_similarity, visual_similarity) in enumerate(
                    design_rows[:limit], 1
                )
            ],
            "tactile_similar": [
                self._public_product(
                    candidate,
                    rank=index,
                    extra={
                        "relevance_score": score,
                        "tactile_cosine": cosine,
                        "evidence_strength": confidence,
                        "score_breakdown": {
                            "tactile_similarity_01": (cosine + 1.0) / 2.0,
                            "target_confidence": confidence,
                            "weighted_tactile": tactile_similarity_weight * ((cosine + 1.0) / 2.0),
                            "weighted_confidence": tactile_confidence_weight * confidence,
                            "final_score": score,
                        },
                        "target_source": (
                            self.multimodal.target_info(candidate)["tactile_target_source"]
                            if self.multimodal is not None
                            else "review_observed"
                        ),
                        "method": (
                            "same_category_hybrid_tactile_cosine"
                            if self.multimodal is not None
                            else "same_category_review_target_cosine"
                        ),
                    },
                )
                for index, (candidate, score, cosine, confidence) in enumerate(
                    tactile_rows[:limit], 1
                )
            ],
            "design_method_note": (
                "Design similarity uses same-category FashionCLIP image cosine as the primary "
                "signal and title/style token similarity as a configurable secondary signal."
            ),
            "tactile_method_note": (
                "Tactile similarity uses confidence-weighted review and image-predicted "
                "384-dimensional targets; target_source is returned per product."
                if self.multimodal is not None
                else "Tactile similarity uses review-derived 384-dimensional product targets."
            ),
        }
