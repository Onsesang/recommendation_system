from __future__ import annotations

import csv
import hashlib
from pathlib import Path
from typing import Any

import joblib
import numpy as np
from scipy.stats import spearmanr

from .common import (
    PATHS, axis_map, load_experiment, load_taxonomy, sha256_file, utc_now,
    write_json,
)


MLLM_DATASET_URL = "https://huggingface.co/datasets/EuniceF/MLLM-Fabric"
MLLM_REVISION = "d1563bf214bfdc3d46938c59545ef531552589ab"


def extract_mllm_fashionclip(batch_size: int = 32) -> dict[str, Any]:
    import torch
    from PIL import Image
    from transformers import AutoProcessor, CLIPModel

    image_root = PATHS.external / "mllm_fabric" / "Fabric-RGB"
    image_paths = sorted(image_root.glob("*.jpg"))
    if len(image_paths) != 220:
        raise RuntimeError(f"Expected 220 MLLM-Fabric RGB images, found {len(image_paths)}")
    output_path = PATHS.external / "mllm_fabric" / "fashionclip_embeddings.npz"
    if output_path.is_file():
        with np.load(output_path, allow_pickle=False) as arrays:
            if len(arrays["ids"]) == len(image_paths):
                return {"status": "complete", "cached": True, "images": len(image_paths), "output": str(output_path)}
    encoder = load_experiment()["image_encoders"]["fashionclip"]
    model_id = str(encoder["model_id"])
    revision = str(encoder["revision"])
    device = "cuda" if torch.cuda.is_available() else "cpu"
    processor = AutoProcessor.from_pretrained(model_id, revision=revision, local_files_only=True)
    model = CLIPModel.from_pretrained(model_id, revision=revision, local_files_only=True).eval().to(device)
    rows = []
    for start in range(0, len(image_paths), batch_size):
        images = []
        for path in image_paths[start:start + batch_size]:
            with Image.open(path) as image:
                images.append(image.convert("RGB"))
        inputs = {key: value.to(device) for key, value in processor(images=images, return_tensors="pt").items()}
        with torch.inference_mode():
            features = model.get_image_features(**inputs)
            if not isinstance(features, torch.Tensor):
                features = features.pooler_output
        values = features.float().cpu().numpy()
        values /= np.clip(np.linalg.norm(values, axis=1, keepdims=True), 1e-12, None)
        rows.extend(values)
    matrix = np.asarray(rows, dtype=np.float32)
    np.savez_compressed(output_path, ids=np.asarray([path.stem for path in image_paths]), image=matrix)
    return {"status": "complete", "cached": False, "images": len(image_paths), "output": str(output_path)}


def _pairwise_accuracy(target: np.ndarray, prediction: np.ndarray) -> tuple[float | None, int]:
    correct, total = 0, 0
    for left in range(len(target)):
        for right in range(left + 1, len(target)):
            delta = target[left] - target[right]
            if abs(delta) < 1e-12:
                continue
            correct += int(np.sign(prediction[left] - prediction[right]) == np.sign(delta))
            total += 1
    return (correct / total if total else None), total


