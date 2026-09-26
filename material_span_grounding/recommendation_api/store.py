from __future__ import annotations

import json
import math
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

import joblib
import numpy as np

from material_span.simple_m0_m1 import TEXTURE_ROOT, _human_corrected_claims


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PRODUCTS = PROJECT_ROOT / "data/derived/simple_m0_m1/products.json"
DEFAULT_VECTORS = PROJECT_ROOT / "data/derived/simple_m0_m1/product_vectors.npz"
DEFAULT_MODEL = PROJECT_ROOT / "artifacts/simple_m0_m1/m1_ridge.joblib"
DEFAULT_IMAGE_ROOT = TEXTURE_ROOT / "images_train"
DEFAULT_EVALUATION_METRICS = (
    PROJECT_ROOT / "data/recommendation_eval/temporal_v1/results/metrics.json"
)
DEFAULT_EVALUATION_PROTOCOL = (
    PROJECT_ROOT / "data/recommendation_eval/temporal_v1/manifest.json"
)
ASIN_RE = re.compile(r"^[A-Z0-9]{10}$")


def _normalize(matrix: np.ndarray) -> np.ndarray:
    values = np.asarray(matrix, dtype=np.float32)
    if values.ndim == 1:
        values = values[None, :]
    denominator = np.linalg.norm(values, axis=1, keepdims=True)
    return values / np.clip(denominator, 1e-12, None)


def _read_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


