#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import tempfile
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
import pandas as pd
import torch
from PIL import Image
from torch import nn
from torch.utils.data import DataLoader, Dataset
from transformers import AutoProcessor, CLIPModel

from common import ARTIFACTS, CONFIG_PATH, atomic_json, read_json, sha256


class ImageDataset(Dataset):
    def __init__(self, rows, processor):
        self.rows = rows
        self.processor = processor

    def __len__(self):
        return len(self.rows)

    def __getitem__(self, index):
        row = self.rows[index]
        with Image.open(row["image_path"]) as image:
            pixels = self.processor(images=image.convert("RGB"), return_tensors="pt").pixel_values[0]
        return index, pixels


class TactileClassifier(nn.Module):
    def __init__(self, clip: CLIPModel, classes: int):
        super().__init__()
        self.vision = clip.vision_model
        self.projection = clip.visual_projection
        self.head = nn.Linear(self.projection.out_features, classes)

    def forward(self, pixels):
        output = self.vision(pixel_values=pixels)
        features = nn.functional.normalize(self.projection(output.pooler_output), dim=-1)
        return self.head(features)


def _mode(values: list[str]) -> str:
    counts = Counter(values)
    maximum = max(counts.values())
    return sorted(key for key, value in counts.items() if value == maximum)[0]


def main() -> int:
    config = read_json(CONFIG_PATH)
    cfg = config["fashionclip"]
    output_path = ARTIFACTS / "product_tactile_profiles.parquet"
    manifest_path = ARTIFACTS / "tactile_profile_manifest.json"
    checkpoint_path = Path(cfg["checkpoint"])
    checkpoint_hash_before = sha256(checkpoint_path)
    checkpoint = torch.load(checkpoint_path, map_location="cpu", weights_only=True)
    if checkpoint["regime"] != "last2":
        raise ValueError(f"official checkpoint is not last2: {checkpoint['regime']}")
    classes = list(checkpoint["classes"])
    metadata = read_json(config["tactile_product_metadata"])
    missing = [row["product_id"] for row in metadata if not Path(row["image_path"]).is_file()]
    if missing:
        raise FileNotFoundError(f"{len(missing)} tactile images are missing; first={missing[0]}")
    metadata.sort(key=lambda row: str(row["product_id"]))

    processor = AutoProcessor.from_pretrained(cfg["snapshot"], local_files_only=True)
    clip = CLIPModel.from_pretrained(cfg["snapshot"], local_files_only=True)
    model = TactileClassifier(clip, len(classes))
    incompatible = model.load_state_dict(checkpoint["state_dict"], strict=False)
    if incompatible.unexpected_keys:
        raise ValueError(f"unexpected checkpoint keys: {incompatible.unexpected_keys}")
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model.to(device).eval()
    loader = DataLoader(
        ImageDataset(metadata, processor),
        batch_size=int(cfg["batch_size"]),
        shuffle=False,
        num_workers=int(cfg["num_workers"]),
        pin_memory=device.type == "cuda",
        persistent_workers=int(cfg["num_workers"]) > 0,
    )
    probabilities = np.empty((len(metadata), len(classes)), dtype=np.float32)
    with torch.inference_mode():
        for indices, pixels in loader:
            pixels = pixels.to(device, non_blocking=True)
            if device.type == "cuda":
                with torch.autocast("cuda", dtype=torch.bfloat16):
                    logits = model(pixels)
            else:
                logits = model(pixels)
            probabilities[indices.numpy()] = torch.sigmoid(logits.float()).cpu().numpy()

    split_document = read_json(config["v3_family_split"])
    family_to_split = {
        str(family): split_name
        for split_name, families in split_document["families"].items()
        for family in families
    }
    by_parent: dict[str, list[int]] = defaultdict(list)
    for number, row in enumerate(metadata):
        by_parent[str(row["parent_asin"])].append(number)
    output_rows = []
    split_counts = Counter()
    for parent_asin in sorted(by_parent):
        indices = by_parent[parent_asin]
        rows = [metadata[number] for number in indices]
        vectors = probabilities[indices]
        splits = sorted({family_to_split.get(str(row["product_family_id"]), "unknown") for row in rows})
        split_name = splits[0] if len(splits) == 1 else "mixed:" + "+".join(splits)
        split_counts[split_name] += 1
        representative = rows[0]
        output = {
            "item_id": parent_asin,
            "parent_asin": parent_asin,
            "child_count": len(rows),
            "child_asins": json.dumps([str(row["product_id"]) for row in rows]),
            "category": _mode([str(row["category"]) for row in rows]),
            "representative_product_id": str(representative["product_id"]),
            "image_path": str(representative["image_path"]),
            "v3_family_split": split_name,
        }
        output.update({name: float(value) for name, value in zip(classes, vectors.mean(axis=0))})
        output_rows.append(output)
    frame = pd.DataFrame(output_rows)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{output_path.name}.", dir=output_path.parent)
    os.close(descriptor)
    try:
        frame.to_parquet(temporary, index=False)
        os.replace(temporary, output_path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    checkpoint_hash_after = sha256(checkpoint_path)
    if checkpoint_hash_before != checkpoint_hash_after:
        raise RuntimeError("Last2 checkpoint changed during inference")
    manifest = {
        "status": "complete",
        "model": cfg["model_id"],
        "model_revision": cfg["revision"],
        "checkpoint": str(checkpoint_path),
        "checkpoint_sha256_before": checkpoint_hash_before,
        "checkpoint_sha256_after": checkpoint_hash_after,
        "checkpoint_unchanged": True,
        "regime": checkpoint["regime"],
        "best_epoch": int(checkpoint["best_epoch"]),
        "classes": classes,
        "class_order_source": "official Last2 checkpoint",
        "preprocessing_source": "pinned FashionCLIP AutoProcessor",
        "device": str(device),
        "child_products": len(metadata),
        "parent_profiles": len(frame),
        "aggregation": config["catalog"]["child_aggregation"],
        "parents_with_multiple_children": int((frame["child_count"] > 1).sum()),
        "maximum_children_per_parent": int(frame["child_count"].max()),
        "missing_images": len(missing),
        "v3_family_split_counts": dict(sorted(split_counts.items())),
        "output": str(output_path),
        "output_sha256": sha256(output_path),
        "no_retraining": True,
        "no_thresholding": True,
        "continuous_probabilities": True,
    }
    atomic_json(manifest_path, manifest)
    print(json.dumps({key: manifest[key] for key in ("status", "device", "child_products", "parent_profiles", "aggregation", "v3_family_split_counts")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
