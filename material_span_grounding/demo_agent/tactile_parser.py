from __future__ import annotations

import re
from dataclasses import replace
from typing import Iterable

from recommendation_api.tactile_agent import CATEGORY_PATTERNS as REPOSITORY_CATEGORY_PATTERNS

from .models import Constraint, StructuredQuery


# Specific garment words are checked before the repository's broad 11-category heuristic.
SPECIFIC_CATEGORY_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("tshirt", (r"티\s*셔츠", r"\bt[- ]?shirts?\b", r"\btees?\b")),
    ("shirt", (r"셔츠", r"블라우스", r"\bshirts?\b", r"\bblouses?\b")),
    ("cardigan", (r"가디건", r"\bcardigans?\b")),
    ("hoodie", (r"후드(?:티|집업)?", r"\bhood(?:ie|ed sweatshirt)s?\b")),
    ("sweater", (r"니트", r"스웨터", r"\bsweaters?\b", r"\bknitwear\b")),
    ("jacket", (r"자켓", r"재킷", r"\bjackets?\b")),
    ("coat", (r"코트", r"\bcoats?\b")),
    ("jeans", (r"청바지", r"데님\s*바지", r"\bjeans?\b")),
    ("pants", (r"바지", r"팬츠", r"\b(?:pants|trousers|leggings)\b")),
    ("dress", (r"원피스", r"드레스", r"\bdresses?\b")),
    ("skirt", (r"스커트", r"치마", r"\bskirts?\b")),
)

TACTILE_PATTERNS: dict[str, tuple[str, ...]] = {
    "soft": (r"부드럽|부드러", r"보들", r"포근", r"\bsoft(?:er|est)?\b"),
    "firm": (r"탄탄", r"단단", r"견고", r"\bfirm\b", r"\bstructured\b"),
    "smooth": (r"매끄러", r"매끈", r"실키", r"\bsmooth\b", r"\bsilky\b"),
    "rough": (r"거칠", r"까슬", r"꺼끌", r"\brough\b", r"\bscratchy\b"),
    "elastic": (r"신축", r"잘\s*늘어", r"쫀쫀", r"\belastic\b", r"\bstretchy\b"),
    "thin": (r"얇", r"가벼운\s*두께", r"\bthin\b", r"\blightweight\b"),
    "thick": (r"두껍|두꺼", r"도톰", r"\bthick\b", r"\bheavyweight\b"),
    "flexible": (r"유연", r"유연한", r"잘\s*휘", r"\bflexible\b", r"\bpliable\b"),
    "stiff": (r"뻣뻣", r"빳빳", r"\bstiff\b", r"\brigid\b"),
    "warm": (r"따뜻", r"보온", r"\bwarm\b", r"\binsulated\b"),
    "cool": (r"시원", r"청량", r"\bcool(?:ing)?\b"),
    "spongy": (r"폭신", r"푹신", r"쿠션감", r"\bspongy\b", r"\bcushiony\b"),
    "crisp": (r"바삭", r"각(?:이|을)?\s*잡", r"각진\s*느낌", r"\bcrisp\b"),
}

NON_ELASTIC_PATTERNS = (
    r"신축성?(?:이)?\s*(?:없|적)",
    r"(?:잘\s*)?늘어나지\s*않",
    r"잘\s*안\s*늘어",
    r"\bnon[-_ ]?elastic\b",
    r"\binelastic\b",
    r"\b(?:not stretchy|no stretch)\b",
)

OPPOSITES = {
    "soft": "firm",
    "firm": "soft",
    "smooth": "rough",
    "rough": "smooth",
    "non_elastic": "elastic",
    "elastic": "non_elastic",
    "thin": "thick",
    "thick": "thin",
    "flexible": "stiff",
    "stiff": "flexible",
    "warm": "cool",
    "cool": "warm",
    "spongy": "crisp",
    "crisp": "spongy",
}

