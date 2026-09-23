#!/usr/bin/env python3
"""Zero-shot CLIP-family scoring with paired positive/negative text prompts.

For every attribute a and image x the score is

    P(a | x) = softmax_over_two( s * cos(f(x), t_pos(a)),  s * cos(f(x), t_neg(a)) )[0]

with the model's own learned logit scale s.  This yields a continuous score in
(0,1) that is comparable across attributes and models.

Three prompt templates (fixed in common22.CLIP_TEMPLATES) are scored for every
model.  Which one is used downstream is decided by macro AUROC on the Amazon
*development* split only; that choice is written to
artifacts/clip_prompt_selection.json before any test number is produced.

These are texture/material *zero-shot* baselines.  They are not tactile-property
classifiers and are never described as such.
"""
from __future__ import annotations

import argparse
import gc
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np
import torch
from PIL import Image
from torch.utils.data import DataLoader, Dataset

import common22 as C

SCORES = C.CACHE / "scores"
SCORES.mkdir(parents=True, exist_ok=True)

# model key -> (hf id, revision or None)
CLIP_MODELS = {
    # CLIP-Texture protocol (cvl-umass/clip-texture, ECCV CVinW 2022).  That work
    # releases no checkpoint of its own -- its contribution is an evaluation of
    # stock OpenAI CLIP on texture/material benchmarks -- so the protocol is
    # reproduced with the stock encoder it reports.  ViT-L/14 is used rather than
    # ViT-L/14@336 because the 336 repo ships only a pickled .bin, which
    # transformers refuses to load on torch<2.6 (CVE-2025-32434).  The paper's own
    # tables put the two within 0.3 pp on DTD (50.4 vs 50.7).
    "clip_texture_vitl14": ("openai/clip-vit-large-patch14", "32bd64288804d66eefd0ccbe215aa642df71cc41"),
    # in-domain apparel CLIP, used zero-shot (no supervised head)
    "fashionclip_zeroshot": (C.FASHIONCLIP_ID, C.FASHIONCLIP_REV),
    # modern open-weight general-purpose contrastive baseline
    "siglip2_so400m_384": ("google/siglip2-so400m-patch14-384", None),
}


class Images(Dataset):
    def __init__(self, paths, processor):
        self.paths, self.processor = list(paths), processor

    def __len__(self):
        return len(self.paths)

    def __getitem__(self, i):
        with Image.open(self.paths[i]) as im:
            px = self.processor(images=im.convert("RGB"), return_tensors="pt").pixel_values[0]
        return px, i


def as_tensor(value):
    """transformers 5.x returns a ModelOutput from some get_*_features; unwrap it."""
    if isinstance(value, torch.Tensor):
        return value
    for attr in ("pooler_output", "text_embeds", "image_embeds", "last_hidden_state"):
        got = getattr(value, attr, None)
        if isinstance(got, torch.Tensor):
            return got if got.ndim == 2 else got[:, 0]
    raise TypeError(f"cannot unwrap features of type {type(value)}")


@torch.inference_mode()
def image_features(model, paths, processor, device, batch_size, workers=8):
    loader = DataLoader(Images(paths, processor), batch_size=batch_size, shuffle=False,
                        num_workers=workers, pin_memory=True)
    feats, order = [], []
    start = time.time()
    for px, idx in loader:
        f = as_tensor(model.get_image_features(pixel_values=px.to(device, non_blocking=True).to(model.dtype)))
        feats.append(torch.nn.functional.normalize(f.float(), dim=-1).cpu())
        order.append(idx)
    f = torch.cat(feats)
    idx = torch.cat(order)
    out = torch.zeros_like(f)
    out[idx] = f
    return out, len(paths) / max(time.time() - start, 1e-9)


@torch.inference_mode()
def text_features(model, tokenizer, texts, device, max_length):
    batch = tokenizer(texts, padding="max_length", max_length=max_length,
                      truncation=True, return_tensors="pt").to(device)
    f = as_tensor(model.get_text_features(**batch))
    return torch.nn.functional.normalize(f.float(), dim=-1).cpu()


def logit_scale(model) -> float:
    for attr in ("logit_scale",):
        if hasattr(model, attr):
            return float(getattr(model, attr).exp().item())
    return 100.0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", nargs="*", default=list(CLIP_MODELS))
    ap.add_argument("--batch-size", type=int, default=64)
    args = ap.parse_args()

    from transformers import AutoModel, AutoProcessor, AutoTokenizer

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

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

    for name in args.models:
        model_id, revision = CLIP_MODELS[name]
        done = all((SCORES / f"{name}__{t}.npz").is_file() for t in tracks)
        if done:
            print(f"[{name}] cached, skipping", flush=True)
            continue
        print(f"[{name}] loading {model_id}", flush=True)
        kw = {"revision": revision} if revision else {}
        dtype = torch.bfloat16 if name.startswith("siglip") else torch.float32
        model = AutoModel.from_pretrained(model_id, dtype=dtype, use_safetensors=True, **kw).to(device).eval()
        processor = AutoProcessor.from_pretrained(model_id, **kw)
        tokenizer = AutoTokenizer.from_pretrained(model_id, **kw)
        scale = logit_scale(model)
        text_config = getattr(model.config, "text_config", model.config)
        max_length = int(getattr(text_config, "max_position_embeddings", 64))
        print(f"[{name}] logit scale {scale:.2f}, text max_length {max_length}", flush=True)

        # text side: one (pos, neg) pair per attribute per template
        text_bank = {}
        for template in C.CLIP_TEMPLATES:
            prompts = []
            for a in C.COMMON8:
                p, n = C.clip_prompts(a, template)
                prompts += [p, n]
            tf = text_features(model, tokenizer, prompts, device, max_length)
            text_bank[template] = tf.view(len(C.COMMON8), 2, -1)

        for track, (track_paths, unit_ids) in tracks.items():
            target = SCORES / f"{name}__{track}.npz"
            if target.is_file():
                continue
            print(f"  {track}: {len(track_paths)} images", flush=True)
            feats, rate = image_features(model, track_paths, processor, device, args.batch_size)
            print(f"  {track}: {rate:.1f} img/s", flush=True)
            payload = {}
            for template, tf in text_bank.items():
                # (N, A, 2) similarity -> softmax over the two poles
                sim = torch.einsum("nd,akd->nak", feats, tf) * scale
                payload[f"probabilities__{template}"] = torch.softmax(sim, dim=-1)[..., 0].numpy().astype(np.float32)
            np.savez_compressed(
                target, classes=np.array(C.COMMON8),
                unit_ids=np.array([str(u) for u in unit_ids]),
                paths=np.array([str(p) for p in track_paths]),
                templates=np.array(list(C.CLIP_TEMPLATES)),
                **payload,
            )
        del model
        gc.collect()
        torch.cuda.empty_cache()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