class RecommendationStore:
    """In-memory index over frozen image features and review material targets."""

    def __init__(
        self,
        *,
        products_path: Path = DEFAULT_PRODUCTS,
        vectors_path: Path = DEFAULT_VECTORS,
        model_path: Path = DEFAULT_MODEL,
        image_root: Path = DEFAULT_IMAGE_ROOT,
    ) -> None:
        self.products_path = Path(products_path)
        self.vectors_path = Path(vectors_path)
        self.model_path = Path(model_path)
        self.image_root = Path(image_root)

        self.products: list[dict[str, Any]] = _read_json(self.products_path)
        vectors = np.load(self.vectors_path, allow_pickle=False)
        asins = [str(value) for value in vectors["asins"]]
        if len(asins) != len(self.products):
            raise ValueError("Product metadata and vector counts do not match")
        product_asins = [str(row["asin"]) for row in self.products]
        if asins != product_asins:
            raise ValueError("Product metadata and vector ASIN order do not match")

        self.asins = asins
        self.index_by_asin = {asin: index for index, asin in enumerate(asins)}
        if len(self.index_by_asin) != len(asins):
            raise ValueError("Duplicate ASIN in recommendation catalog")

        self.image_raw = np.asarray(vectors["image"], dtype=np.float32)
        self.material_raw = np.asarray(vectors["material"], dtype=np.float32)
        if self.image_raw.shape != (len(asins), 1152):
            raise ValueError(f"Unexpected image feature shape: {self.image_raw.shape}")
        if self.material_raw.shape[0] != len(asins):
            raise ValueError("Unexpected material target count")

        self.image_index = _normalize(self.image_raw)
        development = np.array(
            [i for i, row in enumerate(self.products) if row.get("split") != "test"],
            dtype=int,
        )
        if not len(development):
            raise ValueError("No development products available to center material targets")
        self.material_mean = self.material_raw[development].mean(axis=0, keepdims=True)
        self.material_index = _normalize(self.material_raw - self.material_mean)

        artifact = joblib.load(self.model_path)
        self.scaler = artifact["scaler"]
        self.model = artifact["model"]
        self.sentence_model = str(artifact.get("sentence_model", "unknown"))
        self.best_alpha = float(artifact.get("best_alpha", math.nan))
        self.predicted_material = _normalize(
            self.model.predict(self.scaler.transform(self.image_raw))
        )
        self.evidence_by_asin = self._load_evidence()

    def _load_evidence(self) -> dict[str, list[dict[str, Any]]]:
        claims, _ = _human_corrected_claims()
        grouped: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
        for row in claims:
            asin = str(row["asin"])
            if asin not in self.index_by_asin:
                continue
            claim = str(row["claim"]).strip()
            key = claim.casefold()
            entry = grouped[asin].setdefault(
                key,
                {
                    "claim": claim,
                    "scope": row.get("scope") or "unknown",
                    "property_status": row.get("property_status") or "unknown",
                    "visual_observability": row.get("visual_observability") or "unknown",
                    "quotes": [],
                    "review_ids": [],
                    "users": set(),
                    "human_audited": False,
                },
            )
            quote = str(row.get("quote") or "").strip()
            review_id = str(row.get("review_id") or "")
            if quote and quote not in entry["quotes"]:
                entry["quotes"].append(quote)
            if review_id and review_id not in entry["review_ids"]:
                entry["review_ids"].append(review_id)
            entry["users"].add(str(row.get("user_id") or review_id))
            entry["human_audited"] = entry["human_audited"] or bool(
                row.get("human_audited")
            )

        output: dict[str, list[dict[str, Any]]] = {}
        for asin, claims_by_text in grouped.items():
            rows = []
            for entry in claims_by_text.values():
                users = entry.pop("users")
                entry["user_count"] = len(users)
                entry["evidence_count"] = len(entry["review_ids"])
                rows.append(entry)
            rows.sort(
                key=lambda row: (
                    -row["user_count"],
                    -row["evidence_count"],
                    row["claim"].casefold(),
                )
            )
            output[asin] = rows
        return output

    def health(self) -> dict[str, Any]:
        return {
            "status": "ok",
            "service": "material-recommendation-api",
            "catalog_products": len(self.products),
            "image_feature_dim": int(self.image_raw.shape[1]),
            "material_target_dim": int(self.material_raw.shape[1]),
            "evidence_products": len(self.evidence_by_asin),
            "methods": ["m0", "m1"],
            "model": "StandardScaler + multi-output Ridge",
            "protected_test_used_for_training": False,
            "offline_evaluation_available": DEFAULT_EVALUATION_METRICS.is_file(),
        }

    def evaluation(self) -> dict[str, Any]:
        if not DEFAULT_EVALUATION_METRICS.is_file():
            raise KeyError("Offline evaluation has not been generated")
        metrics = _read_json(DEFAULT_EVALUATION_METRICS)
        return {
            "status": metrics.get("status"),
            "k": metrics.get("k"),
            "cases": metrics.get("cases"),
            "models": metrics.get("models"),
            "paired_bootstrap": metrics.get("paired_bootstrap"),
            "interpretation_contract": metrics.get("interpretation_contract"),
        }

    def evaluation_protocol(self) -> dict[str, Any]:
        if not DEFAULT_EVALUATION_PROTOCOL.is_file():
            raise KeyError("Offline evaluation protocol has not been generated")
        return _read_json(DEFAULT_EVALUATION_PROTOCOL)

    def stats(self) -> dict[str, Any]:
        category_counts: dict[str, int] = defaultdict(int)
        user_counts: dict[str, int] = defaultdict(int)
        for product in self.products:
            category_counts[str(product.get("category", "other"))] += 1
            user_counts[str(product.get("users", 0))] += 1
        return {
            **self.health(),
            "categories": dict(sorted(category_counts.items())),
            "target_user_counts": dict(sorted(user_counts.items(), key=lambda item: int(item[0]))),
            "ridge_alpha": self.best_alpha,
            "sentence_model": self.sentence_model,
            "catalog": "human-corrected sparse pilot",
            "limitations": [
                "Most catalog targets are supported by one material-review user.",
                "M1 is experimental and has not yet shown significant improvement on the dense follow-up.",
                "Scores are retrieval similarities, not calibrated probabilities.",
            ],
        }

    def _public_product(self, index: int, *, include_evidence: bool = False) -> dict[str, Any]:
        product = self.products[index]
        asin = self.asins[index]
        evidence = self.evidence_by_asin.get(asin, [])
        payload = {
            "asin": asin,
            "title": product.get("title", ""),
            "category": product.get("category", "other"),
            "target_claim_count": int(product.get("claims", 0)),
            "target_user_count": int(product.get("users", 0)),
            "evidence_claim_count": len(evidence),
            "image_url": f"/images/{asin}.jpg" if (self.image_root / f"{asin}.jpg").is_file() else None,
        }
        if include_evidence:
            payload["evidence"] = evidence
        return payload

    def product(self, asin: str) -> dict[str, Any]:
        index = self.index_by_asin.get(asin)
        if index is None:
            raise KeyError(f"Unknown ASIN: {asin}")
        return self._public_product(index, include_evidence=True)

    def list_products(
        self,
        *,
        offset: int = 0,
        limit: int = 50,
        category: str | None = None,
        min_users: int = 0,
    ) -> dict[str, Any]:
        if offset < 0:
            raise ValueError("offset must be non-negative")
        if not 1 <= limit <= 200:
            raise ValueError("limit must be between 1 and 200")
        selected = [
            i
            for i, row in enumerate(self.products)
            if (category is None or row.get("category") == category)
            and int(row.get("users", 0)) >= min_users
        ]
        page = selected[offset : offset + limit]
        return {
            "total": len(selected),
            "offset": offset,
            "limit": limit,
            "items": [self._public_product(index) for index in page],
        }

    def search_by_asin(
        self,
        asin: str,
        *,
        method: str = "m1",
        k: int = 10,
        same_category: bool = False,
        min_users: int = 0,
        include_evidence: int = 3,
    ) -> dict[str, Any]:
        index = self.index_by_asin.get(asin)
        if index is None:
            raise KeyError(f"Unknown ASIN: {asin}")
        return self._search(
            image_vector=self.image_raw[index],
            query_asin=asin,
            query_category=self.products[index].get("category"),
            method=method,
            k=k,
            same_category=same_category,
            min_users=min_users,
            include_evidence=include_evidence,
        )

    def search_by_vector(
        self,
        image_vector: list[float],
        *,
        method: str = "m1",
        k: int = 10,
        category: str | None = None,
        min_users: int = 0,
        include_evidence: int = 3,
    ) -> dict[str, Any]:
        vector = np.asarray(image_vector, dtype=np.float32)
        if vector.shape != (self.image_raw.shape[1],):
            raise ValueError(
                f"image_vector must have exactly {self.image_raw.shape[1]} numbers"
            )
        if not np.isfinite(vector).all():
            raise ValueError("image_vector must contain only finite numbers")
        return self._search(
            image_vector=vector,
            query_asin=None,
            query_category=category,
            method=method,
            k=k,
            same_category=category is not None,
            min_users=min_users,
            include_evidence=include_evidence,
        )

    def _search(
        self,
        *,
        image_vector: np.ndarray,
        query_asin: str | None,
        query_category: str | None,
        method: str,
        k: int,
        same_category: bool,
        min_users: int,
        include_evidence: int,
    ) -> dict[str, Any]:
        method = method.casefold()
        if method not in {"m0", "m1"}:
            raise ValueError("method must be m0 or m1")
        if not 1 <= k <= 100:
            raise ValueError("k must be between 1 and 100")
        if not 0 <= include_evidence <= 20:
            raise ValueError("include_evidence must be between 0 and 20")
        if min_users < 0:
            raise ValueError("min_users must be non-negative")

        vector = np.asarray(image_vector, dtype=np.float32)[None, :]
        if method == "m0":
            query = _normalize(vector)[0]
            scores = self.image_index @ query
            score_name = "frozen_image_cosine"
        else:
            prediction = _normalize(
                self.model.predict(self.scaler.transform(vector))
            )[0]
            scores = self.material_index @ prediction
            score_name = "predicted_to_review_target_cosine"

        allowed = np.ones(len(self.products), dtype=bool)
        if query_asin is not None:
            allowed[self.index_by_asin[query_asin]] = False
        if same_category:
            if not query_category:
                raise ValueError("A category is required for same-category search")
            allowed &= np.array(
                [row.get("category") == query_category for row in self.products]
            )
        allowed &= np.array(
            [int(row.get("users", 0)) >= min_users for row in self.products]
        )
        candidates = np.flatnonzero(allowed)
        order = candidates[np.argsort(-scores[candidates], kind="stable")[:k]]
        results = []
        for rank, index in enumerate(order, 1):
            product = self._public_product(int(index))
            evidence = self.evidence_by_asin.get(self.asins[index], [])
            product.update(
                {
                    "rank": rank,
                    "score": float(scores[index]),
                    "score_name": score_name,
                    "evidence": evidence[:include_evidence],
                }
            )
            results.append(product)
        return {
            "query": {
                "asin": query_asin,
                "category": query_category,
                "method": method,
                "same_category": same_category,
                "min_users": min_users,
            },
            "count": len(results),
            "results": results,
            "warning": "Similarity scores are not calibrated confidence probabilities.",
        }

    def image_path(self, asin: str) -> Path:
        if not ASIN_RE.fullmatch(asin):
            raise KeyError("Invalid ASIN")
        path = self.image_root / f"{asin}.jpg"
        if not path.is_file():
            raise KeyError(f"Image not found: {asin}")
        return path
