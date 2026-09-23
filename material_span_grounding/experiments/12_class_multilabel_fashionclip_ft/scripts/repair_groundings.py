#!/usr/bin/env python3
from __future__ import annotations

import json
import os
from pathlib import Path

import torch
from transformers import AutoProcessor, BitsAndBytesConfig, Qwen3VLForConditionalGeneration

from ground_classes import parse_json, prompt

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    config = json.loads((ROOT / "config.json").read_text())
    path = ROOT / "artifacts" / "class_groundings.jsonl"
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    pending = [index for index, row in enumerate(records) if row.get("class_parse_error")]
    if not pending:
        (ROOT / "manifests" / "repair_groundings.json").write_text(json.dumps({"status": "complete", "repaired": 0}, indent=2) + "\n")
        print("No parse errors to repair"); return 0
    qcfg = config["qwen"]
    quant = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_compute_dtype=torch.bfloat16, bnb_4bit_use_double_quant=True)
    model = Qwen3VLForConditionalGeneration.from_pretrained(qcfg["snapshot"], quantization_config=quant, device_map="auto", torch_dtype=torch.bfloat16, local_files_only=True).eval()
    processor = AutoProcessor.from_pretrained(qcfg["snapshot"], local_files_only=True); processor.tokenizer.padding_side = "left"
    allowed = set(config["classes"]); repaired = 0; batch_size = 32
    for start in range(0, len(pending), batch_size):
        indices = pending[start:start + batch_size]; texts = []
        for index in indices:
            messages = [{"role": "user", "content": [{"type": "text", "text": prompt(records[index], config["classes"])}]}]
            texts.append(processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True))
        inputs = processor(text=texts, padding=True, truncation=True, max_length=int(qcfg["max_input_tokens"]), return_tensors="pt").to(model.device)
        with torch.inference_mode():
            generated = model.generate(**inputs, max_new_tokens=192, do_sample=False, use_cache=True)
        decoded = processor.batch_decode(generated[:, inputs.input_ids.shape[1]:], skip_special_tokens=True)
        for index, raw in zip(indices, decoded):
            labels, unmappable, error = parse_json(raw, allowed)
            records[index]["class_labels"] = labels; records[index]["class_unmappable"] = unmappable
            records[index]["class_parse_error"] = error; records[index]["class_raw_output"] = raw
            records[index]["repair_attempted"] = True
            if error is None: repaired += 1
    remaining = sum(row.get("class_parse_error") is not None for row in records)
    temporary = path.with_suffix(".jsonl.repaired")
    with temporary.open("w", encoding="utf-8") as handle:
        for row in records: handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        handle.flush(); os.fsync(handle.fileno())
    temporary.replace(path)
    status = "complete" if remaining == 0 else "failed"
    (ROOT / "manifests" / "repair_groundings.json").write_text(json.dumps({"status": status, "repaired": repaired, "remaining": remaining}, indent=2) + "\n")
    if remaining: raise RuntimeError(f"{remaining} parse errors remain after repair")
    return 0


if __name__ == "__main__": raise SystemExit(main())
