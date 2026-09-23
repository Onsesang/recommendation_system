#!/usr/bin/env python3
"""PART B - relabel raw reviews against the FabricVST attribute vocabulary.

Append-only and resumable: completed review ids are skipped on restart. The
prompt is frozen in prompts/fabricvst_tactile_pseudolabel.md; its version string
is written into every row.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path

os.environ.setdefault("HF_HOME", "/home/user/onsesang/.cache/huggingface")
os.environ.setdefault("HF_HUB_OFFLINE", "1")

import torch  # noqa: E402
from transformers import AutoProcessor, BitsAndBytesConfig, Qwen3VLForConditionalGeneration  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import ROOT, load_config  # noqa: E402

PROMPT_VERSION = "fabricvst_tactile_pseudolabel_v1"

ATTRIBUTES = [
    "stiff", "soft", "rough", "smooth", "thick", "thin", "cool", "warm",
    "fluffy", "heavy", "delicate", "durable", "stretchable", "absorbent",
    "holey", "flat", "bumpy", "patterned", "striped", "shinny", "hairy",
    "embroidered", "jacquard", "pigment printed",
]

GLOSSES = {
    "absorbent": "Absorbent material soaks up liquid easily",
    "embroidered": "the design is stitched into the fabric after weaving, by machine",
    "jacquard": "the design is incorporated into the weave, woven with different colours of yarn",
    "pigment printed": "the pattern is printed onto the fabric after it is finished",
}

SYSTEM = (
    "You are annotating tactile and physical properties explicitly supported by a "
    "clothing review.\n\n"
    "Do not infer properties only from the product category.\n\n"
    "For every FabricVST attribute, return positive, negative, or unknown.\n\n"
    "Use unknown whenever the review does not contain enough evidence.\n\n"
    "Multiple attributes may be positive simultaneously.\n\n"
    "These labels are multi-label attributes, not mutually exclusive classes."
)

ALLOWED = set(ATTRIBUTES)


def build_prompt(review_text: str) -> str:
    vocabulary = ", ".join(ATTRIBUTES)
    gloss_lines = "\n".join(f"- {name}: {text}" for name, text in GLOSSES.items())
    return f"""Attribute vocabulary (use these exact names):
{vocabulary}

Definitions supplied by the dataset:
{gloss_lines}

Read the REVIEW and decide, for each attribute you can justify, whether the review
gives evidence that the garment's material HAS the property (positive) or does NOT
have it (negative).

Rules:
- Judge the material or fabric of the garment, not the fit, the sizing, the price,
  the delivery, the colour preference, or the wearer's mood.
- Report an attribute only when the review contains explicit or strongly implied
  linguistic evidence for it. Silence is not evidence.
- Never infer an attribute from the product type alone. "It is denim" is not
  evidence for stiff. "It is a sweater" is not evidence for warm. "It is silk" is
  not evidence for smooth. Only the reviewer's own description counts.
- Negation gives a negative label: "not scratchy at all" is rough=negative.
  A negated property does NOT license its opposite: "not soft" is soft=negative
  and says nothing about stiff.
- Comparative or hedged statements ("a little thin", "thinner than expected")
  still count as evidence; reflect the uncertainty in the confidence value.
- Omit every attribute you cannot justify. Omitted attributes are treated as
  unknown. Do not pad the output with guesses.
- evidence must be copied character for character from the REVIEW below, at most
  120 characters. Never copy evidence text out of these instructions.

Return only compact JSON, no prose, no markdown fence. Output shape only:
{{"a":[["ATTRIBUTE","p",0.0,"EXACT QUOTE FROM THE REVIEW"]]}}

Each entry is [attribute, polarity, confidence, evidence].
polarity is "p" for positive or "n" for negative.
confidence is a number between 0 and 1.
Return {{"a":[]}} when the review supports no attribute at all.

