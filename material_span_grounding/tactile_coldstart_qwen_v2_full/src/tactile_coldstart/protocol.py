from __future__ import annotations

import random
from collections import defaultdict
from pathlib import Path
from typing import Any

from .common import (
    PATHS, load_experiment, load_taxonomy, read_json, read_jsonl, sha256_file,
    utc_now, write_json,
)


def document_taxonomy() -> dict[str, Any]:
    taxonomy = load_taxonomy()
    config = load_experiment()
    path = PATHS.configs / "tactile_axes.yaml"
    manifest = {
        "status": "complete",
        "phase": 1,
        "generated_at": utc_now(),
        "taxonomy_version": taxonomy["version"],
        "candidate_axes": [str(axis["id"]) for axis in taxonomy["axes"]],
        "axis_count": len(taxonomy["axes"]),
        "taxonomy": str(path),
        "taxonomy_sha256": sha256_file(path),
        "selection_policy": config["diagnostics"],
        "active_axis_selection_deferred_to_phase3": True,
    }
    write_json(PATHS.manifests / "phase1_taxonomy.json", manifest)
    lines = [
        "# Phase 1 — Configurable Tactile Taxonomy", "",
        f"Taxonomy version: `{taxonomy['version']}`. Candidate axes are declarative; the active subset is selected only by Phase 3 diagnostics.", "",
        "| Axis | Negative pole | Positive pole | Definition |", "|---|---|---|---|",
    ]
    for axis in taxonomy["axes"]:
        lines.append(f"| {axis['id']} | {axis['negative_pole']} | {axis['positive_pole']} | {axis['definition']} |")
    (PATHS.reports / "phase1_taxonomy.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return manifest


def build_protocol() -> dict[str, Any]:
    from .full_pool import build_full_pool
    return build_full_pool()
