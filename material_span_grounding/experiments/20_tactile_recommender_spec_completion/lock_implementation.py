"""Freeze Experiment 20 implementation before official validation metrics."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from common import ART, CONFIG, ROOT, event, load_json, save_json, sha, transition_state


METRIC_SOURCES = [
    "common.py",
    "models_exp20.py",
    "train_select.py",
    "lock_implementation.py",
    "dry_run.py",
    "freeze_inputs.py",
    "prepare_development_views.py",
    "build_tactile_graph.py",
]


def main() -> None:
    event("implementation_lock", "started")
    state_path = ART / "protocol_state.json"
    state = load_json(state_path)
    allowed_amendment = state.get("state") == "implementation_frozen_before_validation" and not (ART / "validation_results.csv").exists()
    if state.get("state") != "implemented_not_scored" and not allowed_amendment:
        raise RuntimeError(f"implementation already left initial state: {state.get('state')}")
    manifest = load_json(ART / "input_manifest.json")
    if manifest.get("status") != "complete":
        raise RuntimeError("input manifest is incomplete")
    views = load_json(ART / "development_views_manifest.json")
    graph = load_json(ART / "tactile_graph_report.json")
    dry = load_json(ART / "synthetic_dry_run.json")
    if dry.get("status") != "pass":
        raise RuntimeError("synthetic dry run did not pass")
    compile_cmd = [sys.executable, "-m", "py_compile", *METRIC_SOURCES]
    subprocess.run(compile_cmd, cwd=ROOT, check=True)
    source_hashes = {name: sha(ROOT / name) for name in METRIC_SOURCES}
    lock = {
        "status": "complete",
        "state_before_transition": state.get("state"),
        "amendment": (
            "pre-validation-metric runtime patch; no validation_results.csv or checkpoint existed"
            if allowed_amendment
            else None
        ),
        "protocol_sha256": sha(CONFIG / "protocol.json"),
        "model_variants_sha256": sha(CONFIG / "model_variants.json"),
        "input_manifest_sha256": sha(ART / "input_manifest.json"),
        "development_views_manifest_sha256": sha(ART / "development_views_manifest.json"),
        "tactile_graph_report_sha256": sha(ART / "tactile_graph_report.json"),
        "synthetic_dry_run_sha256": sha(ART / "synthetic_dry_run.json"),
        "metric_source_sha256": source_hashes,
        "unit_tests": "py_compile plus synthetic dry run; no official validation/test metric computed before this lock",
        "official_validation_metrics_computed_before_lock": False,
        "official_test_metrics_computed_before_lock": False,
        "train_rows": views["rows"]["train_events.parquet"],
        "validation_rows": views["rows"]["validation_events.parquet"],
        "tactile_graph_selected_nprobe": graph["selected_nprobe"],
    }
    save_json(ART / "implementation_lock.json", lock)
    if allowed_amendment:
        state.setdefault("history", []).append(
            {
                "from": "implementation_frozen_before_validation",
                "to": "implementation_frozen_before_validation",
                "reason": "pre-validation-metric implementation lock amendment",
                "implementation_lock_sha256": sha(ART / "implementation_lock.json"),
            }
        )
        save_json(state_path, state)
    else:
        transition_state(
            "implemented_not_scored",
            "implementation_frozen_before_validation",
            implementation_lock_sha256=sha(ART / "implementation_lock.json"),
        )
    event("implementation_lock", "complete", metric_sources=len(source_hashes))


if __name__ == "__main__":
    main()