REVIEW: {review_text}"""


def parse_response(text: str, review_text: str) -> tuple[dict, bool, str | None]:
    candidate = text.strip().replace("```json", "").replace("```", "")
    match = re.search(r"\{.*\}", candidate, flags=re.S)
    if not match:
        return {}, True, "missing_json"
    try:
        payload = json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        return {}, True, f"json_error:{exc.msg}"

    items = payload.get("a", payload.get("attributes", []))
    if not isinstance(items, list):
        return {}, True, "bad_shape"

    lowered = review_text.lower()
    attributes: dict[str, dict] = {}
    for item in items:
        if isinstance(item, list) and len(item) >= 3:
            name, polarity, confidence = item[0], item[1], item[2]
            evidence = item[3] if len(item) > 3 else None
        elif isinstance(item, dict):
            name = item.get("attribute", item.get("id", ""))
            polarity = item.get("polarity", "")
            confidence = item.get("confidence", 0.0)
            evidence = item.get("evidence")
        else:
            continue
        name = str(name).strip().lower()
        if name not in ALLOWED or name in attributes:
            continue
        polarity = str(polarity).strip().lower()
        label = {"p": "positive", "positive": "positive", "n": "negative", "negative": "negative"}.get(polarity)
        if label is None:
            continue
        try:
            confidence = min(1.0, max(0.0, float(confidence)))
        except (TypeError, ValueError):
            continue
        evidence_text = str(evidence)[:120] if evidence else None
        attributes[name] = {
            "label": label,
            "confidence": confidence,
            "evidence": evidence_text,
            "evidence_verbatim": bool(evidence_text and evidence_text.lower() in lowered),
        }
    return attributes, not attributes, None


def iter_jsonl(path: Path):
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                yield json.loads(line)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int)
    parser.add_argument("--batch-size", type=int)
    parser.add_argument("--pool", choices=["selected", "skipped", "all"], default="all")
    args = parser.parse_args()

    config = load_config()
    qcfg = config["retraining"]["qwen"]
    batch_size = args.batch_size or int(qcfg["batch_size"])

    output = ROOT / "artifacts" / "qwen_fabricvst_labels.jsonl"
    output.parent.mkdir(parents=True, exist_ok=True)
    completed = {str(row["review_id"]) for row in iter_jsonl(output)} if output.exists() else set()

    allowed: set[str] | None = None
    if args.pool != "all":
        pool = json.loads((ROOT / "artifacts" / "qwen_candidate_pool.json").read_text())
        allowed = set(pool[f"{args.pool}_review_ids"])

    reviews = [
        row for row in iter_jsonl(Path(config["retraining"]["review_pool"]))
        if str(row["review_id"]) not in completed
        and (allowed is None or str(row["review_id"]) in allowed)
    ]
    if args.limit is not None:
        reviews = reviews[: args.limit]
    # Batches pad to their longest member, so grouping similar lengths together
    # removes most of the wasted compute.
    reviews.sort(key=lambda row: len(str(row.get("text", ""))))
    print(f"pending={len(reviews)} completed={len(completed)}", flush=True)
    if not reviews:
        print("nothing to do")
        return 0

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

    started = time.time()
    written = 0
    with output.open("a", encoding="utf-8") as handle:
        for start in range(0, len(reviews), batch_size):
            batch = reviews[start : start + batch_size]
            texts = []
            for row in batch:
                review_text = str(row.get("text", ""))[: int(qcfg["max_input_tokens"]) * 4]
                messages = [
                    {"role": "system", "content": [{"type": "text", "text": SYSTEM}]},
                    {"role": "user", "content": [{"type": "text", "text": build_prompt(review_text)}]},
                ]
                texts.append(processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True))
            inputs = processor(
                text=texts, return_tensors="pt", padding=True, truncation=True,
                max_length=int(qcfg["max_input_tokens"]),
            ).to(model.device)
            with torch.inference_mode():
                generated = model.generate(
                    **inputs, max_new_tokens=int(qcfg["max_new_tokens"]),
                    do_sample=False, pad_token_id=processor.tokenizer.pad_token_id,
                )
            trimmed = generated[:, inputs["input_ids"].shape[1]:]
            decoded = processor.tokenizer.batch_decode(trimmed, skip_special_tokens=True)

            for row, response in zip(batch, decoded):
                review_text = str(row.get("text", ""))
                attributes, unmapped, error = parse_response(response, review_text)
                handle.write(json.dumps({
                    "review_id": row["review_id"],
                    "asin": row["asin"],
                    "prompt_version": PROMPT_VERSION,
                    "attributes": attributes,
                    "unmapped": unmapped,
                    "parse_error": error,
                }, ensure_ascii=False) + "\n")
                written += 1
            handle.flush()

            done = start + len(batch)
            rate = done / max(time.time() - started, 1e-6)
            remaining = (len(reviews) - done) / max(rate, 1e-6)
            print(
                f"{done}/{len(reviews)} rate={rate:.2f}/s eta={remaining/3600:.2f}h",
                flush=True,
            )

    manifest = {
        "status": "complete",
        "prompt_version": PROMPT_VERSION,
        "prompt_file": str(ROOT / "prompts" / "fabricvst_tactile_pseudolabel.md"),
        "prompt_sha256": hashlib.sha256(
            (ROOT / "prompts" / "fabricvst_tactile_pseudolabel.md").read_bytes()
        ).hexdigest(),
        "model_id": qcfg["model_id"],
        "revision": qcfg["revision"],
        "quantization": qcfg["quantization"],
        "records_written": written,
        "output": str(output),
    }
    (ROOT / "manifests" / "03_qwen_pseudolabel.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
