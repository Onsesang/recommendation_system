from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np

from material_span.common import sha256_file


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MULTIMODAL_ROOT = ROOT / "data" / "derived" / "multimodal_catalog_v1"


class MultimodalProductIndex:
    """Validated product-master index independent of review availability."""

    def __init__(self, root: Path = DEFAULT_MULTIMODAL_ROOT) -> None:
        self.root = Path(root)
        stage2 = json.loads((self.root / "stage2_manifest.json").read_text(encoding="utf-8"))
        stage7 = json.loads((self.root / "stage7_manifest.json").read_text(encoding="utf-8"))
        # Manifests record absolute paths from the machine that built them; the outputs sit
        # beside the manifests, so resolve by file name and let the hash check guard content.
        products_path = self.root / Path(stage7["outputs"]["products"]).name
        image_path = self.root / Path(stage2["outputs"]["vectors"]).name
        tactile_path = self.root / Path(stage7["outputs"]["vectors"]).name
        for path, expected in (
            (products_path, stage7["outputs"]["products_sha256"]),
            (image_path, stage2["outputs"]["vectors_sha256"]),
            (tactile_path, stage7["outputs"]["vectors_sha256"]),
        ):
            if not path.is_file() or sha256_file(path) != expected:
                raise ValueError(f"Multimodal artifact hash mismatch: {path}")

        self.products: list[dict[str, Any]] = json.loads(products_path.read_text(encoding="utf-8"))
        self.product_ids = [str(row["product_id"]) for row in self.products]
        self.product_by_id = {str(row["product_id"]): row for row in self.products}
        self.canonical_by_id: dict[str, str] = {}
        for row in self.products:
            representative = str(row["product_id"])
            for alias in row.get("alias_product_ids", [representative]):
                self.canonical_by_id[str(alias)] = representative
            self.canonical_by_id[representative] = representative
        if len(self.product_by_id) != len(self.products):
            raise ValueError("Duplicate product_id in multimodal product master")

        with np.load(image_path, allow_pickle=False) as arrays:
            image_ids = [str(value) for value in arrays["asins"]]
            image = np.asarray(arrays["image"], dtype=np.float32)
        with np.load(tactile_path, allow_pickle=False) as arrays:
            tactile_ids = [str(value) for value in arrays["asins"]]
            predicted = np.asarray(arrays["image_predicted"], dtype=np.float32)
            hybrid = np.asarray(arrays["hybrid"], dtype=np.float32)
            confidence = np.asarray(arrays["confidence"], dtype=np.float32)
            source = [str(value) for value in arrays["target_source"]]
        if image_ids != self.product_ids or tactile_ids != self.product_ids:
            raise ValueError("Multimodal product/vector order mismatch")
        if image.shape != (len(self.products), 512):
            raise ValueError(f"Unexpected FashionCLIP matrix shape: {image.shape}")
        if predicted.shape != hybrid.shape or hybrid.shape != (len(self.products), 384):
            raise ValueError(f"Unexpected tactile matrix shape: {hybrid.shape}")
        if not np.isfinite(image).all() or not np.isfinite(hybrid).all():
            raise ValueError("Non-finite multimodal vectors")
        if not np.allclose(np.linalg.norm(image, axis=1), 1.0, atol=1e-5):
            raise ValueError("FashionCLIP vectors are not normalized")
        if not np.allclose(np.linalg.norm(hybrid, axis=1), 1.0, atol=1e-5):
            raise ValueError("Hybrid tactile vectors are not normalized")
        self._index = {product_id: index for index, product_id in enumerate(self.product_ids)}
        self.image = image
        self.predicted_tactile = predicted
        self.hybrid_tactile = hybrid
        self.confidence = confidence
        self.source = source

    def canonical(self, product_id: str) -> str:
        try:
            return self.canonical_by_id[product_id]
        except KeyError as exc:
            raise KeyError(f"Unknown product: {product_id}") from exc

    def image_vector(self, product_id: str) -> np.ndarray:
        canonical = self.canonical(product_id)
        return self.image[self._index[canonical]]

    def tactile_vector(self, product_id: str) -> np.ndarray:
        canonical = self.canonical(product_id)
        return self.hybrid_tactile[self._index[canonical]]

    def target_info(self, product_id: str) -> dict[str, Any]:
        canonical = self.canonical(product_id)
        index = self._index[canonical]
        row = self.product_by_id[canonical]
        return {
            "tactile_target_source": self.source[index],
            "review_weight": float(row["review_weight"]),
            "image_weight": float(row["image_weight"]),
            "image_prediction_confidence": float(row["image_prediction_confidence"]),
            "tactile_target_confidence": float(self.confidence[index]),
        }
