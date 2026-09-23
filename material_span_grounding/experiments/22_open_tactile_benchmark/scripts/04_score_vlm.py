#!/usr/bin/env python3
"""Constrained VLM scoring: P(YES) read off the first generated token's logits.

The model is never asked "what does this feel like?".  For every (image,
attribute) pair it answers one fixed yes/no question and we take

    P(YES) = softmax over { max logit of YES-variants, max logit of NO-variants }

at the first answer position.  That is a single forward pass -- no autoregressive
decoding -- so the score is deterministic by construction (equivalent to
temperature 0) and is a real model probability, not a self-reported confidence.

Results are cached per (model_id, revision, prompt_version, track, attribute) in
an append-only JSONL so an interrupted run never recomputes finished work.
"""
from __future__ import annotations

import argparse
import gc
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ.setdefault("HF_HOME", "/home/user/onsesang/.cache/huggingface")

import numpy as np
import torch
from PIL import Image

import common22 as C

SCORES = C.CACHE / "scores"
VLM_CACHE = C.CACHE / "vlm"
SCORES.mkdir(parents=True, exist_ok=True)
VLM_CACHE.mkdir(parents=True, exist_ok=True)

VLM_MODELS = {
    "qwen3vl_8b": {"id": "Qwen/Qwen3-VL-8B-Instruct", "revision": None},
    "qwen3vl_32b": {"id": "Qwen/Qwen3-VL-32B-Instruct",
                    "revision": "0cfaf48183f594c314753d30a4c4974bc75f3ccb"},
    "internvl3_5_8b": {"id": "OpenGVLab/InternVL3_5-8B-HF", "revision": None},
}

YES_WORDS = ["YES", "Yes", "yes", " YES", " Yes", " yes"]
NO_WORDS = ["NO", "No", "no", " NO", " No", " no"]


def answer_token_ids(tokenizer, words):
    ids = set()
    for w in words:
        for enc in (tokenizer.encode(w, add_special_tokens=False),):
            if enc:
                ids.add(int(enc[0]))
    return sorted(ids)


def load_vlm(key, quantize):
    from transformers import AutoModelForImageTextToText, AutoProcessor

    spec = VLM_MODELS[key]
    kw = {"revision": spec["revision"]} if spec["revision"] else {}
    processor = AutoProcessor.from_pretrained(spec["id"], **kw)
    load_kw = dict(dtype=torch.bfloat16, device_map="cuda:0", **kw)
    if quantize == "nf4":
        from transformers import BitsAndBytesConfig
        load_kw["quantization_config"] = BitsAndBytesConfig(
            load_in_4bit=True, bnb_4bit_quant_type="nf4",
            bnb_4bit_compute_dtype=torch.bfloat16, bnb_4bit_use_double_quant=True,
        )
    elif quantize == "int8":
        from transformers import BitsAndBytesConfig
        load_kw["quantization_config"] = BitsAndBytesConfig(load_in_8bit=True)
    model = AutoModelForImageTextToText.from_pretrained(spec["id"], **load_kw).eval()
    return model, processor


@torch.inference_mode()
def score_batch(model, processor, images, question, yes_ids, no_ids, max_pixels):
    messages = []
    for _ in images:
        messages.append([{"role": "user", "content": [
            {"type": "image"}, {"type": "text", "text": question}]}])
    texts = [processor.apply_chat_template(m, tokenize=False, add_generation_prompt=True)
             for m in messages]
    batch = processor(text=texts, images=[[im] for im in images],
                      return_tensors="pt", padding=True)
    batch = {k: (v.to(model.device) if hasattr(v, "to") else v) for k, v in batch.items()}
    out = model(**batch)
    logits = out.logits[:, -1, :].float()
    yes = logits[:, yes_ids].max(dim=-1).values
    no = logits[:, no_ids].max(dim=-1).values
    pair = torch.stack([yes, no], dim=-1)
    return torch.softmax(pair, dim=-1)[:, 0].cpu().numpy().astype(np.float32)


