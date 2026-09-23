"""Materialize the Experiment 20 input manifest before validation scoring."""
from __future__ import annotations

import os
import platform
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import torch

from common import ART, CONFIG, DATA, EXP16, PROJECT, ROOT, event, load_json, resolve_project_path, save_json, sha


def package_versions() -> dict:
    out = {
        "python": sys.version,
        "platform": platform.platform(),
        "numpy": np.__version__,
        "pandas": pd.__version__,
        "torch": torch.__version__,
        "cuda_available": torch.cuda.is_available(),
        "cuda_version": torch.version.cuda,
    }
    try:
        import faiss

        out["faiss"] = faiss.__version__
    except Exception as exc:
        out["faiss_error_type"] = type(exc).__name__
    return out


def manifest_entry(item: dict, conditional: bool = False) -> dict:
    path = resolve_project_path(item["path"])
    row = {
        "id": item["id"],
        "path": str(path),
        "exists": path.exists(),
        "conditional": conditional,
        "usage": item.get("usage"),
        "required_before": item.get("required_before"),
        "earliest_state": item.get("earliest_state"),
        "sha256": sha(path) if path.exists() else None,
        "bytes": path.stat().st_size if path.exists() else None,
        "expected_sha256": item.get("expected_sha256"),
    }
    row["hash_matches_expected"] = item.get("expected_sha256") in (None, row["sha256"])
    return row


def source_hashes() -> dict:
    files = sorted(ROOT.glob("*.py")) + sorted((ROOT / "configs").glob("*.json"))
    return {str(path.relative_to(ROOT)): sha(path) for path in files}


def main() -> None:
    ART.mkdir(parents=True, exist_ok=True)
    DATA.mkdir(parents=True, exist_ok=True)
    state_path = ART / "protocol_state.json"
    if not state_path.exists():
        save_json(state_path, {"state": "implemented_not_scored", "history": []})
    event("freeze_inputs", "started")
    protocol = load_json(CONFIG / "protocol.json")
    rows = []
    unresolved = []
    for item in protocol["input_integrity"]["allowed_inputs"]:
        row = manifest_entry(item)
        rows.append(row)
        if not row["exists"] or not row["hash_matches_expected"]:
            unresolved.append(row["id"])
    for item in protocol["input_integrity"]["conditionally_allowed_inputs"]:
        if item["id"] == "exp16_processed_test_targets":
            rows.append(manifest_entry(item, conditional=True))
    test_metric_forbidden = [
        "general_recommendation_results.json",
        "multimodal_recommendation_results.json",
        "candidate_recall.csv",
        "per_user_results.parquet",
        "multimodal_per_user_results.parquet",
    ]
    manifest = {
        "status": "complete" if not unresolved else "incomplete",
        "unresolved_required_inputs": unresolved,
        "project_root": str(PROJECT),
        "experiment_root": str(ROOT),
        "protocol_sha256": sha(CONFIG / "protocol.json"),
        "model_variants_sha256": sha(CONFIG / "model_variants.json"),
        "source_sha256": source_hashes(),
        "environment": package_versions(),
        "inputs": rows,
        "forbidden_experiment16_test_metric_files_not_used_for_selection": test_metric_forbidden,
        "test_target_hash_recorded_without_metric_computation": True,
    }
    save_json(ART / "input_manifest.json", manifest)
    if unresolved:
        event("freeze_inputs", "blocked", unresolved=len(unresolved))
        raise SystemExit(f"unresolved required inputs: {unresolved}")
    event("freeze_inputs", "complete", inputs=len(rows))


if __name__ == "__main__":
    main()
