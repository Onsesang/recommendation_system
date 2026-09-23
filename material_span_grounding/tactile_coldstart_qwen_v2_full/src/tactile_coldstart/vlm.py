from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

import numpy as np

from .common import (
    PATHS, axis_map, load_experiment, load_taxonomy, read_json, read_jsonl,
    sha256_file, symbolic_score, utc_now, write_json, write_jsonl,
)
from .grounding import INTENSITIES, taxonomy_for_prompt


def render_vlm_prompt(product_id: str, taxonomy: dict[str, Any], active_axes: list[str]) -> str:
    axes = [row for row in taxonomy_for_prompt(taxonomy) if row["axis_id"] in set(active_axes)]
    schema = {
        "product_id": product_id,
        "predictions": [
            {
                "axis_id": "one supplied axis_id",
                "visually_assessable": "boolean",
                "direction": "exact pole, neutral, or null",
                "intensity": "none|slight|moderate|strong|unknown|null",
                "confidence": "0..1",
            }
        ],
    }
    return "\n".join(
        [
            "Assess only the visible material appearance in the supplied product image.",
            "Use the supplied taxonomy generically. Return exactly one entry per supplied axis.",
            "If an axis cannot be supported from the pixels, set visually_assessable=false and do not guess a pole.",
            "Return symbolic poles and intensity only, never a continuous score. Return one JSON object without Markdown.",
            "TAXONOMY", json.dumps(axes, ensure_ascii=False),
            "OUTPUT SCHEMA", json.dumps(schema, ensure_ascii=False),
            "PRODUCT_ID", product_id,
        ]
    )


def _json_object(text: str) -> dict[str, Any]:
    value = text.strip()
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", value, flags=re.DOTALL | re.IGNORECASE)
    if fenced:
        value = fenced.group(1)
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        start, end = value.find("{"), value.rfind("}")
        if start < 0 or end <= start:
            raise
        parsed = json.loads(value[start:end + 1])
    if not isinstance(parsed, dict):
        raise ValueError("response is not an object")
    return parsed


def parse_vlm_output(raw: str, product_id: str, taxonomy: dict[str, Any], active_axes: list[str]) -> dict[str, Any]:
    try:
        value = _json_object(raw)
        normalizations: list[dict[str, Any]] = []
        if str(value.get("product_id")) != product_id:
            normalizations.append({
                "field": "product_id", "from": str(value.get("product_id")),
                "to": product_id, "rule": "source_id_is_authoritative",
            })
        rows = value.get("predictions")
        if not isinstance(rows, list):
            raise ValueError("predictions must be a list")
        axis_values = [str(row.get("axis_id")) for row in rows if isinstance(row, dict)]
        if len(axis_values) != len(set(axis_values)):
            raise ValueError("predictions contain duplicate axes")
        by_axis = {str(row.get("axis_id")): row for row in rows if isinstance(row, dict)}
        extras = set(by_axis) - set(active_axes)
        if extras:
            raise ValueError(f"predictions contain unknown axes: {sorted(extras)}")
        # Missing axes are fail-closed as not visually assessable. This preserves
        # abstention and never invents a pole or numeric tactile score.
        for axis_id in active_axes:
            if axis_id not in by_axis:
                by_axis[axis_id] = {"axis_id": axis_id, "visually_assessable": False}
                normalizations.append({
                    "field": f"predictions.{axis_id}", "from": "missing",
                    "to": "visually_assessable=false", "rule": "missing_axis_abstention",
                })
        axes = axis_map(taxonomy)
        predictions = []
        for axis_id in active_axes:
            row = by_axis[axis_id]
            assessable = row.get("visually_assessable")
            if not isinstance(assessable, bool):
                raise ValueError("invalid assessability/confidence")
            if not assessable:
                confidence = float(row.get("confidence") or 0.0)
                if not 0.0 <= confidence <= 1.0:
                    raise ValueError("invalid assessability/confidence")
                predictions.append({"axis_id": axis_id, "visually_assessable": False, "direction": None, "intensity": None, "confidence": confidence, "score": None})
                continue
            confidence = float(row.get("confidence"))
            if not 0.0 <= confidence <= 1.0:
                raise ValueError("invalid assessability/confidence")
            direction = str(row.get("direction"))
            intensity = str(row.get("intensity"))
            valid = {str(axes[axis_id]["negative_pole"]), str(axes[axis_id]["positive_pole"]), "neutral"}
            if direction not in valid or intensity not in INTENSITIES:
                raise ValueError(f"invalid symbolic value for {axis_id}")
            symbolic = {"axis_id": axis_id, "direction": direction, "intensity": intensity}
            predictions.append({**symbolic, "visually_assessable": True, "confidence": confidence, "score": symbolic_score(symbolic, taxonomy)})
        return {"status": "success", "error": "", "predictions": predictions, "normalizations": normalizations}
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        return {"status": "schema_failure", "error": str(exc), "predictions": []}


