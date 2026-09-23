#!/usr/bin/env python3
"""Run a tactile checkpoint over the Amazon catalog images, for the Exp24
tactile-source ablation.

Last2 already has a full-catalog cache (exp16b `product_tactile_profiles.parquet`,
825,840 rows).  FabricVST-A and FabricVST-B never do, so this produces them.

Writes an .npz aligned to catalog `iid`, plus a coverage record.  Resumable: it
checkpoints every `--flush` batches so an interrupted run continues.
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

import common24 as C

sys.path.insert(0, str(C.PROJECT / "experiments/21_fabricvst_external/scripts"))
from common import TactileClassifier  # noqa: E402

IMAGES = C.E16 / "data/amazon_fashion_images"
CKPT = {
    "fabricvst_A": C.PROJECT / "experiments/21_fabricvst_external/checkpoints/fabricvst_taxonomy/best.pt",
    "fabricvst_B": C.PROJECT / "experiments/21_fabricvst_external/checkpoints/fabricvst_taxonomy/B_best.pt",
}
FASHIONCLIP_ID = "patrickjohncyh/fashion-clip"
FASHIONCLIP_REV = "7e3ba62ce16b379a1ab479346b66f192e76f51b7"


class CatalogImages(Dataset):
    def __init__(self, iids, processor):
        self.iids, self.processor = iids, processor

    def __len__(self):
        return len(self.iids)

    def __getitem__(self, i):
        path = IMAGES / f"{self.iids[i]}.jpg"
        try:
            with Image.open(path) as im:
                px = self.processor(images=im.convert("RGB"),
                                    return_tensors="pt").pixel_values[0]
            return px, i, 1
        except Exception:
            return torch.zeros(3, 224, 224), i, 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True, choices=list(CKPT))
    ap.add_argument("--batch-size", type=int, default=256)
    ap.add_argument("--workers", type=int, default=16)
    ap.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    ap.add_argument("--flush", type=int, default=200)
    args = ap.parse_args()

    from transformers import AutoProcessor, CLIPModel

    target = C.CACHE / f"catalog_tactile__{args.model}.npz"
    saved = torch.load(CKPT[args.model], map_location="cpu", weights_only=True)
    classes = [str(c) for c in saved["classes"]]
    device = torch.device(args.device)
    clip = CLIPModel.from_pretrained(FASHIONCLIP_ID, revision=FASHIONCLIP_REV,
                                     local_files_only=True)
    model = TactileClassifier(clip, len(classes))
    missing, unexpected = model.load_state_dict(saved["state_dict"], strict=False)
    if unexpected:
        raise RuntimeError(f"unexpected keys {unexpected[:5]}")
    model = model.to(device).eval()
    processor = AutoProcessor.from_pretrained(FASHIONCLIP_ID, revision=FASHIONCLIP_REV,
                                              local_files_only=True)

    data = C.load_prepared()
    n_items = int(data["n_items"][0])
    values = np.zeros((n_items, len(classes)), dtype=np.float32)
    covered = np.zeros(n_items, dtype=bool)
    start_at = 0
    if target.is_file():
        blob = np.load(target)
        values, covered = blob["values"], blob["available"]
        start_at = int(blob["progress"][0])
        print(f"resuming at {start_at}", flush=True)

    iids = np.arange(n_items)[start_at:]
    loader = DataLoader(CatalogImages(iids, processor), batch_size=args.batch_size,
                        shuffle=False, num_workers=args.workers, pin_memory=True)
    start = time.time()
    done = 0
    with torch.inference_mode():
        for n, (px, index, ok) in enumerate(loader):
            with torch.autocast("cuda", dtype=torch.bfloat16, enabled=device.type == "cuda"):
                logits = model(px.to(device, non_blocking=True))
            probabilities = torch.sigmoid(logits.float()).cpu().numpy()
            rows = iids[index.numpy()]
            good = ok.numpy().astype(bool)
            values[rows[good]] = probabilities[good]
            covered[rows[good]] = True
            done += px.shape[0]
            if n % args.flush == 0:
                np.savez_compressed(target, values=values, available=covered,
                                    classes=np.array(classes),
                                    progress=np.array([int(rows[-1]) + 1]))
                rate = done / max(time.time() - start, 1e-9)
                remaining = (len(iids) - done) / max(rate, 1e-9) / 60
                print(f"  {start_at + done}/{n_items}  {rate:.0f} img/s  "
                      f"~{remaining:.0f} min left", flush=True)
    np.savez_compressed(target, values=values, available=covered,
                        classes=np.array(classes), progress=np.array([n_items]))
    C.write_json(C.LOGS / f"catalog_tactile__{args.model}.json", {
        "model": args.model, "checkpoint": str(CKPT[args.model]),
        "classes": classes, "coverage": float(covered.mean()),
        "covered_items": int(covered.sum()), "n_items": n_items,
        "elapsed_seconds": time.time() - start,
    })
    print(f"[{args.model}] coverage {covered.mean():.4f} "
          f"({covered.sum()}/{n_items}) in {(time.time()-start)/60:.1f} min", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
