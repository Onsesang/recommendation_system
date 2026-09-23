from __future__ import annotations

import re
from dataclasses import replace
from typing import Any, Mapping

import numpy as np

from .tactile_models import TactileIntent
from .tactile_normalization import canonical_concept
from .tactile_ranking import TactileRankingService, _cosine01
from .tactile_store import TactileStore


CATEGORY_PATTERNS = {
    "pants": (r"\b(?:pants|trousers|leggings|jeans)\b", r"바지", r"레깅스", r"청바지"),
    "skirt": (r"\bskirt\b", r"치마", r"스커트"),
    "dress": (r"\bdress\b", r"원피스", r"드레스"),
    "top": (r"\b(?:top|shirt|t-shirt|tee|blouse|hoodie)\b", r"상의", r"셔츠", r"티셔츠", r"블라우스"),
    "sweater": (r"\b(?:sweater|cardigan|knit)\b", r"스웨터", r"가디건", r"니트"),
    "outerwear": (r"\b(?:jacket|coat)\b", r"재킷", r"자켓", r"코트", r"아우터"),
    "underwear": (r"\b(?:underwear|bra|briefs|socks)\b", r"속옷", r"브라", r"양말"),
    "sleepwear": (r"\b(?:pajamas|sleepwear|robe)\b", r"잠옷", r"파자마", r"로브"),
    "swimwear": (r"\b(?:swimsuit|swimwear|bikini)\b", r"수영복", r"비키니"),
    "accessory": (r"\b(?:hat|scarf|gloves)\b", r"모자", r"스카프", r"장갑"),
}

CONCEPT_PATTERNS = {
    "softness": (r"soft", r"부드러"),
    "scratchiness": (r"scratchy", r"까슬", r"따갑"),
    "itchiness": (r"itchy", r"가려"),
    "roughness": (r"rough", r"거칠"),
    "weight_lightness": (r"lightweight", r"가벼", r"가볍"),
    "heaviness": (r"heavy", r"무거"),
    "thinness": (r"\bthin\b", r"얇"),
    "thickness": (r"thick", r"두꺼"),
    "sheerness": (r"sheer", r"see[- ]?through", r"비치"),
    "stretchiness": (r"stretchy", r"신축", r"잘 늘어"),
    "stiffness": (r"stiff", r"뻣뻣"),
    "breathability": (r"breathable", r"통기"),
    "warmth": (r"warm", r"따뜻"),
    "coolness": (r"cool", r"시원"),
    "flowiness": (r"flowy", r"찰랑", r"하늘하늘"),
    "linting": (r"lint", r"먼지.*묻", r"보풀"),
    "pilling": (r"pilling", r"필링"),
}

_CLAUSE_BOUNDARY = re.compile(r"(?:하지만|지만|그러나|그런데|그리고|\bbut\b|\bhowever\b|[,.!?;])")


def _containing_clause(text: str, start: int, end: int) -> str:
    boundaries = list(_CLAUSE_BOUNDARY.finditer(text))
    left = max((match.end() for match in boundaries if match.end() <= start), default=0)
    right = min((match.start() for match in boundaries if match.start() >= end), default=len(text))
    return text[left:right]