class VisualQwenRunner:
    def __init__(self, model_id: str, snapshot: str) -> None:
        import torch
        from transformers import AutoProcessor, BitsAndBytesConfig, Qwen3VLForConditionalGeneration

        model_path = Path.home() / ".cache" / "huggingface" / "hub" / f"models--{model_id.replace('/', '--')}" / "snapshots" / snapshot
        quantization = BitsAndBytesConfig(
            load_in_4bit=True, bnb_4bit_quant_type="nf4",
            bnb_4bit_compute_dtype=torch.bfloat16, bnb_4bit_use_double_quant=True,
        )
        self.processor = AutoProcessor.from_pretrained(model_path, local_files_only=True)
        self.processor.tokenizer.padding_side = "left"
        self.model = Qwen3VLForConditionalGeneration.from_pretrained(
            model_path, quantization_config=quantization, device_map="auto",
            dtype=torch.bfloat16, local_files_only=True,
        ).eval()

    def generate(
        self, product_ids: list[str], image_paths: list[Path], prompts: list[str],
        max_tokens: int, max_image_side: int,
    ) -> list[str]:
        import torch
        from PIL import Image

        messages, images = [], []
        for image_path, prompt in zip(image_paths, prompts):
            message = [{"role": "user", "content": [{"type": "image"}, {"type": "text", "text": prompt}]}]
            messages.append(self.processor.apply_chat_template(message, tokenize=False, add_generation_prompt=True))
            with Image.open(image_path) as image:
                converted = image.convert("RGB")
                converted.thumbnail((max_image_side, max_image_side))
                images.append(converted.copy())
        inputs = self.processor(text=messages, images=images, padding=True, return_tensors="pt").to("cuda")
        with torch.inference_mode():
            generated = self.model.generate(**inputs, max_new_tokens=max_tokens, do_sample=False, use_cache=True)
        return [
            value.strip() for value in self.processor.batch_decode(
                generated[:, inputs["input_ids"].shape[1]:], skip_special_tokens=True
            )
        ]


