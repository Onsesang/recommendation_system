#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import random
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from material_span.common import ROOT, save_json, sha256_file
from recommendation_api.store import DEFAULT_IMAGE_ROOT
from recommendation_api.tactile_catalog import TactileCatalogService
from recommendation_api.tactile_store import TactileStore


DEFAULT_OUTPUT_ROOT = ROOT / "data" / "derived" / "multimodal_catalog_v1"
FASHION_CLIP_MODEL = "patrickjohncyh/fashion-clip"


def build_product_master(
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    image_root: Path = DEFAULT_IMAGE_ROOT,
) -> dict[str, Any]:
    output_root = Path(output_root)
    image_root = Path(image_root)
    store = TactileStore()
    catalog = TactileCatalogService(store, image_root=image_root)
    grouped: dict[str, list[str]] = defaultdict(list)
    for asin in store.source_asins:
        grouped[catalog._identity_by_asin[asin]].append(asin)

    products = []
    missing_images = []
    for representative in catalog.catalog_asins:
        identity = catalog._identity_by_asin[representative]
        aliases = sorted(grouped[identity])
        image_path = image_root / f"{representative}.jpg"
        if not image_path.is_file():
            missing_images.append(representative)
            image_sha256 = None
        else:
            image_sha256 = sha256_file(image_path)
        profile = store._profile_cache[representative]
        products.append(
            {
                **store.product_metadata[representative],
                "product_family_id": identity,
                "alias_product_ids": aliases,
                "image_filename": image_path.name,
                "image_sha256": image_sha256,
                "has_review_target": store.vector(representative) is not None,
                "reviewer_count": profile.reviewer_count,
                "claim_count": profile.claim_count,
            }
        )

    if missing_images:
        raise RuntimeError(f"Missing product images: {missing_images[:10]}")
    if len(products) != len({row["product_family_id"] for row in products}):
        raise RuntimeError("Duplicate product family remains in visible product master")

    output_root.mkdir(parents=True, exist_ok=True)
    products_path = output_root / "product_master.json"
    save_json(products_path, products)
    manifest = {
        "status": "complete",
        "stage": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_records": len(store.source_asins),
        "visible_products": len(products),
        "duplicate_records_collapsed": len(store.source_asins) - len(products),
        "products_with_review_target": sum(row["has_review_target"] for row in products),
        "products_without_review_target": sum(not row["has_review_target"] for row in products),
        "image_root": str(image_root.resolve()),
        "missing_images": 0,
        "outputs": {
            "product_master": str(products_path.resolve()),
            "product_master_sha256": sha256_file(products_path),
        },
    }
    save_json(output_root / "stage1_manifest.json", manifest)
    return manifest


