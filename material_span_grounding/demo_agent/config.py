from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = Path(__file__).with_name("config.json")


@dataclass(frozen=True)
class DemoConfig:
    metadata_path: Path
    profiles_path: Path
    checkpoint_path: Path
    checkpoint_sha256: str
    default_constraint_weight: float
    class_weight_overrides: dict[str, float]
    default_top_k: int
    maximum_top_k: int
    specific_category_min_candidates: int
    initial_catalog_size: int
    maximum_message_characters: int

    @classmethod
    def load(cls, path: Path = DEFAULT_CONFIG_PATH) -> "DemoConfig":
        raw: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        artifacts = raw["artifacts"]
        ranking = raw["ranking"]

        def project_path(value: str) -> Path:
            candidate = Path(value)
            return candidate if candidate.is_absolute() else PROJECT_ROOT / candidate

        config = cls(
            metadata_path=project_path(artifacts["metadata"]),
            profiles_path=project_path(artifacts["last2_profiles"]),
            checkpoint_path=project_path(artifacts["last2_checkpoint_provenance"]),
            checkpoint_sha256=str(artifacts["last2_checkpoint_sha256"]),
            default_constraint_weight=float(ranking["default_constraint_weight"]),
            class_weight_overrides={
                str(key): float(value)
                for key, value in ranking.get("class_weight_overrides", {}).items()
            },
            default_top_k=int(ranking["default_top_k"]),
            maximum_top_k=int(ranking["maximum_top_k"]),
            specific_category_min_candidates=int(ranking["specific_category_min_candidates"]),
            initial_catalog_size=int(ranking["initial_catalog_size"]),
            maximum_message_characters=int(raw["agent"]["maximum_message_characters"]),
        )
        if config.default_constraint_weight <= 0:
            raise ValueError("default_constraint_weight must be positive")
        if not 1 <= config.default_top_k <= config.maximum_top_k:
            raise ValueError("default_top_k must be within the configured maximum")
        return config
