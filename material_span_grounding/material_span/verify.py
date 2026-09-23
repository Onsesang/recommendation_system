from __future__ import annotations

import json
import re
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
    sha256_text,
    write_jsonl,
)


ALLOWED = {
    "scope": {"main_fabric", "outer_surface", "lining", "component", "whole_garment", "unknown"},
    "property_status": {"present", "absent", "comparative", "uncertain", "mixed", "not_applicable"},
    "intensity": {"none", "slight", "moderate", "strong", "unknown"},
    "sentiment": {"positive", "negative", "neutral", "mixed", "unknown"},
    "evidence_basis": {"direct_touch", "worn_experience", "visual_only", "product_behavior", "unspecified"},
    "visual_observability": {"high", "medium", "low", "unknown"},
}

SEMANTIC_GUARDRAIL_VERSION = "semantic_guardrails_v1"


def apply_semantic_guardrails(
    parsed: dict[str, Any], source: dict[str, Any]
) -> dict[str, Any]:
    """Apply narrow deterministic boundaries after a valid model response.

    These rules encode explicit audit-policy boundaries, not span IDs or review
    IDs. They primarily prevent recurring vague/fit/color false positives and
    rescue unambiguous one-word concrete properties.
    """
    if parsed.get("status") != "success":
        return parsed
    quote = str(source.get("quote", "")).strip()
    normalized = re.sub(r"\s+", " ", quote.casefold())

    color_only = bool(
        re.search(r"\b(color|colour|gray|grey|red|white|black|blue|pink)\b", normalized)
        and not re.search(r"\b(fad|bleed|transfer|run|wash(?:ed)? out)\w*\b", normalized)
    )
    fit_or_position = bool(
        re.search(
            r"\b(sleeves? (?:are |is )?short|creep(?:ing)? down|rid(?:e|ing) down|"
            r"slid(?:e|ing) down|stay(?:s|ing)? up|adjust(?:ing|ed)?|skin touching skin|"
            r"more friction)\b",
            normalized,
        )
    )
    vague_only = bool(
        re.search(
            r"\b(nice feel|like (?:the way )?(?:the )?(?:fabric|material) feels|"
            r"cozy|flimsy|teetering stockings|messed up)\b",
            normalized,
        )
    )
    if color_only or fit_or_position or vague_only:
        if color_only:
            reason = "color/appearance without a concrete material behavior"
        elif fit_or_position:
            reason = "fit, garment position, or skin-to-skin friction without a material cause"
        else:
            reason = "vague evaluation without a concrete material property"
        return {
            **parsed,
            "accepted": False,
            "claim": "",
            "scope": "unknown",
            "property_status": "not_applicable",
            "intensity": "unknown",
            "sentiment": "unknown",
            "evidence_basis": "unspecified",
            "visual_observability": "unknown",
            "ambiguous": True,
            "rejection_reason": reason,
            "semantic_guardrail": SEMANTIC_GUARDRAIL_VERSION,
        }

    bare_properties = {
        "soft": ("main_fabric", "low"),
        "warm": ("whole_garment", "low"),
        "thin": ("main_fabric", "medium"),
        "thick": ("main_fabric", "medium"),
        "sheer": ("main_fabric", "high"),
        "lightweight": ("whole_garment", "medium"),
        "stretchy": ("main_fabric", "low"),
        "durable": ("whole_garment", "low"),
        "flowy": ("main_fabric", "medium"),
        "floppy": ("whole_garment", "medium"),
    }
    if normalized in bare_properties and parsed.get("accepted") is not True:
        scope, visibility = bare_properties[normalized]
        return {
            **parsed,
            "accepted": True,
            "claim": f"the garment is described as {normalized}",
            "scope": scope,
            "property_status": "present",
            "intensity": "none",
            "sentiment": "neutral",
            "evidence_basis": "unspecified",
            "visual_observability": visibility,
            "ambiguous": False,
            "rejection_reason": "",
            "semantic_guardrail": SEMANTIC_GUARDRAIL_VERSION,
        }
    return parsed