def extract_image_embeddings(
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    image_root: Path = DEFAULT_IMAGE_ROOT,
    batch_size: int = 32,
) -> dict[str, Any]:
    import numpy as np
    import torch
    from PIL import Image
    from transformers import AutoProcessor, CLIPModel

    output_root = Path(output_root)
    image_root = Path(image_root)
    master_path = output_root / "product_master.json"
    stage1 = json.loads((output_root / "stage1_manifest.json").read_text(encoding="utf-8"))
    if sha256_file(master_path) != stage1["outputs"]["product_master_sha256"]:
        raise RuntimeError("Product master hash no longer matches stage 1 manifest")
    products = json.loads(master_path.read_text(encoding="utf-8"))
    asins = [str(row["product_id"]) for row in products]
    checkpoint_path = output_root / "image_embeddings.checkpoint.npz"
    completed_asins: list[str] = []
    completed_vectors: list[np.ndarray] = []
    if checkpoint_path.is_file():
        with np.load(checkpoint_path, allow_pickle=False) as checkpoint:
            completed_asins = [str(value) for value in checkpoint["asins"]]
            completed_vectors = [row for row in checkpoint["image"]]
        if asins[: len(completed_asins)] != completed_asins:
            raise RuntimeError("Image embedding checkpoint does not match product master")

    device = "cuda" if torch.cuda.is_available() else "cpu"
    processor = AutoProcessor.from_pretrained(FASHION_CLIP_MODEL, local_files_only=True)
    model = CLIPModel.from_pretrained(FASHION_CLIP_MODEL, local_files_only=True)
    model.eval().to(device)
    for start in range(len(completed_asins), len(asins), batch_size):
        batch_asins = asins[start : start + batch_size]
        images = []
        for asin in batch_asins:
            with Image.open(image_root / f"{asin}.jpg") as image:
                images.append(image.convert("RGB"))
        inputs = processor(images=images, return_tensors="pt")
        inputs = {key: value.to(device) for key, value in inputs.items()}
        with torch.inference_mode(), torch.autocast(
            device_type="cuda", dtype=torch.float16, enabled=device == "cuda"
        ):
            output = model.get_image_features(**inputs)
            features = output if isinstance(output, torch.Tensor) else output.pooler_output
        vectors = features.float().cpu().numpy()
        vectors /= np.clip(np.linalg.norm(vectors, axis=1, keepdims=True), 1e-12, None)
        completed_asins.extend(batch_asins)
        completed_vectors.extend(vectors)
        np.savez_compressed(
            checkpoint_path,
            asins=np.asarray(completed_asins),
            image=np.asarray(completed_vectors, dtype=np.float32),
        )
        print(f"image embeddings: {len(completed_asins)}/{len(asins)}", flush=True)

    matrix = np.asarray(completed_vectors, dtype=np.float32)
    if matrix.shape[0] != len(asins) or not np.isfinite(matrix).all():
        raise RuntimeError(f"Invalid image embedding matrix: {matrix.shape}")
    if not np.allclose(np.linalg.norm(matrix, axis=1), 1.0, atol=1e-5):
        raise RuntimeError("Image embeddings are not L2 normalized")
    vectors_path = output_root / "fashionclip_image_embeddings.npz"
    np.savez_compressed(vectors_path, asins=np.asarray(asins), image=matrix)
    checkpoint_path.unlink(missing_ok=True)
    manifest = {
        "status": "complete",
        "stage": 2,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "model": FASHION_CLIP_MODEL,
        "model_revision": getattr(model.config, "_commit_hash", None),
        "device": device,
        "products": len(asins),
        "dimension": int(matrix.shape[1]),
        "normalized": True,
        "input_product_master_sha256": sha256_file(master_path),
        "outputs": {
            "vectors": str(vectors_path.resolve()),
            "vectors_sha256": sha256_file(vectors_path),
        },
    }
    save_json(output_root / "stage2_manifest.json", manifest)
    return manifest


def evaluate_design_retrieval(output_root: Path = DEFAULT_OUTPUT_ROOT) -> dict[str, Any]:
    import numpy as np

    store = TactileStore()
    catalog = TactileCatalogService(store, multimodal_root=output_root)
    checked = 0
    category_matches = 0
    duplicate_leaks = 0
    missing_visual = 0
    finite_scores = 0
    for anchor in catalog.catalog_asins:
        result = catalog.related(anchor, limit=10)
        anchor_identity = catalog._identity_by_asin[anchor]
        for row in result["design_similar"]:
            checked += 1
            category_matches += row["category"] == result["category"]
            duplicate_leaks += catalog._identity_by_asin[row["product_id"]] == anchor_identity
            missing_visual += row["visual_similarity"] is None
            finite_scores += bool(np.isfinite(row["relevance_score"]))
    report = {
        "status": "complete",
        "stage": 3,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "evaluation_type": "structural_full_catalog_no_human_relevance_labels",
        "anchors": len(catalog.catalog_asins),
        "pairs_checked": checked,
        "design_embedding_coverage": len(catalog._visual_by_asin) / len(store.source_asins),
        "category_precision": category_matches / checked if checked else 0.0,
        "duplicate_family_leaks": duplicate_leaks,
        "missing_visual_scores": missing_visual,
        "finite_score_rate": finite_scores / checked if checked else 0.0,
        "method": catalog._visual_method,
        "weights": store.config["related"],
        "limitation": "Structural checks do not measure human-perceived design relevance.",
    }
    path = Path(output_root) / "stage3_design_evaluation.json"
    save_json(path, report)
    report["output_sha256"] = sha256_file(path)
    save_json(Path(output_root) / "stage3_manifest.json", report)
    return report