NEGATION_BEFORE = re.compile(r"(?:안|덜|피하고|피해|제외|싫은|싫어|not|no|without|avoid)\s*$", re.I)
# A Korean verb stem can sit between the tactile word and its negation
# ("까슬" + "거리" + "지 않는"), so allow a short run of syllables before `지 않`.
NEGATION_AFTER = re.compile(r"^[가-힣]{0,4}?지\s*않|^\s*(?:아니|말고|싫|피하)", re.I)
RESET_PATTERN = re.compile(r"(?:조건\s*초기화|처음부터|새로\s*찾|new search|start over)", re.I)


def _first_category(text: str) -> str | None:
    for category, patterns in SPECIFIC_CATEGORY_PATTERNS:
        if any(re.search(pattern, text, re.I) for pattern in patterns):
            return category
    for category, patterns in REPOSITORY_CATEGORY_PATTERNS.items():
        if any(re.search(pattern, text, re.I) for pattern in patterns):
            return category
    return None


def _is_negated(text: str, start: int, end: int) -> bool:
    return bool(
        NEGATION_BEFORE.search(text[max(0, start - 16) : start])
        or NEGATION_AFTER.search(text[end : end + 18])
    )


def _remove_class(items: Iterable[Constraint], tactile_class: str) -> list[Constraint]:
    return [item for item in items if item.tactile_class != tactile_class]


def _add_constraint(
    positive: list[Constraint],
    negative: list[Constraint],
    tactile_class: str,
    *,
    is_negative: bool,
    weight: float,
) -> None:
    opposite = OPPOSITES.get(tactile_class)
    for name in (tactile_class, opposite):
        if name:
            positive[:] = _remove_class(positive, name)
            negative[:] = _remove_class(negative, name)
    target = negative if is_negative else positive
    target.append(Constraint(tactile_class, weight))


def parse_message(
    message: str,
    *,
    previous: StructuredQuery | None = None,
    default_weight: float = 1.0,
) -> StructuredQuery:
    """Parse Korean/English garment and Last2 terms with deterministic negation.

    A message that explicitly names both a garment and tactile terms starts a new
    query. A category-free follow-up merges into the previous state, which makes
    requests such as "조금 더 따뜻한 걸로" additive.
    """
    if not isinstance(message, str) or not message.strip():
        raise ValueError("message must be a non-empty string")
    text = message.casefold().strip()
    category = _first_category(text)

    found: list[tuple[int, str, bool]] = []
    blocked_spans: list[tuple[int, int]] = []
    for pattern in NON_ELASTIC_PATTERNS:
        for match in re.finditer(pattern, text, re.I):
            found.append((match.start(), "non_elastic", False))
            blocked_spans.append(match.span())

    for tactile_class, patterns in TACTILE_PATTERNS.items():
        for pattern in patterns:
            for match in re.finditer(pattern, text, re.I):
                if tactile_class == "elastic" and any(
                    left <= match.start() < right for left, right in blocked_spans
                ):
                    continue
                found.append(
                    (match.start(), tactile_class, _is_negated(text, *match.span()))
                )

    # First occurrence wins for duplicate synonyms of the same class.
    deduped: list[tuple[int, str, bool]] = []
    seen: set[str] = set()
    for hit in sorted(found):
        if hit[1] not in seen:
            deduped.append(hit)
            seen.add(hit[1])

    starts_new = bool(RESET_PATTERN.search(text)) or (
        category is not None and bool(deduped)
    )
    if previous is not None and not starts_new:
        positive = list(previous.constraints)
        negative = list(previous.negative_constraints)
        resolved_category = category or previous.category
    else:
        positive = []
        negative = []
        resolved_category = category

    for _, tactile_class, is_negative in deduped:
        _add_constraint(
            positive,
            negative,
            tactile_class,
            is_negative=is_negative,
            weight=default_weight,
        )

    source = "agent_context" if previous is not None and not starts_new else "deterministic_fallback"
    return StructuredQuery(
        category=resolved_category,
        constraints=tuple(positive),
        negative_constraints=tuple(negative),
        source=source,
        original_message=message.strip(),
    )


def with_source(query: StructuredQuery, source: str) -> StructuredQuery:
    return replace(query, source=source)
