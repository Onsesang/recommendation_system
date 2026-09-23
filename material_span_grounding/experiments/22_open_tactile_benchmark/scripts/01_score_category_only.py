#!/usr/bin/env python3
"""Score the experiment-13 category-only baseline on Track A.

This model sees no pixels at all: it maps a train-vocabulary category id to 14
tactile logits.  It is the control that says how much of any image model's
apparent accuracy is really a category shortcut.

It cannot be run on FabricVST (there is no apparel category for a fabric swatch),
so Track B leaves it out rather than inventing a category assignment.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np
import torch

import common22 as C

EXP13 = C.PROJECT / "experiments/13_category_only_baseline"
sys.path.insert(0, str(EXP13 / "scripts"))
from common import CategoryClassifier  # noqa: E402

SCORES = C.CACHE / "scores"
SCORES.mkdir(parents=True, exist_ok=True)


def main() -> int:
    manifest = C.read_json(EXP13 / "artifacts/preparation_manifest.json")
    vocabulary = list(manifest["category_vocabulary"])
    lookup = {name: i for i, name in enumerate(vocabulary)}
    unknown = lookup["<UNK>"]

    saved = torch.load(C.CKPT["category_only"], map_location="cpu", weights_only=True)
    classes = [str(c) for c in saved["classes"]]
    config = C.read_json(EXP13 / "config.json")
    model = CategoryClassifier(len(vocabulary), config["model"]["embedding_dimension"], len(classes))
    model.load_state_dict(saved["state_dict"])
    model.eval()

    for split in ("development", "test"):
        data = C.load_amazon(split)
        ids = torch.tensor([lookup.get(c, unknown) for c in data["categories"]], dtype=torch.long)
        with torch.inference_mode():
            probabilities = torch.sigmoid(model(ids)).numpy().astype(np.float32)
        np.savez_compressed(
            SCORES / f"category_only__amazon_{split}.npz",
            probabilities=probabilities, classes=np.array(classes),
            thresholds=np.asarray(saved.get("thresholds", [0.5] * len(classes)), dtype=np.float32),
            unit_ids=np.array(data["product_ids"]),
            paths=np.array([str(p) for p in data["image_paths"]]),
            category_ids=ids.numpy(),
        )
        distinct = len(set(map(tuple, probabilities.round(6))))
        print(f"{split}: {len(data['product_ids'])} products, "
              f"{distinct} distinct score vectors (= number of categories seen)", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