def build_coldstart_split(
    output_root: Path = DEFAULT_OUTPUT_ROOT, seed: int = 20260813
) -> dict[str, Any]:
    output_root = Path(output_root)
    products = json.loads((output_root / "product_master.json").read_text(encoding="utf-8"))
    by_category: dict[str, list[str]] = defaultdict(list)
    inference_only = []
    for row in products:
        if row["has_review_target"]:
            by_category[str(row["category"])].append(str(row["product_id"]))
        else:
            inference_only.append(str(row["product_id"]))

    split = {"train": [], "development": [], "test": []}
    rng = random.Random(seed)
    category_counts = {}
    for category, product_ids in sorted(by_category.items()):
        product_ids = sorted(product_ids)
        rng.shuffle(product_ids)
        count = len(product_ids)
        if count >= 3:
            test_count = max(1, round(count * 0.15))
            development_count = max(1, round(count * 0.15))
        else:
            test_count = 0
            development_count = 0
        train_count = count - development_count - test_count
        split["train"].extend(product_ids[:train_count])
        split["development"].extend(
            product_ids[train_count : train_count + development_count]
        )
        split["test"].extend(product_ids[train_count + development_count :])
        category_counts[category] = {
            "total": count,
            "train": train_count,
            "development": development_count,
            "test": test_count,
        }
    for values in split.values():
        values.sort()
    all_split = split["train"] + split["development"] + split["test"]
    if len(all_split) != len(set(all_split)):
        raise RuntimeError("A product family appears in multiple cold-start splits")
    if set(all_split) & set(inference_only):
        raise RuntimeError("Products without review targets entered supervised splits")

    payload = {
        "status": "complete",
        "stage": 4,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "seed": seed,
        "unit": "deduplicated_product_family",
        "ratios": {"train": 0.70, "development": 0.15, "test": 0.15},
        "splits": split,
        "inference_only_without_review_target": sorted(inference_only),
        "counts": {key: len(value) for key, value in split.items()},
        "category_counts": category_counts,
        "leakage_checks": {
            "cross_split_product_family_overlap": 0,
            "inference_only_in_supervised_split": 0,
        },
    }
    path = output_root / "coldstart_split.json"
    save_json(path, payload)
    manifest = {
        **{key: value for key, value in payload.items() if key != "splits"},
        "output": str(path.resolve()),
        "output_sha256": sha256_file(path),
    }
    save_json(output_root / "stage4_manifest.json", manifest)
    return manifest


def _training_matrices(output_root: Path) -> tuple[Any, Any, list[str], list[str]]:
    import numpy as np

    products = json.loads((output_root / "product_master.json").read_text(encoding="utf-8"))
    with np.load(output_root / "fashionclip_image_embeddings.npz", allow_pickle=False) as arrays:
        image_asins = [str(value) for value in arrays["asins"]]
        image_matrix = np.asarray(arrays["image"], dtype=np.float32)
    image_by_asin = dict(zip(image_asins, image_matrix))
    store = TactileStore()
    product_ids, categories, image_rows, target_rows = [], [], [], []
    for row in products:
        alias_targets = [
            store.vector(str(alias))
            for alias in row["alias_product_ids"]
            if store.vector(str(alias)) is not None
        ]
        if not alias_targets:
            continue
        target = np.stack(alias_targets).mean(axis=0)
        target /= max(float(np.linalg.norm(target)), 1e-12)
        product_id = str(row["product_id"])
        product_ids.append(product_id)
        categories.append(str(row["category"]))
        image_rows.append(image_by_asin[product_id])
        target_rows.append(target)
    return (
        np.asarray(image_rows, dtype=np.float32),
        np.asarray(target_rows, dtype=np.float32),
        product_ids,
        categories,
    )