def _local_model_path(model_id: str) -> str:
    cache_root = Path.home() / ".cache" / "huggingface" / "hub"
    snapshots = cache_root / f"models--{model_id.replace('/', '--')}" / "snapshots"
    found = sorted(snapshots.iterdir()) if snapshots.exists() else []
    return str(found[-1]) if found else model_id


def prepare_verification_input() -> dict[str, Any]:
    source_path = ROOT / "data" / "output" / "span_extractions.jsonl"
    source_rows = read_jsonl(source_path)
    rows = []
    for review in source_rows:
        for evidence in review["evidence"]:
            quote = evidence["quote"]
            span_id = sha256_text(f"{review['review_id']}\x1f{quote}")[:20]
            rows.append(
                {
                    "span_id": span_id,
                    "review_id": review["review_id"],
                    "asin": review["asin"],
                    "user_id": review["user_id"],
                    "quote": quote,
                    "review_text": review["text"],
                }
            )
    rows.sort(key=lambda row: (row["review_id"], row["span_id"]))
    if len({row["span_id"] for row in rows}) != len(rows):
        raise ValueError("span_id collision or duplicate stage-1 span")
    output_path = ROOT / "data" / "input" / "semantic_verification_input.jsonl"
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
    save_json(ROOT / "data" / "manifests" / "verification_input_manifest.json", manifest)
    return manifest


def render_verification_prompt(template: str, row: dict[str, Any]) -> str:
    return (
        template.replace("__SPAN_ID__", row["span_id"])
        .replace("__QUOTE__", row["quote"])
        .replace("__REVIEW_TEXT__", row["review_text"])
    )


def parse_verification(output: str, source: dict[str, Any]) -> dict[str, Any]:
    start, end = output.find("{"), output.rfind("}")
    if start < 0 or end < start:
        return {"status": "parse_failure", "error": "JSON object not found"}
    try:
        row = json.loads(output[start : end + 1])
    except Exception as exc:
        return {"status": "parse_failure", "error": f"invalid JSON: {exc}"}
    if not isinstance(row, dict):
        return {"status": "schema_failure", "error": "output is not an object"}
    if row.get("span_id") != source["span_id"]:
        return {"status": "schema_failure", "error": "span_id mismatch"}
    if row.get("quote") != source["quote"]:
        return {"status": "schema_failure", "error": "quote changed"}
    if not isinstance(row.get("accepted"), bool) or not isinstance(row.get("ambiguous"), bool):
        return {"status": "schema_failure", "error": "accepted or ambiguous is not boolean"}
    if not isinstance(row.get("claim"), str) or not isinstance(row.get("rejection_reason"), str):
        return {"status": "schema_failure", "error": "claim or rejection_reason is not string"}
    for field, choices in ALLOWED.items():
        if row.get(field) not in choices:
            return {"status": "schema_failure", "error": f"invalid {field}"}
    if row["accepted"] and not row["claim"].strip():
        return {"status": "schema_failure", "error": "accepted item has empty claim"}
    if not row["accepted"] and row["property_status"] != "not_applicable":
        return {"status": "schema_failure", "error": "rejected item has material property status"}
    return {"status": "success", "error": "", **row}