def run_qwen_vlm_zero_shot() -> dict[str, Any]:
    config = load_experiment()
    taxonomy = load_taxonomy()
    active = [str(value) for value in read_json(PATHS.artifacts / "active_axes.json")["active_axes"]]
    products = read_json(Path(config["inputs"]["product_master"]))
    product_ids = [str(row["product_id"]) for row in products]
    product_index = {value: index for index, value in enumerate(product_ids)}
    split = read_json(PATHS.manifests / f"family_split_{config['experiment']['seed']}.json")["splits"]
    test_ids = [str(value) for value in split["test"]]
    path = PATHS.artifacts / "qwen_vlm_zero_shot.jsonl"
    stored_rows = read_jsonl(path)
    existing = {str(row["product_id"]): row for row in stored_rows if row.get("status") == "success"}
    for stored in stored_rows:
        product_id = str(stored["product_id"])
        if product_id in existing:
            continue
        parsed = parse_vlm_output(
            str(stored.get("raw_output") or ""), product_id, taxonomy, active
        )
        if parsed["status"] == "success":
            existing[product_id] = {
                **stored, **parsed, "recovered_from_raw_output": True,
            }
    pending = [value for value in test_ids if value not in existing]
    settings = config["vlm_zero_shot"]
    labeler = config["semantic_labeler"]
    runner = VisualQwenRunner(labeler["model_id"], labeler["snapshot"]) if pending else None
    batch_size = int(settings["batch_size"])
    image_root = Path(config["inputs"]["image_root"])
    started = time.time()
    for start in range(0, len(pending), batch_size):
        ids = pending[start:start + batch_size]
        unresolved = list(ids)
        for attempt in range(1, int(labeler["max_attempts"]) + 1):
            prompts = [render_vlm_prompt(value, taxonomy, active) for value in unresolved]
            if attempt > 1:
                prompts = [value + "\nThe prior output failed validation. Return one complete valid JSON object." for value in prompts]
            assert runner is not None
            outputs = runner.generate(
                unresolved, [image_root / f"{value}.jpg" for value in unresolved],
                prompts, int(settings["max_tokens"]), int(settings["max_image_side"]),
            )
            retry = []
            for product_id, raw in zip(unresolved, outputs):
                parsed = parse_vlm_output(raw, product_id, taxonomy, active)
                existing[product_id] = {
                    "product_id": product_id, **parsed, "raw_output": raw,
                    "attempts": attempt,
                    "model_id": labeler["model_id"], "model_snapshot": labeler["snapshot"],
                    "prompt_version": settings["prompt_version"], "schema_version": settings["schema_version"],
                    "taxonomy_version": taxonomy["version"],
                }
                if parsed["status"] != "success" and attempt < int(labeler["max_attempts"]):
                    retry.append(product_id)
            unresolved = retry
            if not unresolved:
                break
        write_jsonl(path, [existing[value] for value in test_ids if value in existing])
        print(f"Qwen VLM zero-shot: {len(existing)}/{len(test_ids)}", flush=True)
    # Persist parser-only recoveries even when no new model inference was needed.
    write_jsonl(path, [existing[value] for value in test_ids if value in existing])
    prediction = np.full((len(product_ids), len(active)), np.nan, dtype=np.float32)
    confidence = np.zeros((len(product_ids), len(active)), dtype=np.float32)
    visual_mask = np.zeros((len(product_ids), len(active)), dtype=np.uint8)
    for product_id, row in existing.items():
        if row.get("status") != "success":
            continue
        for axis_number, item in enumerate(row["predictions"]):
            confidence[product_index[product_id], axis_number] = float(item["confidence"])
            if item["visually_assessable"]:
                prediction[product_index[product_id], axis_number] = float(item["score"])
                visual_mask[product_index[product_id], axis_number] = 1
    matrix_path = PATHS.artifacts / "qwen_vlm_zero_shot.npz"
    np.savez_compressed(
        matrix_path, product_ids=np.asarray(product_ids), axis_ids=np.asarray(active),
        prediction=prediction, confidence=confidence, visual_mask=visual_mask,
    )
    successful = sum(row.get("status") == "success" for row in existing.values())
    manifest = {
        "status": "complete" if successful == len(test_ids) else "incomplete",
        "phase": 6, "component": "qwen_vlm_zero_shot", "generated_at": utc_now(),
        "test_products": len(test_ids), "schema_success": successful,
        "visually_assessable_pairs": int(visual_mask.sum()),
        "elapsed_seconds_this_process": time.time() - started,
        "inference_input": "product image only; no buyer review",
        "model_id": labeler["model_id"], "model_snapshot": labeler["snapshot"],
        "output": str(path), "output_sha256": sha256_file(path),
        "matrices": str(matrix_path), "matrices_sha256": sha256_file(matrix_path),
    }
    write_json(PATHS.manifests / "phase6_qwen_vlm_zero_shot.json", manifest)
    return manifest