def train_image_to_tactile(
    output_root: Path = DEFAULT_OUTPUT_ROOT, seed: int = 20260813
) -> dict[str, Any]:
    import joblib
    import numpy as np
    import torch
    from sklearn.linear_model import Ridge
    from sklearn.preprocessing import OneHotEncoder, StandardScaler
    from torch.utils.data import DataLoader, TensorDataset

    from material_span.multimodal_models import TactileMLP

    output_root = Path(output_root)
    split_payload = json.loads((output_root / "coldstart_split.json").read_text(encoding="utf-8"))
    x_image, y, product_ids, categories = _training_matrices(output_root)
    index = {product_id: i for i, product_id in enumerate(product_ids)}
    split_indices = {
        name: np.asarray([index[value] for value in values], dtype=np.int64)
        for name, values in split_payload["splits"].items()
    }
    train_idx = split_indices["train"]
    development_idx = split_indices["development"]
    encoder = OneHotEncoder(handle_unknown="ignore", sparse_output=False, dtype=np.float32)
    train_category = encoder.fit_transform(np.asarray(categories, dtype=object)[train_idx, None])
    all_category = encoder.transform(np.asarray(categories, dtype=object)[:, None])
    x = np.concatenate([x_image, all_category], axis=1).astype(np.float32)
    scaler = StandardScaler()
    x_train = scaler.fit_transform(x[train_idx]).astype(np.float32)
    x_development = scaler.transform(x[development_idx]).astype(np.float32)

    def normalized(values: np.ndarray) -> np.ndarray:
        return values / np.clip(np.linalg.norm(values, axis=1, keepdims=True), 1e-12, None)

    ridge_results = []
    best_ridge = None
    for alpha in (0.1, 1.0, 10.0, 100.0, 1000.0):
        model = Ridge(alpha=alpha)
        model.fit(x_train, y[train_idx])
        prediction = normalized(model.predict(x_development).astype(np.float32))
        cosine = np.sum(prediction * y[development_idx], axis=1)
        row = {"alpha": alpha, "development_mean_cosine": float(cosine.mean())}
        ridge_results.append(row)
        if best_ridge is None or row["development_mean_cosine"] > best_ridge[0]:
            best_ridge = (row["development_mean_cosine"], model, alpha)
    assert best_ridge is not None
    ridge_bundle = {
        "model_type": "ridge",
        "model": best_ridge[1],
        "scaler": scaler,
        "category_encoder": encoder,
        "image_dimension": int(x_image.shape[1]),
        "output_dimension": int(y.shape[1]),
        "selected_alpha": best_ridge[2],
    }
    ridge_path = output_root / "image_to_tactile_ridge.joblib"
    joblib.dump(ridge_bundle, ridge_path)

    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    network = TactileMLP(input_dim=x.shape[1]).to(device)
    optimizer = torch.optim.AdamW(network.parameters(), lr=1e-3, weight_decay=1e-4)
    generator = torch.Generator().manual_seed(seed)
    loader = DataLoader(
        TensorDataset(torch.from_numpy(x_train), torch.from_numpy(y[train_idx])),
        batch_size=32,
        shuffle=True,
        generator=generator,
    )
    dev_x = torch.from_numpy(x_development).to(device)
    dev_y = torch.from_numpy(y[development_idx]).to(device)
    best_dev = -1.0
    best_epoch = 0
    best_state = None
    patience = 35
    for epoch in range(1, 401):
        network.train()
        for batch_x, batch_y in loader:
            batch_x, batch_y = batch_x.to(device), batch_y.to(device)
            prediction = network(batch_x)
            loss = (1.0 - torch.sum(prediction * batch_y, dim=1)).mean()
            optimizer.zero_grad(set_to_none=True)
            loss.backward()
            optimizer.step()
        network.eval()
        with torch.inference_mode():
            dev_score = float(torch.sum(network(dev_x) * dev_y, dim=1).mean().item())
        if dev_score > best_dev + 1e-6:
            best_dev = dev_score
            best_epoch = epoch
            best_state = {key: value.detach().cpu().clone() for key, value in network.state_dict().items()}
        elif epoch - best_epoch >= patience:
            break
        if epoch % 25 == 0:
            print(f"MLP epoch={epoch} best_dev_cosine={best_dev:.6f}", flush=True)
    if best_state is None:
        raise RuntimeError("MLP training did not produce a checkpoint")
    mlp_path = output_root / "image_to_tactile_mlp.pt"
    torch.save(
        {
            "model_type": "mlp",
            "state_dict": best_state,
            "input_dim": int(x.shape[1]),
            "hidden_dim": 256,
            "output_dim": int(y.shape[1]),
            "scaler_mean": scaler.mean_.astype(np.float32),
            "scaler_scale": scaler.scale_.astype(np.float32),
            "categories": [str(value) for value in encoder.categories_[0]],
            "best_epoch": best_epoch,
        },
        mlp_path,
    )
    targets_path = output_root / "family_review_targets.npz"
    np.savez_compressed(
        targets_path,
        asins=np.asarray(product_ids),
        categories=np.asarray(categories),
        material=y,
    )
    manifest = {
        "status": "complete",
        "stage": 5,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "seed": seed,
        "train_products": int(len(train_idx)),
        "development_products": int(len(development_idx)),
        "protected_test_used": False,
        "input_dimension": int(x.shape[1]),
        "image_dimension": int(x_image.shape[1]),
        "category_dimension": int(all_category.shape[1]),
        "target_dimension": int(y.shape[1]),
        "ridge_search": ridge_results,
        "ridge_best_development_cosine": float(best_ridge[0]),
        "ridge_selected_alpha": float(best_ridge[2]),
        "mlp_best_development_cosine": best_dev,
        "mlp_best_epoch": best_epoch,
        "outputs": {
            "ridge": str(ridge_path.resolve()),
            "ridge_sha256": sha256_file(ridge_path),
            "mlp": str(mlp_path.resolve()),
            "mlp_sha256": sha256_file(mlp_path),
            "family_targets": str(targets_path.resolve()),
            "family_targets_sha256": sha256_file(targets_path),
        },
    }
    save_json(output_root / "stage5_manifest.json", manifest)
    return manifest


