from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from .common import (
    ROOT,
    append_jsonl,
    load_config,
    load_json,
    read_jsonl,
    save_json,
    sha256_file,
    write_jsonl,
)


def _local_model_path(model_id: str) -> str:
    cache_root = Path.home() / ".cache" / "huggingface" / "hub"
    snapshots = cache_root / f"models--{model_id.replace('/', '--')}" / "snapshots"
    found = sorted(snapshots.iterdir()) if snapshots.exists() else []
    return str(found[-1]) if found else model_id


def render_prompt(template: str, review_id: str, review_text: str) -> str:
    return template.replace("__REVIEW_ID__", review_id).replace(
        "__REVIEW_TEXT__", review_text
    )


def parse_extraction(
    output: str, review_id: str, review_text: str, max_items: int = 10
) -> dict[str, Any]:
    start, end = output.find("{"), output.rfind("}")
    if start < 0 or end < start:
        return {
            "status": "parse_failure",
            "evidence": [],
            "invalid_quotes": [],
            "returned_quote_count": 0,
            "error": "JSON object not found",
        }
    try:
        payload = json.loads(output[start : end + 1])
    except Exception as exc:
        return {
            "status": "parse_failure",
            "evidence": [],
            "invalid_quotes": [],
            "returned_quote_count": 0,
            "error": f"invalid JSON: {exc}",
        }
    if not isinstance(payload, dict) or not isinstance(payload.get("evidence"), list):
        return {
            "status": "schema_failure",
            "evidence": [],
            "invalid_quotes": [],
            "returned_quote_count": 0,
            "error": "top-level object or evidence array is invalid",
        }
    if str(payload.get("review_id", "")) != review_id:
        return {
            "status": "schema_failure",
            "evidence": [],
            "invalid_quotes": [],
            "returned_quote_count": 0,
            "error": "review_id mismatch",
        }

    valid, invalid, seen = [], [], set()
    returned = 0
    for item in payload["evidence"][:max_items]:
        returned += 1
        quote = item.get("quote") if isinstance(item, dict) else item if isinstance(item, str) else None
        if not isinstance(quote, str) or not quote.strip():
            invalid.append({"quote": quote, "reason": "quote is not a non-empty string"})
            continue
        if quote not in review_text:
            invalid.append({"quote": quote, "reason": "not an exact substring"})
            continue
        if quote in seen:
            continue
        seen.add(quote)
        valid.append({"quote": quote})
    return {
        "status": "success" if not invalid else "partial_invalid_quote",
        "evidence": valid,
        "invalid_quotes": invalid,
        "returned_quote_count": returned,
        "error": "",
    }


