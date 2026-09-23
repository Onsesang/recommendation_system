#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import time
from pathlib import Path
from typing import Any

import torch
from transformers import AutoProcessor, BitsAndBytesConfig, Qwen3VLForConditionalGeneration

ROOT = Path(__file__).resolve().parents[1]


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def iter_jsonl(path: Path):
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                yield json.loads(line)


def source_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def prompt(row: dict[str, Any], classes: list[str]) -> str:
    review = str(row.get("review_text", ""))[:1800]
    quote = str(row.get("quote") or row.get("claim") or "")
    allowed = ", ".join(classes)
    return f"""You are a conservative tactile evidence annotator.
Allowed atomic classes: {allowed}.
Label only material/garment tactile properties explicitly stated in QUOTE and
supported by CONTEXT. Do not infer from product type. Comfort, fit, quality,
appearance, temperature of the environment, and bodily sensation are not
material tactile evidence unless an allowed class is stated unambiguously.
For negation such as 'not soft', output soft with polarity absent; do not infer
firm. Multiple explicit classes are allowed. Missing evidence is not negative.
Return only compact JSON. Use c=[class, polarity, confidence] and u=unmappable:
{{"c":[["soft","p",0.90]],"u":false}}
Polarity must be p (present) or a (absent).
Use an empty classes list and unmappable=true when nothing is safely mappable.
QUOTE: {quote}
CONTEXT: {review}"""


def parse_json(text: str, allowed: set[str]) -> tuple[list[dict[str, Any]], bool, str | None]:
    candidate = text.strip().replace("```json", "").replace("```", "")
    match = re.search(r"\{.*\}", candidate, flags=re.S)
    if not match:
        return [], True, "missing_json"
    try:
        payload = json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        return [], True, f"json_error:{exc.msg}"
    results = []
    seen = set()
    items = payload.get("classes", payload.get("c", []))
    for item in items:
        if isinstance(item, list) and len(item) >= 3:
            class_id, polarity, raw_confidence = item[0], item[1], item[2]
        elif isinstance(item, dict):
            class_id, polarity, raw_confidence = item.get("id", ""), item.get("polarity", ""), item.get("confidence", 0.0)
        else:
            continue
        class_id = str(class_id).strip().lower()
        polarity = {"p": "present", "a": "absent"}.get(str(polarity).strip().lower(), str(polarity).strip().lower())
        try:
            confidence = min(1.0, max(0.0, float(raw_confidence)))
        except (TypeError, ValueError):
            continue
        if class_id not in allowed or polarity not in {"present", "absent"}:
            continue
        key = (class_id, polarity)
        if key not in seen:
            seen.add(key)
            results.append({"id": class_id, "polarity": polarity, "confidence": confidence})
    return results, bool(payload.get("unmappable", payload.get("u", not results))), None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int)
    parser.add_argument("--batch-size", type=int)
    args = parser.parse_args()
    config = read_json(ROOT / "config.json")
    output = ROOT / "artifacts" / "class_groundings.jsonl"
    output.parent.mkdir(parents=True, exist_ok=True)
    completed = {str(row["span_id"]) for row in iter_jsonl(output)} if output.exists() else set()
    candidates = [row for row in iter_jsonl(Path(config["candidate_file"])) if str(row["span_id"]) not in completed]
    if args.limit is not None:
        candidates = candidates[: args.limit]
    if not candidates:
        print("No pending candidates")
        return 0

    qcfg = config["qwen"]
    quant = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.bfloat16,
        bnb_4bit_use_double_quant=True,
    )
    model = Qwen3VLForConditionalGeneration.from_pretrained(
        qcfg["snapshot"], quantization_config=quant, device_map="auto",
        torch_dtype=torch.bfloat16, local_files_only=True, low_cpu_mem_usage=True,
    ).eval()
    processor = AutoProcessor.from_pretrained(qcfg["snapshot"], local_files_only=True)
    processor.tokenizer.padding_side = "left"
    batch_size = args.batch_size or int(qcfg["batch_size"])
    allowed = set(config["classes"])
    started = time.time()
    written = 0
    with output.open("a", encoding="utf-8") as handle:
        for start in range(0, len(candidates), batch_size):
            rows = candidates[start : start + batch_size]
            texts = []
            for row in rows:
                messages = [{"role": "user", "content": [{"type": "text", "text": prompt(row, config["classes"])}]}]
                texts.append(processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True))
            inputs = processor(
                text=texts, padding=True, truncation=True,
                max_length=int(qcfg["max_input_tokens"]), return_tensors="pt",
            ).to(model.device)
            with torch.inference_mode():
                generated = model.generate(
                    **inputs, max_new_tokens=int(qcfg["max_new_tokens"]),
                    do_sample=False, use_cache=True,
                )
            prompt_length = inputs.input_ids.shape[1]
            decoded = processor.batch_decode(generated[:, prompt_length:], skip_special_tokens=True)
            for row, raw in zip(rows, decoded):
                labels, unmappable, error = parse_json(raw, allowed)
                record = {
                    **row,
                    "class_labels": labels,
                    "class_unmappable": unmappable,
                    "class_parse_error": error,
                    "class_raw_output": raw,
                    "class_schema_version": "atomic_tactile_multilabel_v1",
                    "model_id": qcfg["model_id"],
                    "model_revision": qcfg["revision"],
                    "quantization": qcfg["quantization"],
                }
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
                written += 1
            handle.flush()
            os.fsync(handle.fileno())
            done = len(completed) + written
            elapsed = max(time.time() - started, 1e-6)
            print(f"grounded={done} pending={len(candidates)-written} rate={written/elapsed:.2f}/s", flush=True)

    manifest = {
        "status": "complete" if args.limit is None else "limited_run",
        "source": config["candidate_file"],
        "source_sha256": source_sha256(Path(config["candidate_file"])),
        "records": len(completed) + written,
        "model_id": qcfg["model_id"],
        "revision": qcfg["revision"],
        "quantization": qcfg["quantization"],
        "output": str(output),
    }
    (ROOT / "manifests").mkdir(exist_ok=True)
    (ROOT / "manifests" / "ground_classes.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