def load_images(paths, max_side):
    images = []
    for p in paths:
        with Image.open(p) as im:
            im = im.convert("RGB")
            if max(im.size) > max_side:
                scale = max_side / max(im.size)
                im = im.resize((max(28, int(im.width * scale)), max(28, int(im.height * scale))),
                               Image.BICUBIC)
            images.append(im.copy())
    return images


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True, choices=list(VLM_MODELS))
    ap.add_argument("--tracks", nargs="*",
                    default=["amazon_development", "amazon_test", "fabricvst_subset"])
    ap.add_argument("--batch-size", type=int, default=8)
    ap.add_argument("--max-side", type=int, default=448)
    ap.add_argument("--quantize", default="bf16", choices=["bf16", "nf4", "int8"])
    ap.add_argument("--calibrate", type=int, default=0)
    args = ap.parse_args()

    tracks = {}
    for split in ("development", "test"):
        d = C.load_amazon(split)
        tracks[f"amazon_{split}"] = (d["image_paths"], d["product_ids"])
    crops = C.fabricvst_crop_subset()
    paths, fabrics = [], []
    for f in sorted(crops):
        for p in crops[f]:
            paths.append(p)
            fabrics.append(f)
    tracks["fabricvst_subset"] = (paths, fabrics)

    key = args.model
    cache_path = VLM_CACHE / f"{key}__{C.PROMPT_VERSION}__{args.quantize}.jsonl"
    done: dict[tuple[str, str, str], float] = {}
    if cache_path.is_file():
        with cache_path.open() as handle:
            for line in handle:
                try:
                    r = json.loads(line)
                except json.JSONDecodeError:
                    continue
                done[(r["track"], r["path"], r["attribute"])] = r["p_yes"]
    print(f"[{key}] cache holds {len(done)} scored pairs", flush=True)

    model, processor = load_vlm(key, args.quantize)
    tokenizer = getattr(processor, "tokenizer", processor)
    yes_ids = answer_token_ids(tokenizer, YES_WORDS)
    no_ids = answer_token_ids(tokenizer, NO_WORDS)
    print(f"[{key}] yes ids {yes_ids} no ids {no_ids}", flush=True)
    if not yes_ids or not no_ids:
        raise RuntimeError("could not resolve YES/NO token ids")

    start_all = time.time()
    n_new = 0
    handle = cache_path.open("a")
    for track in args.tracks:
        track_paths, unit_ids = tracks[track]
        if args.calibrate:
            track_paths, unit_ids = track_paths[: args.calibrate], unit_ids[: args.calibrate]
        target = SCORES / f"{key}__{track}.npz"
        if target.is_file() and not args.calibrate:
            # Only skip when the cached file was produced at THIS precision.  A
            # leftover .npz from an earlier run at a different precision would
            # otherwise silently mix NF4 and BF16 scores across splits -- and the
            # development split sets the thresholds applied to test, so that would
            # corrupt every downstream number.
            existing = np.load(target, allow_pickle=True)
            previous = (str(existing["quantization"][0])
                        if "quantization" in existing else "unknown")
            if previous == args.quantize:
                print(f"  {track}: cached npz at {previous}, skipping", flush=True)
                continue
            stale = target.with_suffix(f".npz.{previous}-stale.bak")
            target.rename(stale)
            print(f"  {track}: cached npz was {previous}, need {args.quantize}; "
                  f"moved to {stale.name} and rescoring", flush=True)
        matrix = np.full((len(track_paths), len(C.COMMON8)), np.nan, dtype=np.float32)
        for j, attribute in enumerate(C.COMMON8):
            question = C.vlm_prompt(attribute)
            todo = [i for i, p in enumerate(track_paths)
                    if (track, str(p), attribute) not in done]
            for i, p in enumerate(track_paths):
                v = done.get((track, str(p), attribute))
                if v is not None:
                    matrix[i, j] = v
            t0 = time.time()
            for b in range(0, len(todo), args.batch_size):
                chunk = todo[b: b + args.batch_size]
                images = load_images([track_paths[i] for i in chunk], args.max_side)
                probs = score_batch(model, processor, images, question, yes_ids, no_ids,
                                    args.max_side)
                for i, prob in zip(chunk, probs):
                    matrix[i, j] = prob
                    handle.write(json.dumps({"track": track, "path": str(track_paths[i]),
                                             "attribute": attribute,
                                             "p_yes": float(prob)}) + "\n")
                n_new += len(chunk)
                if (b // args.batch_size) % 20 == 0:
                    rate = (b + len(chunk)) / max(time.time() - t0, 1e-9)
                    print(f"    {track}/{attribute}: {b + len(chunk)}/{len(todo)} "
                          f"{rate:.2f} img/s", flush=True)
            handle.flush()
            print(f"  {track}/{attribute}: done in {time.time() - t0:.1f}s", flush=True)
        if not args.calibrate:
            # Never write a partially-filled matrix: a NaN here would silently
            # propagate into AUROC/threshold selection downstream.  Failing loudly
            # lets the supervisor retry, and the JSONL cache means nothing is lost.
            missing = int(np.isnan(matrix).sum())
            if missing:
                raise RuntimeError(
                    f"{key}/{track}: {missing} of {matrix.size} scores are NaN; "
                    "refusing to write the npz so the run can be retried")
            np.savez_compressed(
                target, probabilities=matrix, classes=np.array(C.COMMON8),
                unit_ids=np.array([str(u) for u in unit_ids]),
                paths=np.array([str(p) for p in track_paths]),
                prompt_version=np.array([C.PROMPT_VERSION]),
                quantization=np.array([args.quantize]),
            )
    handle.close()

    elapsed = time.time() - start_all
    stats = {"model": key, "new_pairs": n_new, "elapsed_sec": elapsed,
             "pairs_per_sec": n_new / max(elapsed, 1e-9), "quantize": args.quantize,
             "max_side": args.max_side, "batch_size": args.batch_size}
    name = "calibration" if args.calibrate else "timing"
    C.write_json(C.LOGS / f"{name}_vlm_{key}.json", stats)
    print(json.dumps(stats, indent=2))

    del model
    gc.collect()
    torch.cuda.empty_cache()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
