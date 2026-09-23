#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

import numpy as np
import torch
from torch.utils.data import DataLoader
from transformers import AutoProcessor, CLIPModel

from common import CONFIG_PATH, ROOT, atomic_json, read_json, sha256, sigmoid, source_hashes


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    config = read_json(CONFIG_PATH)
    artifacts = ROOT / "artifacts"
    predictions_path = artifacts / "fixed_model_predictions.npz"
    manifest_path = artifacts / "prediction_manifest.json"
    if args.verify_only:
        manifest = read_json(manifest_path)
        assert manifest["prediction_sha256"] == sha256(predictions_path)
        assert manifest["source_hashes"] == source_hashes(config)
        print(f"prediction_sha256={manifest['prediction_sha256']}")
        print("source_hashes_unchanged=PASS")
        return 0
    if predictions_path.exists() or manifest_path.exists():
        raise SystemExit("prediction artifact already exists; use --verify-only")

    seed = int(config["inference"]["seed"])
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    before_hashes = source_hashes(config)
    v3_config = read_json(Path(config["paths"]["v3_config"]))
    split = read_json(Path(config["paths"]["split_manifest"]))["splits"]
    metadata_rows = read_json(Path(config["paths"]["product_metadata"]))
    metadata = {str(row[config["product_id_field"]]): row for row in metadata_rows}

    with np.load(Path(config["paths"]["v3_targets"]), allow_pickle=False) as targets:
        all_ids = targets["product_ids"].astype(str)
        classes = targets["classes"].astype(str).tolist()
        values = targets["values"].astype(np.float32)
        masks = targets["mask"].astype(np.uint8)
    assert classes == config["classes"] == v3_config["classes"]
    index = {product_id: number for number, product_id in enumerate(all_ids)}
    selected_indices = {
        name: np.asarray([index[product_id] for product_id in split[name]], dtype=np.int64)
        for name in ("development", "test")
    }

    v3_scripts = Path(config["paths"]["v3_training_code"]).parent
    sys.path.insert(0, str(v3_scripts))
    from train_fashionclip import ProductDataset, TactileClassifier, configure, load_checkpoint, metrics, predict

    last2_checkpoint = load_checkpoint(Path(config["paths"]["last2_checkpoint"]))
    v3_results = read_json(Path(config["paths"]["v3_results"]))[config["evaluation"]["last2_regime"]]
    last2_thresholds = last2_checkpoint["thresholds"].cpu().numpy().astype(np.float32)
    assert last2_checkpoint["regime"] == config["evaluation"]["last2_regime"]
    assert last2_checkpoint["classes"] == classes
    assert np.allclose(last2_thresholds, v3_results["thresholds"], rtol=0, atol=1e-7)

    fashionclip_snapshot = Path(config["fashionclip_snapshot"])
    assert fashionclip_snapshot.is_dir()
    assert fashionclip_snapshot.name == v3_config["fashionclip"]["revision"]
    processor = AutoProcessor.from_pretrained(fashionclip_snapshot, local_files_only=True)
    clip = CLIPModel.from_pretrained(fashionclip_snapshot, local_files_only=True)
    last2_model = TactileClassifier(clip, len(classes))
    configure(last2_model, "last2")
    incompatible = last2_model.load_state_dict(last2_checkpoint["state_dict"], strict=False)
    assert not incompatible.unexpected_keys
    assert set(last2_checkpoint["state_dict"]) <= set(last2_model.state_dict())
    device = torch.device(config["inference"]["device"])
    last2_model = last2_model.to(device)

    last2_logits: dict[str, np.ndarray] = {}
    parity: dict[str, dict[str, float]] = {}
    for name in ("development", "test"):
        indices = selected_indices[name]
        dataset = ProductDataset(
            all_ids[indices],
            values[indices],
            masks[indices].astype(np.float32),
            Path(v3_config["image_root"]),
            processor,
            False,
        )
        loader = DataLoader(
            dataset,
            batch_size=int(config["inference"]["batch_size"]),
            shuffle=False,
            num_workers=int(config["inference"]["num_workers"]),
            pin_memory=True,
            persistent_workers=int(config["inference"]["num_workers"]) > 0,
        )
        logits, loaded_values, loaded_masks = predict(last2_model, loader, device)
        assert np.array_equal(loaded_values, values[indices])
        assert np.array_equal(loaded_masks, masks[indices].astype(bool))
        last2_logits[name] = logits.astype(np.float32)
        calculated = metrics(logits, loaded_values, loaded_masks, last2_thresholds, classes)
        expected = v3_results["development" if name == "development" else "test"]
        parity[name] = {
            metric: abs(float(calculated[metric]) - float(expected[metric]))
            for metric in ("macro_f1", "micro_f1", "macro_average_precision")
        }
        assert max(parity[name].values()) < 1e-7, (name, parity[name])

    del last2_model, clip
    torch.cuda.empty_cache()

    category_checkpoint = torch.load(
        Path(config["paths"]["category_checkpoint"]), map_location="cpu", weights_only=True
    )
    category_results = read_json(Path(config["paths"]["category_results"]))
    assert category_checkpoint["classes"] == classes
    category_thresholds = category_checkpoint["thresholds"].numpy().astype(np.float32)
    assert np.allclose(
        category_thresholds,
        [category_results["selected_thresholds"][name] for name in classes],
        rtol=0,
        atol=1e-7,
    )
    embedding_dimension = category_checkpoint["state_dict"]["category_embedding.weight"].shape[1]
    category_model = torch.nn.Sequential()
    category_embedding = torch.nn.Embedding(
        len(category_checkpoint["category_vocabulary"]), embedding_dimension
    )
    category_classifier = torch.nn.Linear(embedding_dimension, len(classes))
    category_embedding.load_state_dict(
        {"weight": category_checkpoint["state_dict"]["category_embedding.weight"]}
    )
    category_classifier.load_state_dict(
        {
            "weight": category_checkpoint["state_dict"]["classifier.weight"],
            "bias": category_checkpoint["state_dict"]["classifier.bias"],
        }
    )
    category_embedding.eval()
    category_classifier.eval()
    category_to_id = {
        category: number for number, category in enumerate(category_checkpoint["category_vocabulary"])
    }
    category_logits: dict[str, np.ndarray] = {}
    with torch.inference_mode():
        for name in ("development", "test"):
            category_ids = torch.tensor(
                [category_to_id.get(str(metadata[product_id][config["category_field"]]), 0) for product_id in split[name]],
                dtype=torch.long,
            )
            category_logits[name] = category_classifier(category_embedding(category_ids)).numpy().astype(np.float32)

    artifacts.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        predictions_path,
        classes=np.asarray(classes),
        development_product_ids=np.asarray(split["development"]),
        test_product_ids=np.asarray(split["test"]),
        development_last2_probabilities=sigmoid(last2_logits["development"]).astype(np.float32),
        test_last2_probabilities=sigmoid(last2_logits["test"]).astype(np.float32),
        development_category_probabilities=sigmoid(category_logits["development"]).astype(np.float32),
        test_category_probabilities=sigmoid(category_logits["test"]).astype(np.float32),
        last2_thresholds=last2_thresholds,
        category_thresholds=category_thresholds,
    )
    after_hashes = source_hashes(config)
    assert after_hashes == before_hashes
    manifest = {
        "status": "complete_fixed_checkpoint_inference_only",
        "new_training_performed": False,
        "parameter_updates_performed": False,
        "threshold_tuning_performed": False,
        "inference_splits": ["development", "test"],
        "last2_checkpoint_sha256": before_hashes["last2_checkpoint"],
        "category_checkpoint_sha256": before_hashes["category_checkpoint"],
        "last2_checkpoint_epoch": int(last2_checkpoint["best_epoch"]),
        "last2_threshold_source": config["evaluation"]["threshold_source"],
        "category_threshold_source": config["evaluation"]["category_threshold_source"],
        "v3_metric_reproduction_absolute_error": parity,
        "prediction_sha256": sha256(predictions_path),
        "source_hashes": before_hashes,
        "source_hashes_unchanged_after_inference": True,
    }
    atomic_json(manifest_path, manifest)
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