def run_verification(batch_size: int = 8, max_attempts: int = 2) -> dict[str, Any]:
    import torch
    from tqdm import tqdm
    from transformers import AutoProcessor, BitsAndBytesConfig
    from transformers import Qwen3VLForConditionalGeneration

    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is required for Qwen3-VL verification")

    cfg = load_config()
    input_path = ROOT / "data" / "input" / "semantic_verification_input.jsonl"
    prompt_path = ROOT / "prompts" / "semantic_verification_v1_1.txt"
    output_path = ROOT / "data" / "output" / "semantic_verifications.jsonl"
    raw_path = ROOT / "data" / "output" / "semantic_verification_raw.jsonl"
    inputs_all = read_jsonl(input_path)
    existing_rows = read_jsonl(output_path)
    existing_by_id = {row["span_id"]: row for row in existing_rows}
    input_ids = [row["span_id"] for row in inputs_all]
    compacted = [existing_by_id[span_id] for span_id in input_ids if span_id in existing_by_id]
    if existing_rows and len(compacted) != len(existing_rows):
        write_jsonl(output_path, compacted)
    completed = set(existing_by_id) & set(input_ids)
    pending = [row for row in inputs_all if row["span_id"] not in completed]
    if not pending:
        return {
            "status": "already_complete",
            "input_spans": len(inputs_all),
            "completed_spans": len(completed),
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

    run_path = ROOT / "data" / "manifests" / "verification_run.json"
    previous = load_json(run_path) if run_path.exists() else None
    previous_elapsed = (
        float(previous.get("cumulative_elapsed_seconds", previous.get("elapsed_seconds", 0.0)))
        if previous
        else 0.0
    )
    started = time.time()
    final_rows = []
    for start in tqdm(range(0, len(pending), batch_size), desc="Qwen semantic verifier"):
        original_batch = pending[start : start + batch_size]
        unresolved = list(original_batch)
        resolved: dict[str, dict[str, Any]] = {}
        for attempt in range(1, max_attempts + 1):
            if not unresolved:
                break
            prompts = []
            for source in unresolved:
                prompt = render_verification_prompt(template, source)
                if attempt > 1:
                    prompt += (
                        "\nThe previous response failed strict schema validation. Return exactly "
                        "one valid JSON object and copy span_id and quote unchanged."
                    )
                message = [{"role": "user", "content": [{"type": "text", "text": prompt}]}]
                prompts.append(
                    processor.apply_chat_template(message, tokenize=False, add_generation_prompt=True)
                )
            tensors = processor(text=prompts, padding=True, return_tensors="pt").to("cuda")
            batch_started = time.time()
            with torch.no_grad():
                generated = model.generate(
                    **tensors,
                    max_new_tokens=300,
                    do_sample=False,
                )
            batch_seconds = time.time() - batch_started
            decoded = processor.batch_decode(
                generated[:, tensors["input_ids"].shape[1] :], skip_special_tokens=True
            )
            retry, raw_rows = [], []
            for source, raw_output in zip(unresolved, decoded):
                parsed = parse_verification(raw_output.strip(), source)
                raw_rows.append(
                    {
                        "span_id": source["span_id"],
                        "attempt": attempt,
                        "raw_output": raw_output.strip(),
                        "validation_status": parsed["status"],
                        "latency_share_seconds": batch_seconds / max(len(unresolved), 1),
                    }
                )
                if parsed["status"] != "success" and attempt < max_attempts:
                    retry.append(source)
                    continue
                resolved[source["span_id"]] = {
                    **source,
                    **parsed,
                    "attempts": attempt,
                }
            append_jsonl(raw_path, raw_rows)
            unresolved = retry
        batch_final = [resolved[row["span_id"]] for row in original_batch]
        append_jsonl(output_path, batch_final)
        final_rows.extend(batch_final)

    elapsed = time.time() - started
    run = {
        "status": "complete",
        "model": model_id,
        "model_path": model_path,
        "prompt_version": cfg["verification_prompt_version"],
        "prompt_sha256": sha256_file(prompt_path),
        "input_sha256": sha256_file(input_path),
        "batch_size": batch_size,
        "max_attempts": max_attempts,
        "input_spans": len(inputs_all),
        "newly_processed_spans": len(final_rows),
        "elapsed_seconds": elapsed,
        "cumulative_elapsed_seconds": previous_elapsed + elapsed,
        "output": str(output_path),
    }
    save_json(run_path, run)
    return run
