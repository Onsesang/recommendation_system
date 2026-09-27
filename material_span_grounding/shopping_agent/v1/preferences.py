from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from demo_agent.models import TACTILE_CLASSES
from recommendation_api.tactile_agent import parse_tactile_intent
from recommendation_api.tactile_models import TactileIntent

from .database import AgentDatabase


COLOR_PATTERNS = {
    "black": (r"\bblack\b", r"검정", r"검은", r"블랙"),
    "white": (r"\bwhite\b", r"흰색", r"하얀", r"화이트"),
    "navy": (r"\bnavy\b", r"네이비", r"남색"),
    "blue": (r"\bblue\b", r"파란", r"파랑", r"블루"),
    "red": (r"\bred\b", r"빨간", r"빨강", r"레드"),
    "pink": (r"\bpink\b", r"분홍", r"핑크"),
    "beige": (r"\bbeige\b", r"베이지"),
    "gray": (r"\bgr[ae]y\b", r"회색", r"그레이"),
    "green": (r"\bgreen\b", r"초록", r"그린"),
    "brown": (r"\bbrown\b", r"갈색", r"브라운"),
    "purple": (r"\bpurple\b", r"보라", r"퍼플"),
}

STYLE_PATTERNS = {
    "pleated": (r"\bpleated?\b", r"플리츠", r"주름"),
    "midi": (r"\bmidi\b", r"미디"),
    "mini": (r"\bmini\b", r"미니"),
    "maxi": (r"\bmaxi\b", r"맥시", r"롱"),
    "slim": (r"\bslim\b", r"슬림"),
    "oversized": (r"\boversi[sz]ed\b", r"오버핏", r"오버사이즈"),
    "casual": (r"\bcasual\b", r"캐주얼"),
    "formal": (r"\bformal\b", r"포멀", r"정장", r"출근"),
}


def _matches(text: str, patterns: tuple[str, ...]) -> bool:
    return any(re.search(pattern, text, re.IGNORECASE) for pattern in patterns)


def _explicit_strength(text: str) -> tuple[float, float]:
    if re.search(r"(?:나는|제가|난|항상|좋아해|선호|싫어해|추천하지\s*마|기억해|i\s+(?:like|love|hate|prefer))", text, re.I):
        return 1.0, 0.95
    return 0.65, 0.75


@dataclass(frozen=True)
class ExtractedPreferences:
    intent: TactileIntent
    saved: list[dict[str, Any]]


class PreferenceService:
    """Persist model-independent, category-scoped preferences from chat."""

    def __init__(self, database: AgentDatabase) -> None:
        self.database = database

    def extract_and_save(
        self,
        user_id: str,
        message: str,
        *,
        previous_intent: TactileIntent | None = None,
        structured: dict[str, Any] | None = None,
    ) -> ExtractedPreferences:
        """Save what the message says about tactile, color and style.

        `structured` is the tool model's own reading of the message (category, want, avoid
        as Last2 classes). It handles negation such as "안 까끌한" that the keyword parser
        misses, so when given it replaces the keyword parser for tactile preferences.
        """
        intent = parse_tactile_intent(message, previous=previous_intent)
        strength, confidence = _explicit_strength(message)
        saved: list[dict[str, Any]] = []

        if structured is not None:
            scope = structured.get("category")
            tactile_groups: tuple[tuple[Any, str], ...] = (
                (structured.get("want", ()), "more"),
                (structured.get("avoid", ()), "avoid"),
            )
            tactile_confidence = confidence
        else:
            scope = intent.category
            tactile_groups = (
                (intent.desired_more, "more"),
                (intent.desired_less, "less"),
                (intent.avoid, "avoid"),
                (intent.must_have, "must_have"),
            )
            tactile_confidence = min(confidence, intent.confidence)
        for concepts, direction in tactile_groups:
            for concept in concepts:
                saved.append(
                    self.database.upsert_preference(
                        user_id,
                        scope_category=scope,
                        attribute_type="tactile",
                        attribute=concept,
                        direction=direction,
                        strength=strength,
                        confidence=tactile_confidence,
                        source="chat_auto",
                        source_text=message,
                    )
                )

        text = message.casefold()
        negative = bool(re.search(r"(?:싫|피하|빼줘|제외|avoid|hate|don['’]t\s+like)", text))
        direction = "avoid" if negative else "more"
        for color, patterns in COLOR_PATTERNS.items():
            if _matches(text, patterns):
                saved.append(
                    self.database.upsert_preference(
                        user_id,
                        scope_category=scope,
                        attribute_type="color",
                        attribute=color,
                        direction=direction,
                        strength=strength,
                        confidence=confidence,
                        source="chat_auto",
                        source_text=message,
                    )
                )
        for style, patterns in STYLE_PATTERNS.items():
            if _matches(text, patterns):
                saved.append(
                    self.database.upsert_preference(
                        user_id,
                        scope_category=scope,
                        attribute_type="style",
                        attribute=style,
                        direction=direction,
                        strength=strength,
                        confidence=confidence,
                        source="chat_auto",
                        source_text=message,
                    )
                )
        return ExtractedPreferences(intent=intent, saved=saved)

    def save_onboarding(
        self, user_id: str, answers: dict[str, list[str]], *, completed: bool
    ) -> dict[str, Any]:
        """Save onboarding answers and mirror the tactile picks as explicit preferences.

        Onboarding tactile option ids are Last2 classes (soft, thin, elastic, ...). Only picks
        that changed since the last save are synced, so a preference the user forgot or turned
        off in 내 취향 is not brought back by an unrelated save such as a voice setting.
        """
        before = self.database.get_onboarding(user_id)
        saved = self.database.save_onboarding(user_id, answers, completed=completed)
        classes = lambda ids: {value for value in ids if value in TACTILE_CLASSES}
        old = classes(before["answers"].get("tactile", [])) if before else set()
        new = classes(answers.get("tactile", []))
        for attribute in sorted(new - old):
            self.database.add_preference_if_absent(
                user_id, attribute_type="tactile", attribute=attribute, direction="more",
                strength=1.0, confidence=0.95, source="onboarding", source_text="onboarding",
            )
        for attribute in sorted(old - new):
            self.database.delete_sourced_preference(
                user_id, attribute_type="tactile", attribute=attribute, direction="more", source="onboarding",
            )
        return saved

    def tactile_intent_for_category(
        self,
        user_id: str,
        *,
        category: str | None,
        current: TactileIntent,
    ) -> TactileIntent:
        preferences = self.database.list_preferences(user_id)
        buckets: dict[str, list[str]] = {
            "more": list(current.desired_more),
            "less": list(current.desired_less),
            "avoid": list(current.avoid),
            "must_have": list(current.must_have),
        }
        for pref in preferences:
            if pref["attribute_type"] != "tactile":
                continue
            pref_category = pref.get("scope_category")
            if pref_category and category and pref_category != category:
                continue
            if pref_category and category is None:
                continue
            direction = str(pref["direction"])
            if direction in buckets and float(pref["confidence"]) >= 0.55:
                buckets[direction].append(str(pref["attribute"]))
        unique = lambda values: tuple(dict.fromkeys(values))
        return TactileIntent(
            current_product_id=current.current_product_id,
            category=category or current.category,
            query_text=current.query_text,
            desired_more=unique(buckets["more"]),
            desired_less=unique(buckets["less"]),
            avoid=unique(buckets["avoid"]),
            must_have=unique(buckets["must_have"]),
            source="agent_context",
            confidence=max(0.75, current.confidence),
        )