def evaluate_coldstart(output_root: Path = DEFAULT_OUTPUT_ROOT) -> dict[str, Any]:
    import joblib
    import numpy as np
    import torch

    from material_span.multimodal_models import TactileMLP

    output_root = Path(output_root)
    split_payload = json.loads((output_root / "coldstart_split.json").read_text(encoding="utf-8"))
    x_image, y, product_ids, categories = _training_matrices(output_root)
    index = {product_id: i for i, product_id in enumerate(product_ids)}
    split_indices = {
        name: np.asarray([index[value] for value in values], dtype=np.int64)
        for name, values in split_payload["splits"].items()
    }
    train_idx, development_idx, test_idx = (
        split_indices["train"],
        split_indices["development"],
        split_indices["test"],
    )

    def normalize(values: np.ndarray) -> np.ndarray:
        return values / np.clip(np.linalg.norm(values, axis=1, keepdims=True), 1e-12, None)

    ridge_bundle = joblib.load(output_root / "image_to_tactile_ridge.joblib")
    category_column = np.asarray(categories, dtype=object)[:, None]
    one_hot = ridge_bundle["category_encoder"].transform(category_column)
    x = np.concatenate([x_image, one_hot], axis=1).astype(np.float32)
    x_scaled = ridge_bundle["scaler"].transform(x).astype(np.float32)
    ridge_prediction = normalize(ridge_bundle["model"].predict(x_scaled).astype(np.float32))

    checkpoint = torch.load(output_root / "image_to_tactile_mlp.pt", map_location="cpu")
    network = TactileMLP(
        input_dim=int(checkpoint["input_dim"]),
        hidden_dim=int(checkpoint["hidden_dim"]),
        output_dim=int(checkpoint["output_dim"]),
    )
    network.load_state_dict(checkpoint["state_dict"])
    network.eval()
    with torch.inference_mode():
        mlp_prediction = network(torch.from_numpy(x_scaled)).numpy().astype(np.float32)

    global_mean = normalize(y[train_idx].mean(axis=0, keepdims=True))[0]
    category_mean = {}
    category_array = np.asarray(categories)
    for category in sorted(set(categories)):
        members = train_idx[category_array[train_idx] == category]
        if len(members):
            category_mean[category] = normalize(y[members].mean(axis=0, keepdims=True))[0]
    category_prediction = np.stack(
        [category_mean.get(category, global_mean) for category in categories]
    ).astype(np.float32)

    train_mean = y[train_idx].mean(axis=0, keepdims=True)
    centered_target = normalize(y - train_mean)
    centered_predictions = {
        "category_only": normalize(category_prediction - train_mean),
        "ridge": normalize(ridge_prediction - train_mean),
        "mlp": normalize(mlp_prediction - train_mean),
    }

    def prediction_metrics(prediction: np.ndarray, centered: np.ndarray) -> dict[str, float]:
        raw_cosine = np.sum(prediction[test_idx] * y[test_idx], axis=1)
        centered_cosine = np.sum(centered[test_idx] * centered_target[test_idx], axis=1)
        return {
            "mean_cosine": float(raw_cosine.mean()),
            "median_cosine": float(np.median(raw_cosine)),
            "centered_mean_cosine": float(centered_cosine.mean()),
        }

    results = {
        "category_only": prediction_metrics(category_prediction, centered_predictions["category_only"]),
        "ridge": prediction_metrics(ridge_prediction, centered_predictions["ridge"]),
        "mlp": prediction_metrics(mlp_prediction, centered_predictions["mlp"]),
    }
    retrieval_accumulator = {
        name: {"recall_at_5": [], "ndcg_at_5": []}
        for name in ("category_only", "raw_image", "ridge", "mlp")
    }
    for query_index in test_idx:
        candidates = np.asarray(
            [
                i
                for i, category in enumerate(categories)
                if category == categories[query_index] and i != query_index
            ],
            dtype=np.int64,
        )
        if not len(candidates):
            continue
        oracle_scores = centered_target[candidates] @ centered_target[query_index]
        k = min(5, len(candidates))
        oracle_order = np.argsort(-oracle_scores, kind="stable")[:k]
        oracle_set = set(oracle_order.tolist())
        relevance = np.clip((oracle_scores + 1.0) / 2.0, 0.0, 1.0)
        ideal_dcg = sum(
            relevance[position] / np.log2(rank + 2.0)
            for rank, position in enumerate(oracle_order)
        )
        method_scores = {
            "category_only": centered_target[candidates] @ centered_predictions["category_only"][query_index],
            "raw_image": x_image[candidates] @ x_image[query_index],
            "ridge": centered_target[candidates] @ centered_predictions["ridge"][query_index],
            "mlp": centered_target[candidates] @ centered_predictions["mlp"][query_index],
        }
        for name, scores in method_scores.items():
            order = np.argsort(-scores, kind="stable")[:k]
            retrieval_accumulator[name]["recall_at_5"].append(
                len(oracle_set & set(order.tolist())) / k
            )
            dcg = sum(
                relevance[position] / np.log2(rank + 2.0)
                for rank, position in enumerate(order)
            )
            retrieval_accumulator[name]["ndcg_at_5"].append(dcg / ideal_dcg if ideal_dcg else 0.0)
    for name, metrics in retrieval_accumulator.items():
        results.setdefault(name, {})["same_category_recall_at_5"] = float(
            np.mean(metrics["recall_at_5"])
        )
        results[name]["same_category_ndcg_at_5"] = float(np.mean(metrics["ndcg_at_5"]))

    dev_category_confidence = {}
    dev_centered_cosine = np.sum(
        centered_predictions["ridge"][development_idx] * centered_target[development_idx], axis=1
    )
    for category in sorted(set(categories)):
        mask = category_array[development_idx] == category
        values = dev_centered_cosine[mask]
        if len(values):
            dev_category_confidence[category] = {
                "samples": int(len(values)),
                "centered_mean_cosine": float(values.mean()),
                "confidence": float(np.clip((values.mean() + 1.0) / 2.0, 0.05, 0.95)),
            }
    ridge_improves_retrieval = (
        results["ridge"]["same_category_recall_at_5"]
        >= max(
            results["category_only"]["same_category_recall_at_5"],
            results["raw_image"]["same_category_recall_at_5"],
        )
        and results["ridge"]["same_category_ndcg_at_5"]
        >= max(
            results["category_only"]["same_category_ndcg_at_5"],
            results["raw_image"]["same_category_ndcg_at_5"],
        )
    )
    report = {
        "status": "complete",
        "stage": 6,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "protocol": "product-family cold-start; test reviews hidden from training and model selection",
        "test_products": int(len(test_idx)),
        "selection_rule": "highest development mean cosine",
        "selected_model": "ridge",
        "selected_alpha": float(ridge_bundle["selected_alpha"]),
        "results": results,
        "ridge_improves_over_category_and_raw_image_retrieval": ridge_improves_retrieval,
        "deployment_mode": (
            "image_predicted_tactile_enabled_with_explicit_confidence"
            if ridge_improves_retrieval
            else "image_prediction_available_but_low_confidence_fallback_only"
        ),
        "development_category_confidence": dev_category_confidence,
        "limitations": [
            "Only 461 deduplicated product families have review targets.",
            "The review targets aggregate all selected reviews and are not time-aware.",
            "BGE targets have a strong shared mean direction, so centered metrics are reported.",
        ],
    }
    path = output_root / "coldstart_evaluation.json"
    save_json(path, report)
    manifest = {
        **report,
        "output": str(path.resolve()),
        "output_sha256": sha256_file(path),
    }
    save_json(output_root / "stage6_manifest.json", manifest)
    return manifest


