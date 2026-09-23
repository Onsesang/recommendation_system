from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import yaml


ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class ExperimentPaths:
    root: Path = ROOT
    configs: Path = ROOT / "configs"
    artifacts: Path = ROOT / "artifacts"
    plots: Path = ROOT / "plots"
    reports: Path = ROOT / "reports"
    notion: Path = ROOT / "notion"
    manifests: Path = ROOT / "manifests"
    cache: Path = ROOT / "cache"
    external: Path = ROOT / "external"


PATHS = ExperimentPaths()


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        value = yaml.safe_load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"Expected mapping in {path}")
    return value


def load_experiment() -> dict[str, Any]:
    return load_yaml(PATHS.configs / "experiment.yaml")


def load_taxonomy() -> dict[str, Any]:
    taxonomy = load_yaml(PATHS.configs / "tactile_axes.yaml")
    validate_taxonomy(taxonomy)
    return taxonomy


def validate_taxonomy(taxonomy: dict[str, Any]) -> None:
    axes = taxonomy.get("axes")
    if not isinstance(axes, list) or not axes:
        raise ValueError("taxonomy.axes must be a non-empty list")
    required = {
        "id", "display_name", "type", "negative_pole", "positive_pole",
        "definition", "external_sources",
    }
    ids: set[str] = set()
    for axis in axes:
        missing = required - set(axis)
        if missing:
            raise ValueError(f"Axis is missing fields {sorted(missing)}: {axis}")
        axis_id = str(axis["id"])
        if axis_id in ids:
            raise ValueError(f"Duplicate axis id: {axis_id}")
        if axis["negative_pole"] == axis["positive_pole"]:
            raise ValueError(f"Identical poles for {axis_id}")
        ids.add(axis_id)
    coding = taxonomy.get("ordinal_coding", {})
    for key in ("negative_pole", "positive_pole", "neutral", "intensity_multiplier"):
        if key not in coding:
            raise ValueError(f"Missing ordinal coding field: {key}")


def read_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def _atomic_write(path: Path, writer: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
            writer(handle)
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def write_json(path: Path, value: Any) -> None:
    def writer(handle: Any) -> None:
        json.dump(value, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.write("\n")
    _atomic_write(path, writer)


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    def writer(handle: Any) -> None:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n")
    _atomic_write(path, writer)


def append_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def finite_or_none(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number and abs(number) != float("inf") else None


def axis_map(taxonomy: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(axis["id"]): axis for axis in taxonomy["axes"]}


def symbolic_score(mapping: dict[str, Any], taxonomy: dict[str, Any]) -> float:
    axes = axis_map(taxonomy)
    axis = axes[str(mapping["axis_id"])]
    direction = str(mapping["direction"])
    coding = taxonomy["ordinal_coding"]
    if direction == axis["negative_pole"]:
        base = float(coding["negative_pole"])
    elif direction == axis["positive_pole"]:
        base = float(coding["positive_pole"])
    elif direction == "neutral":
        return float(coding["neutral"])
    else:
        raise ValueError(f"Invalid direction {direction!r} for {axis['id']}")
    multiplier = float(coding["intensity_multiplier"][str(mapping["intensity"])])
    return base * multiplier

