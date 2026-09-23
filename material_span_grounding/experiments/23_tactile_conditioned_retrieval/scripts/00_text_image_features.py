#!/usr/bin/env python3
"""Cache CLIP-family image features for the natural-language retrieval baseline.

Exp22 stored per-attribute probabilities, not raw embeddings, so the
"user types a sentence, the system ranks images by text-image similarity"
baseline needs its own feature cache.  This is what a deployed search box would
actually do, so it belongs in the comparison.

Runs on CPU by default: the shared A100 belongs to another user's job.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np
import torch
from PIL import Image
from torch.utils.data import DataLoader, Dataset

import common23 as R

MODELS = {
    "fashionclip": ("patrickjohncyh/fashion-clip", "7e3ba62ce16b379a1ab479346b66f192e76f51b7"),
    "siglip2": ("google/siglip2-so400m-patch14-384", None),
}


class Images(Dataset):
    def __init__(self, paths, processor):
        self.paths, self.processor = list(paths), processor

    def __len__(self):
        return len(self.paths)

    def __getitem__(self, i):
        with Image.open(self.paths[i]) as im:
            return self.processor(images=im.convert("RGB"),
                                  return_tensors="pt").pixel_values[0], i


def as_tensor(value):
    if isinstance(value, torch.Tensor):
        return value
    for attr in ("pooler_output", "text_embeds", "image_embeds", "last_hidden_state"):
        got = getattr(value, attr, None)
        if isinstance(got, torch.Tensor):
            return got if got.ndim == 2 else got[:, 0]
    raise TypeError(type(value))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="fashionclip", choices=list(MODELS))
    ap.add_argument("--device", default="cpu")
    ap.add_argument("--batch-size", type=int, default=64)
    ap.add_argument("--workers", type=int, default=16)
    args = ap.parse_args()

    from transformers import AutoModel, AutoProcessor, AutoTokenizer

    model_id, revision = MODELS[args.model]
    kw = {"revision": revision} if revision else {}
    device = torch.device(args.device)
    model = AutoModel.from_pretrained(model_id, dtype=torch.float32,
                                      use_safetensors=True, **kw).to(device).eval()
    processor = AutoProcessor.from_pretrained(model_id, **kw)
    tokenizer = AutoTokenizer.from_pretrained(model_id, **kw)
    text_config = getattr(model.config, "text_config", model.config)
    max_length = int(getattr(text_config, "max_position_embeddings", 64))
    scale = float(model.logit_scale.exp().item()) if hasattr(model, "logit_scale") else 100.0

    torch.set_num_threads(max(1, args.workers))
    for split in ("development", "test"):
        target = R.CACHE / f"{args.model}_image_features__{split}.npz"
        if target.is_file():
            print(f"{split}: cached", flush=True)
            continue
        block = R.label_block(split)
        paths = [R.C22.AMAZON_IMAGES / f"{p}.jpg" for p in block["product_ids"]]
        loader = DataLoader(Images(paths, processor), batch_size=args.batch_size,
                            shuffle=False, num_workers=args.workers)
        feats, order = [], []
        start = time.time()
        with torch.inference_mode():
            for n, (px, idx) in enumerate(loader):
                f = as_tensor(model.get_image_features(pixel_values=px.to(device)))
                feats.append(torch.nn.functional.normalize(f.float(), dim=-1).cpu())
                order.append(idx)
                if n % 5 == 0:
                    seen = (n + 1) * args.batch_size
                    print(f"  {split} {min(seen, len(paths))}/{len(paths)} "
                          f"{seen / max(time.time() - start, 1e-9):.1f} img/s", flush=True)
        f = torch.cat(feats)
        idx = torch.cat(order)
        out = torch.zeros_like(f)
        out[idx] = f
        np.savez_compressed(target, features=out.numpy().astype(np.float32),
                            product_ids=np.array(block["product_ids"]),
                            logit_scale=np.array([scale]), max_length=np.array([max_length]))
        print(f"{split}: wrote {target.name} {tuple(out.shape)}", flush=True)

    # text side: every query string in the benchmark
    queries = {s: R.build_queries(R.label_block(s)) for s in ("development", "test")}
    texts = sorted({q["text"] for qs in queries.values() for q in qs})
    with torch.inference_mode():
        batch = tokenizer(texts, padding="max_length", max_length=max_length,
                          truncation=True, return_tensors="pt").to(device)
        tf = as_tensor(model.get_text_features(**batch))
        tf = torch.nn.functional.normalize(tf.float(), dim=-1).cpu().numpy()
    np.savez_compressed(R.CACHE / f"{args.model}_text_features.npz",
                        features=tf.astype(np.float32), texts=np.array(texts),
                        logit_scale=np.array([scale]))
    print(f"text features: {tf.shape} for {len(texts)} distinct query strings", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
