from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from .common import (
    ROOT,
    append_jsonl,
    load_config,
    read_jsonl,
    save_json,
    sha256_file,
    sha256_text,
    write_jsonl,
)
from .verify import (
    _local_model_path,
    apply_semantic_guardrails,
    parse_verification,
    render_verification_prompt,
)


def prepare_recall_verification(output_root: Path | None = None) -> dict[str, Any]:
    root = output_root or ROOT / "data" / "v2"
    source_path = root / "span_extractions.jsonl"
    rows = []
    source_rows = read_jsonl(source_path)
    for review in source_rows:
        for evidence in review["evidence"]:
            quote = evidence["quote"]
            rows.append(
                {
                    "span_id": sha256_text(f"{review['review_id']}\x1f{quote}")[:20],
                    "review_id": review["review_id"],
                    "asin": review["asin"],
                    "user_id": review["user_id"],
                    "quote": quote,
                    "review_text": review["text"],
                    "extraction_sources": evidence.get("sources", []),
                }
            )
    rows.sort(key=lambda row: (row["review_id"], row["span_id"]))
    if len({row["span_id"] for row in rows}) != len(rows):
        raise ValueError("span_id collision or duplicate v2 span")
    output_path = root / "semantic_verification_input.jsonl"
    write_jsonl(output_path, rows)
    manifest = {
        "input_spans": len(rows),
        "source_reviews": len(source_rows),
        "source_with_evidence": sum(bool(row["evidence"]) for row in source_rows),
        "source_path": str(source_path),
        "source_sha256": sha256_file(source_path),
        "output_path": str(output_path),
        "output_sha256": sha256_file(output_path),
        "protected_test_used": False,
    }
    save_json(root / "verification_input_manifest.json", manifest)
    return manifest


