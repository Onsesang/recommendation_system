from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


TACTILE_CLASSES = (
    "soft",
    "firm",
    "smooth",
    "rough",
    "non_elastic",
    "elastic",
    "thin",
    "thick",
    "flexible",
    "stiff",
    "warm",
    "cool",
    "spongy",
    "crisp",
)

SUPPORTED_CATEGORIES = (
    "shirt",
    "tshirt",
    "sweater",
    "jacket",
    "coat",
    "pants",
    "jeans",
    "dress",
    "skirt",
    "hoodie",
    "cardigan",
    "top",
    "outerwear",
    "underwear",
    "sleepwear",
    "swimwear",
    "accessory",
)


@dataclass(frozen=True)
class Constraint:
    tactile_class: str
    weight: float = 1.0

    def __post_init__(self) -> None:
        if self.tactile_class not in TACTILE_CLASSES:
            raise ValueError(f"unknown tactile class: {self.tactile_class}")
        if not 0.0 < float(self.weight) <= 10.0:
            raise ValueError("constraint weight must be in (0, 10]")

    def public_dict(self) -> dict[str, Any]:
        return {"tactile_class": self.tactile_class, "weight": float(self.weight)}


@dataclass(frozen=True)
class StructuredQuery:
    category: str | None = None
    constraints: tuple[Constraint, ...] = field(default_factory=tuple)
    negative_constraints: tuple[Constraint, ...] = field(default_factory=tuple)
    source: str = "deterministic_fallback"
    original_message: str = ""

    def __post_init__(self) -> None:
        if self.category is not None and self.category not in SUPPORTED_CATEGORIES:
            raise ValueError(f"unsupported category: {self.category}")
        positive = [item.tactile_class for item in self.constraints]
        negative = [item.tactile_class for item in self.negative_constraints]
        if len(positive) != len(set(positive)) or len(negative) != len(set(negative)):
            raise ValueError("a tactile class may occur only once in each constraint bucket")
        overlap = set(positive) & set(negative)
        if overlap:
            raise ValueError(f"contradictory tactile constraints: {sorted(overlap)}")

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any], *, source: str) -> "StructuredQuery":
        def parse_bucket(name: str) -> tuple[Constraint, ...]:
            raw = value.get(name, [])
            if not isinstance(raw, (list, tuple)):
                raise ValueError(f"{name} must be an array")
            parsed = []
            for item in raw:
                if not isinstance(item, Mapping):
                    raise ValueError(f"{name} entries must be objects")
                tactile_class = item.get("tactile_class", item.get("class"))
                parsed.append(
                    Constraint(str(tactile_class), float(item.get("weight", 1.0)))
                )
            return tuple(parsed)

        category = value.get("category") or None
        return cls(
            category=str(category) if category else None,
            constraints=parse_bucket("constraints"),
            negative_constraints=parse_bucket("negative_constraints"),
            source=source,
            original_message=str(value.get("original_message") or ""),
        )

    def public_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "constraints": [item.public_dict() for item in self.constraints],
            "negative_constraints": [
                item.public_dict() for item in self.negative_constraints
            ],
            "source": self.source,
            "original_message": self.original_message,
        }

    @property
    def has_tactile_constraints(self) -> bool:
        return bool(self.constraints or self.negative_constraints)
