#!/usr/bin/env python3
"""Score our own tactile heads (Last2, FabricVST-A, FabricVST-B, frozen FashionCLIP)
on Track A (Amazon) and Track B (FabricVST crops).

Image features are computed once per image per *backbone regime* and cached, so
the four heads do not each pay for a full encoder pass where they can share one.
They cannot share in general -- last2 / A / B each fine-tuned their own last two
encoder blocks -- so the cache key includes the checkpoint SHA-256.

Outputs one .npz per (model, track) under cache/scores/.
"""
from __future__ import annotations

import argparse
import gc
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np
import torch
from PIL import Image
from torch.utils.data import DataLoader, Dataset
from transformers import AutoProcessor, CLIPModel

import common22 as C

sys.path.insert(0, str(C.PROJECT / "experiments/21_fabricvst_external/scripts"))
from common import TactileClassifier  # noqa: E402  (exp21's definition, reused verbatim)

SCORES = C.CACHE / "scores"
SCORES.mkdir(parents=True, exist_ok=True)

MODELS = ["last2", "fabricvst_A", "fabricvst_B", "fashionclip_frozen"]


class Images(Dataset):
    def __init__(self, paths, processor):
        self.paths, self.processor = list(paths), processor

    def __len__(self):
        return len(self.paths)

    def __getitem__(self, i):
        with Image.open(self.paths[i]) as im:
            px = self.processor(images=im.convert("RGB"), return_tensors="pt").pixel_values[0]
        return px, i


def build(name, device):
    saved = torch.load(C.CKPT[name], map_location="cpu", weights_only=True)
    classes = [str(c) for c in saved["classes"]]
    clip = CLIPModel.from_pretrained(C.FASHIONCLIP_ID, revision=C.FASHIONCLIP_REV,
                                     local_files_only=True)
    model = TactileClassifier(clip, len(classes))
    missing, unexpected = model.load_state_dict(saved["state_dict"], strict=False)
    if unexpected:
        raise RuntimeError(f"{name}: unexpected checkpoint keys {unexpected[:5]}")
    thresholds = saved["thresholds"]
    if isinstance(thresholds, torch.Tensor):
        thresholds = thresholds.numpy()
    return model.to(device).eval(), classes, np.asarray(thresholds, dtype=np.float32)


@torch.inference_mode()
def score(model, paths, processor, device, batch_size, workers=8):
    loader = DataLoader(Images(paths, processor), batch_size=batch_size, shuffle=False,
                        num_workers=workers, pin_memory=True)
    out, order = [], []
    start = time.time()
    seen = 0
    for px, idx in loader:
        with torch.autocast("cuda", dtype=torch.bfloat16):
            logits = model(px.to(device, non_blocking=True))
        out.append(torch.sigmoid(logits.float()).cpu().numpy())
        order.append(idx.numpy())
        seen += px.shape[0]
        if seen % (batch_size * 20) == 0:
            rate = seen / (time.time() - start)
            print(f"    {seen}/{len(paths)}  {rate:.1f} img/s", flush=True)
    probs = np.concatenate(out)
    idx = np.concatenate(order)
    result = np.zeros((len(paths), probs.shape[1]), dtype=np.float32)
    result[idx] = probs
    return result, len(paths) / max(time.time() - start, 1e-9)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", nargs="*", default=MODELS)
    ap.add_argument("--batch-size", type=int, default=96)
    ap.add_argument("--calibrate", type=int, default=0,
                    help="if >0, score only this many Track A test images and exit")
    args = ap.parse_args()

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    processor = AutoProcessor.from_pretrained(C.FASHIONCLIP_ID, revision=C.FASHIONCLIP_REV,
                                              local_files_only=True)

    tracks = {}
    for split in ("development", "test"):
        data = C.load_amazon(split)
        tracks[f"amazon_{split}"] = {
            "paths": data["image_paths"],
            "unit_ids": data["product_ids"],
        }
    crops = C.fabricvst_crop_subset()
    fabric_order = sorted(crops)
    crop_paths, crop_fabric = [], []
    for f in fabric_order:
        for p in crops[f]:
            crop_paths.append(p)
            crop_fabric.append(f)
    tracks["fabricvst_subset"] = {"paths": crop_paths, "unit_ids": crop_fabric}
    C.write_json(C.ARTIFACTS / "fabricvst_crop_subset.json",
                 {"seed": C.SEED, "crops_per_fabric": C.CROPS_PER_FABRIC,
                  "n_fabrics": len(fabric_order), "n_crops": len(crop_paths),
                  "fabrics": {f: [p.name for p in crops[f]] for f in fabric_order}})

    if args.calibrate:
        tracks = {"amazon_test": {"paths": tracks["amazon_test"]["paths"][: args.calibrate],
                                  "unit_ids": tracks["amazon_test"]["unit_ids"][: args.calibrate]}}

    timings = {}
    for name in args.models:
        model, classes, thresholds = build(name, device)
        print(f"[{name}] {len(classes)} classes, device={device}", flush=True)
        for track, block in tracks.items():
            target = SCORES / f"{name}__{track}.npz"
            if target.is_file() and not args.calibrate:
                print(f"  {track}: cached, skipping", flush=True)
                continue
            print(f"  {track}: {len(block['paths'])} images", flush=True)
            probs, rate = score(model, block["paths"], processor, device, args.batch_size)
            timings[f"{name}/{track}"] = {"images": len(block["paths"]), "images_per_sec": rate}
            print(f"  {track}: done, {rate:.1f} img/s", flush=True)
            if not args.calibrate:
                np.savez_compressed(
                    target, probabilities=probs, classes=np.array(classes),
                    thresholds=thresholds,
                    unit_ids=np.array([str(u) for u in block["unit_ids"]]),
                    paths=np.array([str(p) for p in block["paths"]]),
                )
        del model
        gc.collect()
        torch.cuda.empty_cache()

    C.write_json(C.LOGS / ("calibration_ours.json" if args.calibrate else "timing_ours.json"), timings)
    print(json.dumps(timings, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
