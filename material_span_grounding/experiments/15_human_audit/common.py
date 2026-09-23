from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "config.json"
MANIFEST_PATH = ROOT / "artifacts" / "audit_manifest.json"
ANNOTATION_PATH = ROOT / "annotations" / "human_audit.csv"
RESULTS_PATH = ROOT / "artifacts" / "human_audit_results.json"


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.write("\n")
        os.replace(temporary_name, path)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def source_hashes(config: dict[str, Any]) -> dict[str, str]:
    return {name: sha256(Path(path)) for name, path in config["paths"].items()}


def is_fractional(value: float, tolerance: float = 1e-7) -> bool:
    return abs(value) > tolerance and abs(value - 1.0) > tolerance