def run_extraction(batch_size: int = 8, max_attempts: int = 2) -> dict[str, Any]:
    import torch
    from tqdm import tqdm
    from transformers import AutoProcessor, BitsAndBytesConfig
    from transformers import Qwen3VLForConditionalGeneration

    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is required for Qwen3-VL extraction")

    cfg = load_config()
    input_path = ROOT / "data" / "input" / "reviews_pilot.jsonl"
    prompt_path = ROOT / "prompts" / "span_extraction_v1.txt"
    raw_path = ROOT / "data" / "output" / "raw_generations.jsonl"
    output_path = ROOT / "data" / "output" / "span_extractions.jsonl"
    reviews = read_jsonl(input_path)
    existing_rows = read_jsonl(output_path)
    existing_by_id = {row["review_id"]: row for row in existing_rows}
    input_ids = [row["review_id"] for row in reviews]
    compacted_rows = [existing_by_id[review_id] for review_id in input_ids if review_id in existing_by_id]
    if existing_rows and len(compacted_rows) != len(existing_rows):
        write_jsonl(output_path, compacted_rows)
    completed = set(existing_by_id) & set(input_ids)
    pending = [row for row in reviews if row["review_id"] not in completed]

    if not pending:
        return {
            "status": "already_complete",
            "input_reviews": len(reviews),
            "completed_reviews": len(completed),
            "output": str(output_path),
        }

    template = prompt_path.read_text(encoding="utf-8")
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

    previous_run_path = ROOT / "data" / "manifests" / "extraction_run.json"
    previous_run = load_json(previous_run_path) if previous_run_path.exists() else None
    previous_elapsed = (
        float(
            previous_run.get(
                "cumulative_elapsed_seconds", previous_run.get("elapsed_seconds", 0.0)
            )
        )
        if previous_run
        else 0.0
    )
    started = time.time()
    final_rows: list[dict[str, Any]] = []
    for start in tqdm(range(0, len(pending), batch_size), desc="Qwen exact spans"):
        original_batch = pending[start : start + batch_size]
        unresolved = list(original_batch)
        resolved: dict[str, dict[str, Any]] = {}
        for attempt in range(1, max_attempts + 1):
            if not unresolved:
                break
            rendered = []
            for row in unresolved:
                prompt = render_prompt(template, row["review_id"], row["text"])
                if attempt > 1:
                    prompt += (
                        "\nYour previous response failed strict validation. Return the required "
                        "JSON object only. Every quote must be copied exactly from REVIEW."
                    )
                message = [
                    {"role": "user", "content": [{"type": "text", "text": prompt}]}
                ]
                rendered.append(
                    processor.apply_chat_template(
                        message, tokenize=False, add_generation_prompt=True
                    )
                )
            inputs = processor(text=rendered, padding=True, return_tensors="pt").to("cuda")
            batch_started = time.time()
            with torch.no_grad():
                generated = model.generate(
                    **inputs,
                    max_new_tokens=240,
                    do_sample=False,
                )
            batch_seconds = time.time() - batch_started
            decoded = processor.batch_decode(
                generated[:, inputs["input_ids"].shape[1] :],
                skip_special_tokens=True,
            )
            retry = []
            raw_rows = []
            for row, raw_output in zip(unresolved, decoded):
                parsed = parse_extraction(raw_output.strip(), row["review_id"], row["text"])
                raw_rows.append(
                    {
                        "review_id": row["review_id"],
                        "attempt": attempt,
                        "raw_output": raw_output.strip(),
                        "validation_status": parsed["status"],
                        "latency_share_seconds": batch_seconds / max(len(unresolved), 1),
                    }
                )
                if parsed["status"] in {"parse_failure", "schema_failure"} and attempt < max_attempts:
                    retry.append(row)
                    continue
                resolved[row["review_id"]] = {
                    "review_id": row["review_id"],
                    "asin": row["asin"],
                    "user_id": row["user_id"],
                    "text": row["text"],
                    "status": parsed["status"],
                    "evidence": parsed["evidence"],
                    "invalid_quotes": parsed["invalid_quotes"],
                    "returned_quote_count": parsed["returned_quote_count"],
                    "error": parsed["error"],
                    "attempts": attempt,
                }
            append_jsonl(raw_path, raw_rows)
            unresolved = retry

        batch_final = [resolved[row["review_id"]] for row in original_batch]
        append_jsonl(output_path, batch_final)
        final_rows.extend(batch_final)

    elapsed = time.time() - started
    run = {
        "status": "complete",
        "model": model_id,
        "model_path": model_path,
        "prompt_version": cfg["prompt_version"],
        "prompt_sha256": sha256_file(prompt_path),
        "input_sha256": sha256_file(input_path),
        "batch_size": batch_size,
        "max_attempts": max_attempts,
        "input_reviews": len(reviews),
        "newly_processed_reviews": len(final_rows),
        "elapsed_seconds": elapsed,
        "cumulative_elapsed_seconds": previous_elapsed + elapsed,
        "output": str(output_path),
    }
    save_json(ROOT / "data" / "manifests" / "extraction_run.json", run)
    return run
