#!/usr/bin/env python3
"""Retry strict-schema vLLM verification failures and refresh final reports."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from material_span.common import ROOT, append_jsonl, load_json, read_jsonl, save_json, sha256_file, write_jsonl
from material_span.verify import (
    apply_semantic_guardrails,
    parse_verification,
    render_verification_prompt,
)
from material_span.vllm_pipeline import VLLMRunner, build_final_report


TARGET_ROOT = ROOT / "data" / "vllm" / "dense_500" / "v2"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target-root", type=Path, default=TARGET_ROOT)
    args = parser.parse_args()
    target_root = args.target_root.resolve()
    output_path = target_root / "semantic_verifications.jsonl"
    raw_path = target_root / "semantic_verification_raw.jsonl"
    run_path = target_root / "verification_run.json"
    rows = read_jsonl(output_path)
    failures = [row for row in rows if row.get("status") != "success"]
    if not failures:
        print(json.dumps({"status": "already_complete", "failures": 0}))
        return

    template = (ROOT / "prompts" / "semantic_verification_v1_1.txt").read_text(
        encoding="utf-8"
    )
    runner = VLLMRunner(chunk_size=1)
    repaired: dict[str, dict] = {}
    started = time.time()
    for source in failures:
        prompt = render_verification_prompt(template, source)
        prompt += (
            "\nCRITICAL IDENTIFIER COPY CHECK: The required span_id is exactly "
            f'\"{source["span_id"]}\". Copy all 20 characters from this line without '
            "transposing, deleting, or replacing any character. Return one JSON object only."
        )
        decoded, seconds = runner.generate([prompt], 300)
        raw = decoded[0]
        parsed = apply_semantic_guardrails(parse_verification(raw, source), source)
        append_jsonl(
            raw_path,
            [
                {
                    "span_id": source["span_id"],
                    "attempt": int(source.get("attempts", 2)) + 1,
                    "raw_output": raw,
                    "validation_status": parsed["status"],
                    "latency_share_seconds": seconds,
                    "backend": "vllm",
                    "targeted_retry": True,
                }
            ],
        )
        if parsed["status"] != "success":
            raise RuntimeError(
                f"Targeted retry still failed for {source['span_id']}: {parsed['error']}"
            )
        repaired[source["span_id"]] = {
            **source,
            **parsed,
            "attempts": int(source.get("attempts", 2)) + 1,
            "backend": "vllm",
            "targeted_retry": True,
        }

    final_rows = [repaired.get(row["span_id"], row) for row in rows]
    write_jsonl(output_path, final_rows)
    successful = [row for row in final_rows if row.get("status") == "success"]
    run = load_json(run_path)
    run.update(
        {
            "status": "complete" if len(successful) == len(final_rows) else "incomplete",
            "schema_success": len(successful),
            "accepted": sum(row.get("accepted") is True for row in successful),
            "rejected": sum(row.get("accepted") is False for row in successful),
            "targeted_retries": len(repaired),
            "targeted_retry_elapsed_seconds": time.time() - started,
            "output_sha256": sha256_file(output_path),
        }
    )
    save_json(run_path, run)
    if target_root == TARGET_ROOT.resolve():
        build_final_report()
    print(
        json.dumps(
            {
                "status": run["status"],
                "repaired": len(repaired),
                "schema_success": len(successful),
                "output_sha256": run["output_sha256"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
