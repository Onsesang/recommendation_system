from __future__ import annotations

import json
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
    write_jsonl,
)
from .extract import _local_model_path, parse_extraction, render_prompt


LENSES = {
    "surface_use": ROOT / "prompts" / "span_extraction_v2_surface.txt",
    "behavior_care": ROOT / "prompts" / "span_extraction_v2_behavior.txt",
    "audit_gaps": ROOT / "prompts" / "span_extraction_v2_audit_gaps.txt",
}


def _select_reviews(
    reviews: list[dict[str, Any]],
    max_reviews: int | None,
    include_review_ids: set[str] | None,
) -> list[dict[str, Any]]:
    selected = reviews[:max_reviews] if max_reviews else list(reviews)
    selected_ids = {row["review_id"] for row in selected}
    wanted = include_review_ids or set()
    selected.extend(
        row
        for row in reviews
        if row["review_id"] in wanted and row["review_id"] not in selected_ids
    )
    return selected


def _merge_outputs(
    reviews: list[dict[str, Any]],
    lens_rows: list[dict[str, Any]],
    v1_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    lens_by_review: dict[str, list[dict[str, Any]]] = {}
    for row in lens_rows:
        lens_by_review.setdefault(row["review_id"], []).append(row)
    v1_by_review = {row["review_id"]: row for row in v1_rows}
    merged = []
    for review in reviews:
        sources_by_quote: dict[str, set[str]] = {}
        invalid_quotes = []
        v1 = v1_by_review.get(review["review_id"])
        if v1:
            for evidence in v1.get("evidence", []):
                sources_by_quote.setdefault(evidence["quote"], set()).add("v1")
        review_lenses = lens_by_review.get(review["review_id"], [])
        for lens_row in review_lenses:
            lens = lens_row["lens"]
            lens_quotes = sorted(
                (evidence["quote"] for evidence in lens_row.get("evidence", [])),
                key=lambda quote: (-len(quote), quote),
            )
            for quote in lens_quotes:
                # Only exact strings are duplicates. Containment is not enough:
                # "soft" and "soft and sheer" or "single layer" and a longer
                # warmth claim can encode different properties. The verifier can
                # reject redundant candidates without sacrificing recall.
                sources_by_quote.setdefault(quote, set()).add(lens)
            invalid_quotes.extend(
                {**invalid, "lens": lens}
                for invalid in lens_row.get("invalid_quotes", [])
            )
        ordered_quotes = sorted(
            sources_by_quote,
            key=lambda quote: (review["text"].find(quote), len(quote), quote),
        )
        evidence = [
            {"quote": quote, "sources": sorted(sources_by_quote[quote])}
            for quote in ordered_quotes
        ]
        complete_lenses = {row["lens"] for row in review_lenses}
        merged.append(
            {
                "review_id": review["review_id"],
                "asin": review["asin"],
                "user_id": review["user_id"],
                "text": review["text"],
                "status": "success"
                if complete_lenses == set(LENSES)
                else "incomplete",
                "evidence": evidence,
                "invalid_quotes": invalid_quotes,
                "returned_quote_count": sum(
                    row.get("returned_quote_count", 0) for row in review_lenses
                ),
                "lens_status": {
                    row["lens"]: row["status"] for row in review_lenses
                },
                "v1_span_count": len(v1.get("evidence", [])) if v1 else 0,
                "v2_union_span_count": len(evidence),
            }
        )
    return merged


def run_recall_extraction(
    batch_size: int = 6,
    max_attempts: int = 2,
    output_root: Path | None = None,
    max_reviews: int | None = None,
    include_review_ids: set[str] | None = None,
    input_path: Path | None = None,
) -> dict[str, Any]:
    import torch
    from tqdm import tqdm
    from transformers import AutoProcessor, BitsAndBytesConfig
    from transformers import Qwen3VLForConditionalGeneration

    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is required for Qwen3-VL recall extraction")

    cfg = load_config()
    root = output_root or ROOT / "data" / "v2"
    root.mkdir(parents=True, exist_ok=True)
    input_path = input_path or ROOT / "data" / "input" / "reviews_pilot.jsonl"
    reviews = _select_reviews(
        read_jsonl(input_path), max_reviews, include_review_ids
    )
    raw_path = root / "raw_generations.jsonl"
    lens_path = root / "lens_extractions.jsonl"
    output_path = root / "span_extractions.jsonl"
    run_path = root / "extraction_run.json"
    prompts = {
        lens: path.read_text(encoding="utf-8") for lens, path in LENSES.items()
    }

    existing_lens_rows = read_jsonl(lens_path)
    reusable_statuses = {"success", "partial_invalid_quote"}
    existing_by_key = {
        (row["review_id"], row["lens"]): row
        for row in existing_lens_rows
        if row.get("status") in reusable_statuses
    }
    selected_ids = {row["review_id"] for row in reviews}
    compacted = [
        row
        for key, row in existing_by_key.items()
        if key[0] in selected_ids and key[1] in LENSES
    ]
    compacted.sort(key=lambda row: (row["review_id"], row["lens"]))
    if len(compacted) != len(existing_lens_rows):
        write_jsonl(lens_path, compacted)
    tasks = [
        (review, lens)
        for review in reviews
        for lens in LENSES
        if (review["review_id"], lens) not in existing_by_key
    ]

    started = time.time()
    generated_tasks = 0
    if tasks:
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

        for start in tqdm(
            range(0, len(tasks), batch_size), desc="Qwen recall lenses"
        ):
            original_batch = tasks[start : start + batch_size]
            unresolved = list(original_batch)
            resolved: dict[tuple[str, str], dict[str, Any]] = {}
            best_partial: dict[tuple[str, str], dict[str, Any]] = {}
            for attempt in range(1, max_attempts + 1):
                if not unresolved:
                    break
                rendered = []
                for review, lens in unresolved:
                    prompt = render_prompt(
                        prompts[lens], review["review_id"], review["text"]
                    )
                    if attempt > 1:
                        prompt += (
                            "\nThe previous response failed exact-quote or JSON validation. "
                            "Rescan the full review and return valid JSON only. Copy every "
                            "quote exactly from REVIEW."
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
                        **tensors,
                        max_new_tokens=480,
                        do_sample=False,
                    )
                batch_seconds = time.time() - batch_started
                decoded = processor.batch_decode(
                    generated[:, tensors["input_ids"].shape[1] :],
                    skip_special_tokens=True,
                )
                retry = []
                raw_rows = []
                for (review, lens), raw_output in zip(unresolved, decoded):
                    key = (review["review_id"], lens)
                    parsed = parse_extraction(
                        raw_output.strip(),
                        review["review_id"],
                        review["text"],
                        max_items=20,
                    )
                    raw_rows.append(
                        {
                            "review_id": review["review_id"],
                            "lens": lens,
                            "attempt": attempt,
                            "raw_output": raw_output.strip(),
                            "validation_status": parsed["status"],
                            "latency_share_seconds": batch_seconds
                            / max(len(unresolved), 1),
                        }
                    )
                    if parsed["status"] == "partial_invalid_quote" and parsed.get(
                        "evidence"
                    ):
                        candidate = {
                            "review_id": review["review_id"],
                            "asin": review["asin"],
                            "user_id": review["user_id"],
                            "lens": lens,
                            **parsed,
                            "attempts": attempt,
                        }
                        previous = best_partial.get(key)
                        if previous is None or len(candidate["evidence"]) > len(
                            previous["evidence"]
                        ):
                            best_partial[key] = candidate
                    if parsed["status"] != "success" and attempt < max_attempts:
                        retry.append((review, lens))
                        continue
                    if (
                        parsed["status"] in {"parse_failure", "schema_failure"}
                        and key in best_partial
                    ):
                        resolved[key] = best_partial[key]
                    else:
                        resolved[key] = {
                            "review_id": review["review_id"],
                            "asin": review["asin"],
                            "user_id": review["user_id"],
                            "lens": lens,
                            **parsed,
                            "attempts": attempt,
                        }
                append_jsonl(raw_path, raw_rows)
                unresolved = retry
            batch_rows = [
                resolved[(review["review_id"], lens)]
                for review, lens in original_batch
            ]
            append_jsonl(lens_path, batch_rows)
            generated_tasks += len(batch_rows)
        del model
        torch.cuda.empty_cache()
        model_id = cfg["model_id"]
        model_path = _local_model_path(model_id)
    else:
        model_id = cfg["model_id"]
        model_path = _local_model_path(model_id)

    final_lens_rows = read_jsonl(lens_path)
    merged = _merge_outputs(
        reviews,
        final_lens_rows,
        read_jsonl(ROOT / "data" / "output" / "span_extractions.jsonl"),
    )
    write_jsonl(output_path, merged)
    elapsed = time.time() - started
    v1_total = sum(row["v1_span_count"] for row in merged)
    v2_total = sum(row["v2_union_span_count"] for row in merged)
    new_total = sum(
        max(0, row["v2_union_span_count"] - row["v1_span_count"]) for row in merged
    )
    run = {
        "status": "complete"
        if all(row["status"] == "success" for row in merged)
        else "incomplete",
        "model": model_id,
        "model_path": model_path,
        "prompt_version": "span_extraction_v2.1_three_lens_union_v1",
        "prompt_sha256": {
            lens: sha256_file(path) for lens, path in LENSES.items()
        },
        "input": str(input_path),
        "input_sha256": sha256_file(input_path),
        "reviews": len(reviews),
        "lenses": list(LENSES),
        "expected_tasks": len(reviews) * len(LENSES),
        "newly_generated_tasks": generated_tasks,
        "batch_size": batch_size,
        "max_attempts": max_attempts,
        "elapsed_seconds": elapsed,
        "v1_spans": v1_total,
        "v2_union_spans": v2_total,
        "new_spans_vs_v1": new_total,
        "reviews_with_v1_evidence": sum(row["v1_span_count"] > 0 for row in merged),
        "reviews_with_v2_evidence": sum(
            row["v2_union_span_count"] > 0 for row in merged
        ),
        "output": str(output_path),
        "output_sha256": sha256_file(output_path),
    }
    save_json(run_path, run)
    return run
