from __future__ import annotations

import csv
import hashlib
from pathlib import Path
from typing import Any

from .common import PATHS, load_experiment, read_jsonl, sha256_file, utc_now, write_json


def record_skipped_human_audit() -> dict[str, Any]:
    config = load_experiment()
    rows = [row for row in read_jsonl(PATHS.artifacts / "axis_groundings.jsonl") if row.get("status") == "success"]
    size = min(int(config["diagnostics"]["audit_sample_size"]), len(rows))
    sample = sorted(rows, key=lambda row: hashlib.sha256(str(row["span_id"]).encode()).hexdigest())[:size]
    output = PATHS.artifacts / "human_axis_audit_pending.csv"
    fields = ["span_id", "asin", "review_id", "quote", "qwen_mappable", "qwen_axis", "qwen_direction", "qwen_intensity", "qwen_scope", "human_mappable", "human_axis", "human_direction", "human_intensity", "human_scope", "human_notes"]
    with output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in sample:
            writer.writerow({
                "span_id": row["span_id"], "asin": row["asin"], "review_id": row["review_id"], "quote": row["quote"],
                "qwen_mappable": row.get("mappable"), "qwen_axis": row.get("axis_id"), "qwen_direction": row.get("direction"),
                "qwen_intensity": row.get("intensity"), "qwen_scope": row.get("scope"),
                "human_mappable": "", "human_axis": "", "human_direction": "", "human_intensity": "", "human_scope": "", "human_notes": "",
            })
    manifest = {
        "status": "skipped_by_user_pending", "phase": 4, "generated_at": utc_now(),
        "human_validation_complete": False, "sample_rows": size,
        "reason": "User requested that the experiment continue without human validation for now.",
        "scientific_boundary": "Downstream results use Qwen pseudo-labels and cannot be described as human-validated ground truth.",
        "output": str(output), "output_sha256": sha256_file(output),
    }
    write_json(PATHS.manifests / "phase4_human_audit.json", manifest)
    write_json(PATHS.artifacts / "phase4_human_audit_metrics.json", manifest)
    (PATHS.reports / "phase4_human_audit.md").write_text(
        "# Phase 4 — Human audit pending\n\n사람 검증은 사용자 요청에 따라 이번 실행에서 건너뛰었다. "
        "빈 human 필드를 가진 고정 표본을 남겼으며, 이후 사람이 채우기 전까지 모든 결과는 Qwen pseudo-label 기반이다.\n",
        encoding="utf-8",
    )
    return manifest