def build_hybrid_targets(output_root: Path = DEFAULT_OUTPUT_ROOT) -> dict[str, Any]:
    import joblib
    import numpy as np

    output_root = Path(output_root)
    products = json.loads((output_root / "product_master.json").read_text(encoding="utf-8"))
    with np.load(output_root / "fashionclip_image_embeddings.npz", allow_pickle=False) as arrays:
        image_asins = [str(value) for value in arrays["asins"]]
        image_matrix = np.asarray(arrays["image"], dtype=np.float32)
    image_by_asin = dict(zip(image_asins, image_matrix))
    with np.load(output_root / "family_review_targets.npz", allow_pickle=False) as arrays:
        review_asins = [str(value) for value in arrays["asins"]]
        review_matrix = np.asarray(arrays["material"], dtype=np.float32)
    review_by_asin = dict(zip(review_asins, review_matrix))
    evaluation = json.loads((output_root / "coldstart_evaluation.json").read_text(encoding="utf-8"))
    category_confidence = {
        key: float(value["confidence"])
        for key, value in evaluation["development_category_confidence"].items()
    }
    ridge_bundle = joblib.load(output_root / "image_to_tactile_ridge.joblib")
    categories = [str(row["category"]) for row in products]
    one_hot = ridge_bundle["category_encoder"].transform(
        np.asarray(categories, dtype=object)[:, None]
    )
    combined_input = np.concatenate(
        [np.stack([image_by_asin[str(row["product_id"])] for row in products]), one_hot],
        axis=1,
    ).astype(np.float32)
    scaled = ridge_bundle["scaler"].transform(combined_input).astype(np.float32)
    predicted = ridge_bundle["model"].predict(scaled).astype(np.float32)
    predicted /= np.clip(np.linalg.norm(predicted, axis=1, keepdims=True), 1e-12, None)

    store = TactileStore()
    max_review_weight = float(store.config["hybrid_target"]["max_review_weight"])
    default_image_confidence = float(
        store.config["hybrid_target"]["default_image_confidence"]
    )
    hybrid_rows, review_weights, image_confidences, final_confidences = [], [], [], []
    target_sources, enriched = [], []
    for index, row in enumerate(products):
        product_id = str(row["product_id"])
        evidence_strength = max(
            store._profile_cache[str(alias)].evidence_strength
            for alias in row["alias_product_ids"]
        )
        review = review_by_asin.get(product_id)
        image_confidence = category_confidence.get(row["category"], default_image_confidence)
        if review is None:
            review_weight = 0.0
            hybrid = predicted[index]
            source = "image_predicted"
        else:
            review_weight = min(max_review_weight, max_review_weight * evidence_strength)
            hybrid = review_weight * review + (1.0 - review_weight) * predicted[index]
            hybrid /= max(float(np.linalg.norm(hybrid)), 1e-12)
            source = "review_image_blended"
        final_confidence = (
            review_weight * evidence_strength + (1.0 - review_weight) * image_confidence
        )
        hybrid_rows.append(hybrid)
        review_weights.append(review_weight)
        image_confidences.append(image_confidence)
        final_confidences.append(final_confidence)
        target_sources.append(source)
        enriched.append(
            {
                **row,
                "tactile_target_source": source,
                "review_weight": review_weight,
                "image_weight": 1.0 - review_weight,
                "image_prediction_confidence": image_confidence,
                "tactile_target_confidence": final_confidence,
            }
        )
    hybrid_matrix = np.asarray(hybrid_rows, dtype=np.float32)
    if not np.allclose(np.linalg.norm(hybrid_matrix, axis=1), 1.0, atol=1e-5):
        raise RuntimeError("Hybrid tactile targets are not L2 normalized")
    vectors_path = output_root / "hybrid_tactile_targets.npz"
    np.savez_compressed(
        vectors_path,
        asins=np.asarray([row["product_id"] for row in products]),
        image_predicted=predicted,
        hybrid=hybrid_matrix,
        review_weight=np.asarray(review_weights, dtype=np.float32),
        image_confidence=np.asarray(image_confidences, dtype=np.float32),
        confidence=np.asarray(final_confidences, dtype=np.float32),
        target_source=np.asarray(target_sources),
    )
    products_path = output_root / "multimodal_products.json"
    save_json(products_path, enriched)
    source_counts = dict(Counter(target_sources))
    manifest = {
        "status": "complete",
        "stage": 7,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "products": len(products),
        "dimension": int(hybrid_matrix.shape[1]),
        "selected_model": evaluation["selected_model"],
        "target_source_counts": source_counts,
        "mean_review_weight": float(np.mean(review_weights)),
        "mean_image_weight": float(1.0 - np.mean(review_weights)),
        "mean_final_confidence": float(np.mean(final_confidences)),
        "outputs": {
            "vectors": str(vectors_path.resolve()),
            "vectors_sha256": sha256_file(vectors_path),
            "products": str(products_path.resolve()),
            "products_sha256": sha256_file(products_path),
        },
    }
    save_json(output_root / "stage7_manifest.json", manifest)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Build versioned multimodal product artifacts")
    parser.add_argument(
        "command",
        choices=[
            "product-master",
            "image-embeddings",
            "evaluate-design",
            "coldstart-split",
            "train-tactile",
            "evaluate-coldstart",
            "hybrid-targets",
        ],
    )
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--image-root", type=Path, default=DEFAULT_IMAGE_ROOT)
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--seed", type=int, default=20260813)
    args = parser.parse_args()
    if args.command == "product-master":
        result = build_product_master(args.output_root, args.image_root)
    elif args.command == "image-embeddings":
        result = extract_image_embeddings(args.output_root, args.image_root, args.batch_size)
    elif args.command == "evaluate-design":
        result = evaluate_design_retrieval(args.output_root)
    elif args.command == "coldstart-split":
        result = build_coldstart_split(args.output_root, args.seed)
    elif args.command == "train-tactile":
        result = train_image_to_tactile(args.output_root, args.seed)
    elif args.command == "evaluate-coldstart":
        result = evaluate_coldstart(args.output_root)
    else:
        result = build_hybrid_targets(args.output_root)
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
