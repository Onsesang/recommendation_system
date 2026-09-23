from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np

from .common import ROOT, read_jsonl, save_json, write_jsonl
from .protocol import DEFAULT_OUTPUT


DEFAULT_MATERIAL_VECTORS = ROOT / "data/derived/simple_m0_m1/product_vectors.npz"
DEFAULT_MATERIAL_PRODUCTS = ROOT / "data/derived/simple_m0_m1/products.json"


def _load_tactile_index(
    vectors_path: Path = DEFAULT_MATERIAL_VECTORS,
    products_path: Path = DEFAULT_MATERIAL_PRODUCTS,
) -> tuple[dict[str, np.ndarray], int]:
    vectors = np.load(vectors_path, allow_pickle=False)
    asins = [str(value) for value in vectors["asins"]]
    material = np.asarray(vectors["material"], dtype=np.float32)
    products = json.loads(products_path.read_text(encoding="utf-8"))
    development = np.array(
        [i for i, row in enumerate(products) if row.get("split") != "test"], dtype=int
    )
    mean = material[development].mean(axis=0, keepdims=True)
    centered = material - mean
    centered /= np.clip(np.linalg.norm(centered, axis=1, keepdims=True), 1e-12, None)
    return dict(zip(asins, centered)), int(centered.shape[1])


def generate_baseline_predictions(
    *,
    protocol_root: Path = DEFAULT_OUTPUT,
    output_root: Path | None = None,
    hybrid_weight: float = 0.5,
) -> dict[str, Any]:
    if not 0.0 <= hybrid_weight <= 1.0:
        raise ValueError("hybrid_weight must be between 0 and 1")
    protocol_root = Path(protocol_root)
    output_root = Path(output_root or protocol_root / "predictions")
    cases = read_jsonl(protocol_root / "cases.jsonl")
    tactile, tactile_dim = _load_tactile_index()
    rows: dict[str, list[dict[str, Any]]] = {
        "popularity": [],
        "tactile_only": [],
        "popularity_tactile": [],
    }
    tactile_profile_cases = 0
    for case in cases:
        candidates = case["candidates"]
        if len(case.get("candidate_train_counts", [])) != len(candidates):
            raise ValueError("Protocol case lacks aligned candidate_train_counts")
        popularity = np.log1p(
            np.array(case["candidate_train_counts"], dtype=np.float32)
        )
        history_vectors = [tactile[item] for item in case["train_items"] if item in tactile]
        has_profile = bool(history_vectors)
        if has_profile:
            tactile_profile_cases += 1
            profile = np.mean(np.stack(history_vectors), axis=0)
            profile /= max(float(np.linalg.norm(profile)), 1e-12)
            tactile_scores = np.array(
                [float(profile @ tactile[item]) if item in tactile else -1.0 for item in candidates],
                dtype=np.float32,
            )
        else:
            tactile_scores = np.full(len(candidates), -1.0, dtype=np.float32)

        pop_scale = float(popularity.std())
        pop_z = (popularity - popularity.mean()) / (pop_scale if pop_scale > 1e-12 else 1.0)
        tactile_available = tactile_scores > -1.0
        if tactile_available.any():
            available_values = tactile_scores[tactile_available]
            tactile_scale = float(available_values.std())
            tactile_z = np.zeros_like(tactile_scores)
            tactile_z[tactile_available] = (
                available_values - available_values.mean()
            ) / (tactile_scale if tactile_scale > 1e-12 else 1.0)
        else:
            tactile_z = np.zeros_like(tactile_scores)

        score_sets = {
            "popularity": popularity,
            "tactile_only": tactile_scores if has_profile else popularity,
            "popularity_tactile": (
                (1.0 - hybrid_weight) * pop_z + hybrid_weight * tactile_z
                if has_profile
                else pop_z
            ),
        }
        for name, scores in score_sets.items():
            order = np.argsort(-scores, kind="stable")
            rows[name].append(
                {
                    "case_id": case["case_id"],
                    "ranked_items": [candidates[int(index)] for index in order],
                }
            )

    output_root.mkdir(parents=True, exist_ok=True)
    paths = {}
    for name, values in rows.items():
        path = output_root / f"{name}.jsonl"
        write_jsonl(path, values)
        paths[name] = str(path)
    manifest = {
        "status": "complete",
        "cases": len(cases),
        "models": paths,
        "tactile_profile_cases": tactile_profile_cases,
        "tactile_profile_case_rate": tactile_profile_cases / len(cases) if cases else 0.0,
        "tactile_catalog_items": len(tactile),
        "tactile_dimension": tactile_dim,
        "hybrid_weight": hybrid_weight,
        "warning": (
            "Tactile baselines fall back to popularity when no history item has a tactile target; "
            "always interpret them with tactile profile and item coverage."
        ),
    }
    save_json(output_root / "manifest.json", manifest)
    return manifest
