#!/usr/bin/env python3
"""PART B - same pseudo-labelling task as 03, executed through vLLM.

Prompt construction and response parsing are imported from 03 so the two
backends cannot drift apart. Output is append-only and resumable.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("HF_HOME", "/home/user/onsesang/.cache/huggingface")
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("VLLM_WORKER_MULTIPROC_METHOD", "spawn")

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))

_spec = importlib.util.spec_from_file_location("pseudolabel_hf", SCRIPTS / "03_qwen_pseudolabel.py")
_hf = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_hf)

from common import ROOT, load_config  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int)
    parser.add_argument("--chunk-size", type=int, default=2048)
    parser.add_argument("--max-model-len", type=int, default=2048)
    parser.add_argument("--gpu-memory-utilization", type=float, default=0.92)
    parser.add_argument("--quantization", default="none", choices=["none", "bitsandbytes"])
    args = parser.parse_args()

    config = load_config()
    qcfg = config["retraining"]["qwen"]

    output = ROOT / "artifacts" / "qwen_fabricvst_labels.jsonl"
    output.parent.mkdir(parents=True, exist_ok=True)
    completed = {str(row["review_id"]) for row in _hf.iter_jsonl(output)} if output.exists() else set()

    reviews = [
        row for row in _hf.iter_jsonl(Path(config["retraining"]["review_pool"]))
        if str(row["review_id"]) not in completed
    ]
    if args.limit is not None:
        reviews = reviews[: args.limit]
    reviews.sort(key=lambda row: len(str(row.get("text", ""))))
    print(f"pending={len(reviews)} completed={len(completed)}", flush=True)
    if not reviews:
        print("nothing to do")
        return 0

    from transformers import AutoProcessor
    from vllm import LLM, SamplingParams

    processor = AutoProcessor.from_pretrained(qcfg["snapshot"], local_files_only=True)
    llm_kwargs = dict(
        model=qcfg["snapshot"],
        dtype="bfloat16",
        max_model_len=args.max_model_len,
        gpu_memory_utilization=args.gpu_memory_utilization,
        enforce_eager=True,
        seed=42,
        limit_mm_per_prompt={"image": 0, "video": 0},
    )
    if args.quantization == "bitsandbytes":
        llm_kwargs.update(quantization="bitsandbytes", load_format="bitsandbytes")
    llm = LLM(**llm_kwargs)
    sampling = SamplingParams(temperature=0.0, max_tokens=int(qcfg["max_new_tokens"]), seed=42)

    started = time.time()
    written = 0
    with output.open("a", encoding="utf-8") as handle:
        for start in range(0, len(reviews), args.chunk_size):
            chunk = reviews[start : start + args.chunk_size]
            rendered = []
            for row in chunk:
                review_text = str(row.get("text", ""))[: int(qcfg["max_input_tokens"]) * 4]
                messages = [
                    {"role": "system", "content": [{"type": "text", "text": _hf.SYSTEM}]},
                    {"role": "user", "content": [{"type": "text", "text": _hf.build_prompt(review_text)}]},
                ]
                rendered.append(
                    processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
                )
            outputs = llm.generate(rendered, sampling, use_tqdm=False)
            for row, output_row in zip(chunk, outputs):
                response = output_row.outputs[0].text.strip()
                review_text = str(row.get("text", ""))
                attributes, unmapped, error = _hf.parse_response(response, review_text)
                handle.write(json.dumps({
                    "review_id": row["review_id"],
                    "asin": row["asin"],
                    "prompt_version": _hf.PROMPT_VERSION,
                    "attributes": attributes,
                    "unmapped": unmapped,
                    "parse_error": error,
                }, ensure_ascii=False) + "\n")
                written += 1
            handle.flush()
            done = start + len(chunk)
            rate = done / max(time.time() - started, 1e-6)
            print(
                f"{done}/{len(reviews)} rate={rate:.2f}/s eta={(len(reviews)-done)/max(rate,1e-6)/3600:.2f}h",
                flush=True,
            )

    manifest = {
        "status": "complete",
        "backend": "vllm",
        "quantization": args.quantization,
        "prompt_version": _hf.PROMPT_VERSION,
        "prompt_sha256": hashlib.sha256(
            (ROOT / "prompts" / "fabricvst_tactile_pseudolabel.md").read_bytes()
        ).hexdigest(),
        "model_id": qcfg["model_id"],
        "revision": qcfg["revision"],
        "records_written": written,
        "output": str(output),
    }
    (ROOT / "manifests" / "03_qwen_pseudolabel.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
