from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from .common import PATHS, load_experiment, read_json, sha256_file, utc_now, write_json


def extract_dino_embeddings() -> dict[str, Any]:
    import torch
    from PIL import Image
    from transformers import AutoImageProcessor, AutoModel

    config = load_experiment()
    encoder = config["image_encoders"]["dino"]
    model_id = str(encoder["model_id"])
    output_path = PATHS.artifacts / "dino_image_embeddings.npz"
    products = read_json(Path(config["inputs"]["product_master"]))
    ids = [str(row["product_id"]) for row in products]
    if output_path.is_file():
        with np.load(output_path, allow_pickle=False) as arrays:
            if np.array_equal(np.asarray(arrays["product_ids"]).astype(str), np.asarray(ids)):
                return {"status": "complete", "cached": True, "output": str(output_path), "products": len(ids)}
    processor = AutoImageProcessor.from_pretrained(model_id, revision=str(encoder["revision"]))
    model = AutoModel.from_pretrained(model_id, revision=str(encoder["revision"])).eval()
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model.to(device)
    image_root = Path(config["inputs"]["image_root"])
    rows = []
    batch_size = int(encoder["batch_size"])
    for start in range(0, len(ids), batch_size):
        images = []
        for product_id in ids[start:start + batch_size]:
            with Image.open(image_root / f"{product_id}.jpg") as image:
                images.append(image.convert("RGB"))
        inputs = {key: value.to(device) for key, value in processor(images=images, return_tensors="pt").items()}
        with torch.inference_mode():
            output = model(**inputs)
            features = output.pooler_output if getattr(output, "pooler_output", None) is not None else output.last_hidden_state[:, 0]
        values = features.float().cpu().numpy()
        values /= np.clip(np.linalg.norm(values, axis=1, keepdims=True), 1e-12, None)
        rows.extend(values)
        print(f"DINO embeddings: {min(start + batch_size, len(ids))}/{len(ids)}", flush=True)
    matrix = np.asarray(rows, dtype=np.float32)
    np.savez_compressed(output_path, product_ids=np.asarray(ids), image=matrix)
    result = {
        "status": "complete", "phase": 6, "generated_at": utc_now(),
        "model_id": model_id, "requested_revision": encoder["revision"],
        "resolved_revision": getattr(model.config, "_commit_hash", None),
        "frozen": True, "products": len(ids), "dimension": int(matrix.shape[1]),
        "output": str(output_path), "output_sha256": sha256_file(output_path),
    }
    write_json(PATHS.manifests / "phase6_dino_features.json", result)
    return result
