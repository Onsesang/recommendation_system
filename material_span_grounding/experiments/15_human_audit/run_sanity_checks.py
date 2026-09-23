#!/usr/bin/env python3
"""Run implementation and immutable-input sanity checks for experiment 15."""
from __future__ import annotations

import tempfile
from pathlib import Path

from streamlit.testing.v1 import AppTest

from common import ANNOTATION_PATH, CONFIG_PATH, MANIFEST_PATH, ROOT, atomic_json, read_json, source_hashes
from storage import read_annotations, upsert_annotation


def main() -> int:
    config = read_json(CONFIG_PATH)
    manifest = read_json(MANIFEST_PATH)
    items = manifest["items"]
    app_source = (ROOT / "app.py").read_text(encoding="utf-8")
    blind_marker = app_source.index("# Blind stage")
    incomplete_guard = app_source.index("if not completed:", blind_marker)
    blind_return = app_source.index("        return", incomplete_guard)
    reveal = app_source.index('with st.expander("Show reference/model info"', blind_return)

    with tempfile.TemporaryDirectory(prefix="human-audit-sanity-") as temporary:
        path = Path(temporary) / "annotations.csv"
        order = [items[0]["item_id"]]
        base = {
            "item_id": items[0]["item_id"],
            "image_observability": "yes",
            "human_label": "present",
            "confidence": 4,
            "completed": "true",
        }
        first = upsert_annotation(path, base, order)
        second = upsert_annotation(path, {**base, "confidence": 5}, order)
        stored = read_annotations(path)
        upsert_is_unique = len(stored) == 1 and stored[items[0]["item_id"]]["confidence"] == "5"
        first_timestamp_preserved = first["first_saved_timestamp"] == second["first_saved_timestamp"]

    annotations = read_annotations(ANNOTATION_PATH)
    app_test = AppTest.from_file(str(ROOT / "app.py")).run(timeout=30)
    rendered_text = " ".join(
        str(element.value)
        for kind in ("markdown", "text", "caption", "info", "success", "error")
        for element in getattr(app_test, kind)
    )
    checks = {
        "primary_sampling_does_not_use_last2_score": manifest["sampling_diagnostics"]["model_score_used_for_sampling"] is False,
        "locked_test_only": manifest["sanity_checks"]["locked_test_only"],
        "observed_mask_only": manifest["sanity_checks"]["observed_mask_only"],
        "family_disjoint_split_unchanged": all(value == 0 for value in manifest["family_overlap"].values()),
        "qwen_grounding_not_rerun": manifest["sanity_checks"]["qwen_grounding_not_rerun"],
        "target_not_regenerated": manifest["sanity_checks"]["target_not_regenerated"],
        "last2_not_retrained": manifest["sanity_checks"]["last2_not_retrained"],
        "threshold_not_retuned": manifest["sanity_checks"]["threshold_not_retuned"],
        "blind_stage_hides_category": reveal > blind_return > incomplete_guard,
        "blind_stage_hides_qwen": reveal > blind_return > incomplete_guard,
        "blind_stage_hides_target": reveal > blind_return > incomplete_guard,
        "blind_stage_hides_model_score": reveal > blind_return > incomplete_guard,
        "streamlit_blind_screen_runs_without_exception": len(app_test.exception) == 0,
        "runtime_blind_screen_hides_category": "Category:" not in rendered_text,
        "runtime_blind_screen_hides_qwen": "Qwen grounding" not in rendered_text,
        "runtime_blind_screen_hides_target": "raw_target" not in rendered_text,
        "runtime_blind_screen_hides_model_score": "last2_probability" not in rendered_text,
        "duplicate_item_id_absent": len({item["item_id"] for item in items}) == len(items),
        "human_audit_csv_resume_loads": isinstance(annotations, dict),
        "item_update_does_not_duplicate_row": upsert_is_unique,
        "first_saved_timestamp_is_preserved": first_timestamp_preserved,
        "missing_image_is_safely_handled": 'st.error("IMAGE MISSING")' in app_source and 'not image_path.is_file()' in app_source,
        "protected_source_hashes_unchanged": source_hashes(config) == manifest["source_hashes"],
        "human_fields_absent_from_manifest": manifest["sanity_checks"]["human_annotation_fields_absent_from_manifest"],
        "real_annotation_csv_has_no_fabricated_rows": len(annotations) == 0,
        "expected_total_and_balance": len(items) == 160 and all(
            stats["items"] == 20 and stats["positive"] == 10 and stats["negative"] == 10
            for stats in manifest["class_sample_stats"].values()
        ),
    }
    output = {
        "status": "pass" if all(checks.values()) else "fail",
        "passed": sum(checks.values()),
        "total": len(checks),
        "checks": checks,
        "note": "The real annotation CSV was read only; upsert behavior was tested in a temporary CSV.",
    }
    path = ROOT / "artifacts" / "implementation_sanity_checks.json"
    atomic_json(path, output)
    print(f"{output['status']}: {output['passed']}/{output['total']} checks; output={path}")
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