def evaluate_external_transfer() -> dict[str, Any]:
    config = load_experiment()
    taxonomy = load_taxonomy()
    active = read_active_axes()
    label_path = PATHS.external / "mllm_fabric" / "Fabric-labels-only.csv"
    description_path = PATHS.external / "mllm_fabric" / "Fabric-whole-description.csv"
    readme_path = PATHS.external / "mllm_fabric" / "README.md"
    if not all(path.is_file() for path in (label_path, description_path, readme_path)):
        raise FileNotFoundError("MLLM-Fabric metadata was not acquired")
    extraction = extract_mllm_fashionclip()
    with np.load(extraction["output"], allow_pickle=False) as arrays:
        ids = np.asarray(arrays["ids"]).astype(str)
        image = np.asarray(arrays["image"], dtype=np.float32)
    with label_path.open(encoding="utf-8", newline="") as handle:
        label_rows = list(csv.DictReader(handle))
    labels = {str(row["ID"]).strip().zfill(3): row for row in label_rows}
    if any(value not in labels for value in ids):
        raise RuntimeError("MLLM image/label ID mismatch")
    bundles = joblib.load(PATHS.artifacts / "structured_model_bundles.joblib")
    split_seed = int(config["external"]["split_seed"])
    calibration_fraction = float(config["external"]["recoverability_calibration_fraction"])
    ordered = sorted(
        ids.tolist(),
        key=lambda value: hashlib.sha256(f"{split_seed}:{value}".encode()).hexdigest(),
    )
    calibration_count = max(1, min(len(ordered) - 1, round(len(ordered) * calibration_fraction)))
    calibration_ids = set(ordered[:calibration_count])
    calibration_mask = np.asarray([value in calibration_ids for value in ids], dtype=bool)
    test_mask = ~calibration_mask
    split_path = PATHS.manifests / "mllm_fabric_external_split.json"
    write_json(
        split_path,
        {
            "seed": split_seed,
            "method": "SHA256(seed:id) deterministic split",
            "recoverability_calibration_ids": sorted(ids[calibration_mask].tolist()),
            "external_test_ids": sorted(ids[test_mask].tolist()),
            "counts": {"recoverability_calibration": int(calibration_mask.sum()), "external_test": int(test_mask.sum())},
        },
    )
    axes = axis_map(taxonomy)
    results = {}
    recoverability = {}
    for axis_id in active:
        mapping = axes[axis_id].get("external_mapping", {}).get("mllm_fabric")
        bundle = bundles.get(f"{axis_id}:fashionclip_ridge")
        if mapping is None or bundle is None or bundle.get("type") != "ridge":
            results[axis_id] = {"status": "not_compatible_or_model_unavailable"}
            continue
        raw = np.asarray([int(labels[value][mapping["column"]]) for value in ids], dtype=int)
        value_mapping = {int(key): float(value) for key, value in mapping["values"].items()}
        target = np.asarray([value_mapping[value] for value in raw], dtype=np.float32)
        prediction = bundle["model"].predict(bundle["scaler"].transform(image)).astype(np.float32)
        test_target, test_prediction = target[test_mask], prediction[test_mask]
        calibration_target, calibration_prediction = target[calibration_mask], prediction[calibration_mask]
        correlation = None
        if np.std(test_target) > 1e-12 and np.std(test_prediction) > 1e-12:
            candidate_correlation = float(spearmanr(test_target, test_prediction).statistic)
            correlation = candidate_correlation if np.isfinite(candidate_correlation) else None
        pairwise, pair_count = _pairwise_accuracy(test_target, test_prediction)
        calibration_pairwise, calibration_pairs = _pairwise_accuracy(calibration_target, calibration_prediction)
        ordinal_prediction = np.asarray([min(value_mapping.values(), key=lambda item: abs(item - value)) for value in test_prediction])
        ordinal_accuracy = float(np.mean(ordinal_prediction == test_target))
        score = max(0.0, min(1.0, 2.0 * (calibration_pairwise - 0.5))) if calibration_pairwise is not None else 0.0
        results[axis_id] = {
            "status": "complete",
            "samples": int(len(test_target)),
            "split": "external_test",
            "label_distribution": {str(value): int(np.sum(test_target == value)) for value in sorted(set(test_target.tolist()))},
            "spearman": correlation,
            "pairwise_accuracy": pairwise,
            "pairwise_comparisons": pair_count,
            "ordinal_accuracy_without_scale_calibration": ordinal_accuracy,
            "recoverability_calibration": {
                "samples": int(len(calibration_target)),
                "pairwise_accuracy": calibration_pairwise,
                "pairwise_comparisons": calibration_pairs,
            },
        }
        recoverability[axis_id] = {
            "value": score,
            "formula": "clip(2 * (recoverability_calibration_pairwise_accuracy - 0.5), 0, 1)",
            "source": "mllm_fabric_recoverability_calibration_split_rgb_vs_semantic_property_labels",
        }
    result_path = PATHS.artifacts / "external_transfer_results.json"
    result = {
        "status": "complete",
        "phase": 8,
        "generated_at": utc_now(),
        "mllm_fabric": {
            "dataset_url": MLLM_DATASET_URL,
            "revision": MLLM_REVISION,
            "license": "Apache-2.0",
            "images": 220,
            "image_encoder": config["image_encoders"]["fashionclip"],
            "results": results,
            "label_limitations": "The released 0/1/2 semantic property labels are external dataset labels; they are not numerically merged with Amazon targets.",
            "split_policy": "Property recoverability uses only the deterministic calibration half; reported external metrics use the disjoint test half.",
        },
        "leeds": {
            "status": "unavailable_for_execution",
            "reason": "The thesis/paper is public, but a downloadable raw image-plus-rating release and redistribution license were not verified during this run.",
        },
        "property_recoverability": recoverability,
    }
    write_json(result_path, result)
    manifest = {
        "status": "complete_with_leeds_unavailable",
        "phase": 8,
        "generated_at": utc_now(),
        "results": str(result_path),
        "results_sha256": sha256_file(result_path),
        "input_hashes": {
            "labels": sha256_file(label_path),
            "descriptions": sha256_file(description_path),
            "dataset_card": sha256_file(readme_path),
            "embeddings": sha256_file(Path(extraction["output"])),
            "external_split": sha256_file(split_path),
        },
    }
    write_json(PATHS.manifests / "phase8_external.json", manifest)
    _write_report(result)
    return manifest


def read_active_axes() -> list[str]:
    import json
    with (PATHS.artifacts / "active_axes.json").open(encoding="utf-8") as handle:
        return [str(value) for value in json.load(handle)["active_axes"]]


def _write_report(result: dict[str, Any]) -> None:
    lines = [
        "# Phase 8 — External Tactile Transfer", "",
        "MLLM-Fabric: 220 RGB fabric images, Apache-2.0 dataset card. Amazon and external scales were evaluated separately.", "",
        "| Axis | Spearman | Pairwise accuracy | Recoverability |", "|---|---:|---:|---:|",
    ]
    for axis, metrics in result["mllm_fabric"]["results"].items():
        if metrics["status"] != "complete":
            lines.append(f"| {axis} | — | — | — |")
            continue
        recovery = result["property_recoverability"][axis]["value"]
        correlation = "—" if metrics["spearman"] is None else f"{metrics['spearman']:.3f}"
        lines.append(f"| {axis} | {correlation} | {metrics['pairwise_accuracy']:.3f} | {recovery:.3f} |")
    lines.extend(
        [
            "", "## Leeds status", "",
            result["leeds"]["reason"], "",
            "External failure or weak transfer is retained as a falsification result; it is not replaced with Amazon validation.",
        ]
    )
    (PATHS.reports / "phase8_external_transfer.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