def run_recall_verification(
    batch_size: int = 8,
    max_attempts: int = 2,
    output_root: Path | None = None,
) -> dict[str, Any]:
    import torch
    from tqdm import tqdm
    from transformers import AutoProcessor, BitsAndBytesConfig
    from transformers import Qwen3VLForConditionalGeneration

    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is required for Qwen3-VL recall verification")
    cfg = load_config()
    root = output_root or ROOT / "data" / "v2"
    input_path = root / "semantic_verification_input.jsonl"
    output_path = root / "semantic_verifications.jsonl"
    raw_path = root / "semantic_verification_raw.jsonl"
    prompt_path = ROOT / "prompts" / "semantic_verification_v1_1.txt"
    inputs_all = read_jsonl(input_path)
    input_by_id = {row["span_id"]: row for row in inputs_all}
    input_ids = [row["span_id"] for row in inputs_all]

    current_rows = read_jsonl(output_path)
    existing_by_id = {row["span_id"]: row for row in current_rows}
    old_rows = read_jsonl(ROOT / "data" / "output" / "semantic_verifications.jsonl")
    reused = 0
    for row in old_rows:
        span_id = row["span_id"]
        if span_id not in input_by_id or span_id in existing_by_id:
            continue
        source = input_by_id[span_id]
        if row["quote"] != source["quote"] or row["review_id"] != source["review_id"]:
            continue
        existing_by_id[span_id] = {**row, "reused_from_v1": True}
        reused += 1
    compacted = [existing_by_id[span_id] for span_id in input_ids if span_id in existing_by_id]
    write_jsonl(output_path, compacted)
    pending = [row for row in inputs_all if row["span_id"] not in existing_by_id]

    started = time.time()
    if pending:
        model_id = cfg["model_id"]
        model_path = _local_model_path(model_id)
        quant = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_compute_dtype=torch.bfloat16,
            bnb_4bit_use_double_quant=True,
        )
        model = Qwen3VLForConditionalGeneration.from_pretrained(
            model_path,
            quantization_config=quant,
            device_map="auto",
            torch_dtype=torch.bfloat16,
            local_files_only=True,
        )
        processor = AutoProcessor.from_pretrained(model_path, local_files_only=True)
        processor.tokenizer.padding_side = "left"
        model.eval()
        template = prompt_path.read_text(encoding="utf-8")

        for start in tqdm(
            range(0, len(pending), batch_size), desc="Qwen v2 semantic verifier"
        ):
            original_batch = pending[start : start + batch_size]
            unresolved = list(original_batch)
            resolved: dict[str, dict[str, Any]] = {}
            for attempt in range(1, max_attempts + 1):
                if not unresolved:
                    break
                rendered = []
                for source in unresolved:
                    prompt = render_verification_prompt(template, source)
                    if attempt > 1:
                        prompt += (
                            "\nThe previous response failed strict schema validation. Return "
                            "exactly one valid JSON object and copy span_id and quote unchanged."
                        )
                    message = [
                        {"role": "user", "content": [{"type": "text", "text": prompt}]}
                    ]
                    rendered.append(
                        processor.apply_chat_template(
                            message, tokenize=False, add_generation_prompt=True
                        )
                    )
                tensors = processor(
                    text=rendered, padding=True, return_tensors="pt"
                ).to("cuda")
                batch_started = time.time()
                with torch.no_grad():
                    generated = model.generate(
                        **tensors, max_new_tokens=300, do_sample=False
                    )
                batch_seconds = time.time() - batch_started
                decoded = processor.batch_decode(
                    generated[:, tensors["input_ids"].shape[1] :],
                    skip_special_tokens=True,
                )
                retry = []
                raw_rows = []
                for source, raw_output in zip(unresolved, decoded):
                    parsed = apply_semantic_guardrails(
                        parse_verification(raw_output.strip(), source), source
                    )
                    raw_rows.append(
                        {
                            "span_id": source["span_id"],
                            "attempt": attempt,
                            "raw_output": raw_output.strip(),
                            "validation_status": parsed["status"],
                            "latency_share_seconds": batch_seconds
                            / max(len(unresolved), 1),
                        }
                    )
                    if parsed["status"] != "success" and attempt < max_attempts:
                        retry.append(source)
                        continue
                    resolved[source["span_id"]] = {
                        **source,
                        **parsed,
                        "attempts": attempt,
                        "reused_from_v1": False,
                    }
                append_jsonl(raw_path, raw_rows)
                unresolved = retry
            batch_rows = [resolved[row["span_id"]] for row in original_batch]
            append_jsonl(output_path, batch_rows)
        del model
        torch.cuda.empty_cache()
    final_by_id = {row["span_id"]: row for row in read_jsonl(output_path)}
    final_rows = [final_by_id[span_id] for span_id in input_ids]
    write_jsonl(output_path, final_rows)
    elapsed = time.time() - started
    successful = [row for row in final_rows if row.get("status") == "success"]
    run = {
        "status": "complete" if len(final_rows) == len(inputs_all) else "incomplete",
        "model": cfg["model_id"],
        "model_path": _local_model_path(cfg["model_id"]),
        "prompt_version": cfg["verification_prompt_version"],
        "prompt_sha256": sha256_file(prompt_path),
        "input_sha256": sha256_file(input_path),
        "input_spans": len(inputs_all),
        "reused_from_v1_this_run": reused,
        "total_reused_from_v1": sum(
            bool(row.get("reused_from_v1")) for row in final_rows
        ),
        "newly_processed_spans": len(pending),
        "schema_success": len(successful),
        "accepted": sum(bool(row.get("accepted")) for row in successful),
        "rejected": sum(not bool(row.get("accepted")) for row in successful),
        "semantic_guardrail_applied": sum(
            bool(row.get("semantic_guardrail")) for row in successful
        ),
        "elapsed_seconds": elapsed,
        "batch_size": batch_size,
        "max_attempts": max_attempts,
        "output": str(output_path),
        "output_sha256": sha256_file(output_path),
    }
    save_json(root / "verification_run.json", run)
    return run
