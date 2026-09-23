from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class ConceptMatch:
    concept: str
    label: str
    direction: int
    matched_text: str
    open_vocabulary: bool = False


# These are presentation aliases, not an exhaustive extraction taxonomy. A claim may match
# multiple concepts and unmatched claims remain individually visible as open vocabulary.
CONCEPT_PATTERNS: dict[str, tuple[str, tuple[str, ...]]] = {
    "softness": ("soft", (r"\bsoft(?:er|est)?\b", r"\bsmooth\b", r"\bsilky\b", r"\bplush\b")),
    "scratchiness": ("scratchy", (r"\bscratch(?:y|ier|iest)?\b", r"\bscratches?\b")),
    "itchiness": ("itchy", (r"\bitch(?:y|ier|iest)?\b", r"\bitched\b")),
    "roughness": ("rough", (r"\brough(?:er|est)?\b", r"\bcoarse\b")),
    "weight_lightness": ("lightweight", (r"\blightweight\b", r"\bfeather[- ]?light\b")),
    "heaviness": ("heavy", (r"\bheav(?:y|ier|iest)\b",)),
    "thinness": ("thin", (r"\bthin(?:ner|nest)?\b",)),
    "thickness": ("thick", (r"\bthick(?:er|est)?\b",)),
    "sheerness": ("see-through", (r"\bsee[- ]?through\b", r"\bsheer\b", r"\btransparent\b")),
    "opacity": ("opaque", (r"\bopaque\b", r"\bnot transparent\b")),
    "stretchiness": ("stretchy", (r"\bstretch(?:y|ier|iest)?\b", r"\belastic\b", r"\bgives?\b")),
    "stiffness": ("stiff", (r"\bstiff(?:er|est)?\b", r"\brigid\b")),
    "breathability": ("breathable", (r"\bbreathable\b", r"\bbreathes?\b")),
    "warmth": ("warm", (r"\bwarm(?:er|est)?\b", r"\bcozy\b")),
    "coolness": ("cool", (r"\bcool(?:er|est)?\b",)),
    "flowiness": ("flowy", (r"\bflow(?:y|ier|iest)?\b", r"\bdrap(?:e|es|ey|ing)\b")),
    "linting": ("lint", (r"\blint(?:y)?\b", r"\bpicks? up (?:a lot of )?lint\b")),
    "pilling": ("pilling", (r"\bpill(?:ing|s|ed)?\b", r"\bball(?:ing|s|ed)? up\b")),
}

_NEGATION = re.compile(
    r"\b(?:not|never|no|without|isn['’]t|aren['’]t|wasn['’]t|weren['’]t|doesn['’]t|didn['’]t|far from)\b"
)
_SPACE = re.compile(r"\s+")


def _negated_near(text: str, start: int) -> bool:
    prefix = text[max(0, start - 35) : start]
    return bool(_NEGATION.search(prefix))


def concept_matches(text: str, *, property_status: str = "present") -> list[ConceptMatch]:
    normalized = _SPACE.sub(" ", text.casefold()).strip()
    matches: list[ConceptMatch] = []
    for concept, (label, patterns) in CONCEPT_PATTERNS.items():
        hit = None
        for pattern in patterns:
            found = re.search(pattern, normalized)
            if found and (hit is None or found.start() < hit.start()):
                hit = found
        if hit is None:
            continue
        direction = -1 if property_status == "absent" or _negated_near(normalized, hit.start()) else 1
        matches.append(
            ConceptMatch(
                concept=concept,
                label=label,
                direction=direction,
                matched_text=hit.group(0),
            )
        )
    if matches:
        return matches
    # A bare "light" is deliberately left open vocabulary because it may mean color,
    # illumination, or low weight. Unknown claims are never forced into a fixed taxonomy.
    return [
        ConceptMatch(
            concept=f"open:{normalized}",
            label=text.strip(),
            direction=-1 if property_status == "absent" else 1,
            matched_text=text.strip(),
            open_vocabulary=True,
        )
    ]


def canonical_concept(value: str) -> str:
    raw = _SPACE.sub(" ", str(value).casefold().replace("_", " ")).strip()
    for concept, (label, patterns) in CONCEPT_PATTERNS.items():
        if raw in {concept.replace("_", " "), label.casefold()}:
            return concept
        if any(re.fullmatch(pattern, raw) for pattern in patterns):
            return concept
    return f"open:{raw}"