def _ordered_unique(values: list[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(values))


def intent_from_mapping(value: Mapping[str, Any] | None) -> TactileIntent:
    payload = dict(value or {})

    def items(name: str) -> tuple[str, ...]:
        raw = payload.get(name, [])
        if not isinstance(raw, (list, tuple)) or any(
            not isinstance(item, str) or not item.strip() for item in raw
        ):
            raise ValueError(f"{name} must be an array of strings")
        return _ordered_unique([canonical_concept(item) for item in raw])

    return TactileIntent(
        current_product_id=(
            str(payload["current_product_id"])
            if payload.get("current_product_id")
            else None
        ),
        category=str(payload["category"]) if payload.get("category") else None,
        query_text=str(payload["query_text"]) if payload.get("query_text") else None,
        desired_more=items("desired_more"),
        desired_less=items("desired_less"),
        avoid=items("avoid"),
        must_have=items("must_have"),
        source=str(payload.get("source") or "explicit_structured"),
        confidence=float(payload.get("confidence", 1.0)),
    )


def parse_tactile_intent(
    query_text: str,
    *,
    current_product_id: str | None = None,
    previous: TactileIntent | None = None,
) -> TactileIntent:
    if not isinstance(query_text, str) or not query_text.strip():
        raise ValueError("query_text must be a non-empty string")
    text = query_text.casefold().strip()
    category = None
    for name, patterns in CATEGORY_PATTERNS.items():
        if any(re.search(pattern, text) for pattern in patterns):
            category = name
            break

    more: list[str] = []
    less: list[str] = []
    avoid: list[str] = []
    must: list[str] = []
    for concept, patterns in CONCEPT_PATTERNS.items():
        hit = None
        for pattern in patterns:
            match = re.search(pattern, text)
            if match and (hit is None or match.start() < hit.start()):
                hit = match
        if hit is None:
            continue
        window = _containing_clause(text, hit.start(), hit.end())
        sheerness_avoid = concept == "sheerness" and re.search(
            r"(?:안\s*비|비치지\s*않|not\s+see|not\s+sheer)", window
        )
        general_avoid = re.search(r"(?:싫|피하|avoid|without)", window)
        if sheerness_avoid or general_avoid:
            avoid.append(concept)
        elif re.search(r"(?:반드시|꼭|must|need)", window):
            must.append(concept)
        elif re.search(
            r"(?:덜|less|not as|(?:잘\s*)?늘어나지\s*않|(?:잘\s*)?늘어나지|doesn['’]t\s+stretch|not\s+stretch)",
            window,
        ):
            less.append(concept)
        elif re.search(r"(?:더|more|조금 더)", window):
            more.append(concept)
        elif concept in {"scratchiness", "itchiness", "roughness", "sheerness", "linting", "pilling"}:
            # Negative properties require an explicit direction; merely mentioning one does not
            # prove the user wants more or less of it.
            continue
        else:
            more.append(concept)

    previous = previous or TactileIntent()
    desired_more = list(previous.desired_more)
    desired_less = list(previous.desired_less)
    avoided = list(previous.avoid)
    required = list(previous.must_have)

    opposites = {
        "thinness": {"thickness"},
        "thickness": {"thinness"},
        "weight_lightness": {"heaviness"},
        "heaviness": {"weight_lightness"},
    }
    for concept in [*more, *less, *avoid, *must]:
        for opposite in opposites.get(concept, set()):
            desired_more = [value for value in desired_more if value != opposite]
            desired_less = [value for value in desired_less if value != opposite]
            avoided = [value for value in avoided if value != opposite]
            required = [value for value in required if value != opposite]
    desired_more.extend(more)
    desired_less.extend(less)
    avoided.extend(avoid)
    required.extend(must)
    # The newest explicit bucket owns a concept and removes stale contradictory state.
    for concept in more:
        desired_less = [value for value in desired_less if value != concept]
        avoided = [value for value in avoided if value != concept]
    for concept in [*less, *avoid]:
        desired_more = [value for value in desired_more if value != concept]
        required = [value for value in required if value != concept]
    for concept in must:
        avoided = [value for value in avoided if value != concept]

    return TactileIntent(
        current_product_id=current_product_id or previous.current_product_id,
        category=category or previous.category,
        query_text=query_text.strip(),
        desired_more=_ordered_unique(desired_more),
        desired_less=_ordered_unique(desired_less),
        avoid=_ordered_unique(avoided),
        must_have=_ordered_unique(required),
        source="agent_context" if previous.query_text else "deterministic_nlp",
        confidence=0.85 if any((more, less, avoid, must)) else 0.5,
    )


class TactileAgentService:
    """Natural-language facade over deterministic intent and real catalog ranking."""

    def __init__(self, store: TactileStore) -> None:
        self.store = store
        self.ranking = TactileRankingService(store)

    def handle(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        self.store.require_feature("tactile_agent")
        if not isinstance(payload, Mapping):
            raise ValueError("request body must be an object")
        query = payload.get("message") or payload.get("query_text")
        previous = intent_from_mapping(payload.get("previous_intent"))
        current = payload.get("current_product_id") or previous.current_product_id
        if current is not None and str(current) not in self.store.product_metadata:
            raise KeyError(f"Unknown ASIN: {current}")
        intent = parse_tactile_intent(
            str(query) if query is not None else "",
            current_product_id=str(current) if current else None,
            previous=previous,
        )
        if intent.current_product_id and not intent.category:
            intent = replace(
                intent,
                category=self.store.product_metadata[intent.current_product_id]["category"],
            )
        if not intent.category:
            return {
                "status": "needs_clarification",
                "message": "어떤 종류의 상품을 찾는지 알려주세요.",
                "intent": intent.public_dict(),
                "results": [],
            }

        candidates = []
        anchor_matches_category = bool(
            intent.current_product_id
            and self.store.product_metadata[intent.current_product_id]["category"]
            == intent.category
        )
        anchor_vector = (
            self.store.vector(intent.current_product_id) if anchor_matches_category else None
        )
        for asin, meta in self.store.product_metadata.items():
            if meta["category"] != intent.category or asin == intent.current_product_id:
                continue
            vector = self.store.vector(asin)
            if vector is None:
                continue
            profile = self.store._profile_cache[asin]
            base = (
                _cosine01(anchor_vector, vector)
                if anchor_vector is not None
                else float(profile.evidence_strength)
            )
            candidates.append({"product_id": asin, "base_score": base})
        candidates.sort(key=lambda row: (-row["base_score"], row["product_id"]))
        candidates = candidates[:100]
        ranked = self.ranking.rerank(
            candidates=candidates,
            strategy="context_gated",
            intent=intent,
            top_k=int(payload.get("top_k", 10)),
        )
        catalog_ids = set(self.store.product_metadata)
        if any(row["product_id"] not in catalog_ids for row in ranked["results"]):
            raise RuntimeError("Agent ranking returned a product outside the real catalog")
        return {
            "status": "complete" if ranked["results"] else "insufficient_evidence",
            "message": (
                "실제 상품과 리뷰 근거를 사용한 추천입니다."
                if ranked["results"]
                else "조건을 만족하는 근거 있는 상품을 찾지 못했습니다."
            ),
            "intent": intent.public_dict(),
            "retrieval": {
                "category": intent.category,
                "candidate_count": len(candidates),
                "strategy": "context_gated",
                "anchor_used": bool(anchor_vector is not None),
                "invented_product_allowed": False,
            },
            "results": ranked["results"],
        }
