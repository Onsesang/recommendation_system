from __future__ import annotations

import itertools
import math
from collections import defaultdict
from pathlib import Path
from typing import Any

import joblib
import numpy as np
from scipy.stats import spearmanr
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from .common import PATHS, load_experiment, read_json, sha256_file, utc_now, write_json


def _safe_spearman(y_true: np.ndarray, y_pred: np.ndarray) -> float | None:
    if len(y_true) < 3 or np.std(y_true) <= 1e-12 or np.std(y_pred) <= 1e-12:
        return None
    value = float(spearmanr(y_true, y_pred).statistic)
    return value if math.isfinite(value) else None


def _metrics(
    y_true: np.ndarray,
    y_pred: np.ndarray,
    categories: np.ndarray | None = None,
) -> dict[str, Any]:
    if not len(y_true):
        return {"samples": 0, "spearman": None, "mae": None, "direction_accuracy": None, "pairwise_accuracy": None, "same_category_pairwise_accuracy": None}
    true_direction = np.sign(y_true)
    valid_direction = true_direction != 0
    direction = float(np.mean(np.sign(y_pred[valid_direction]) == true_direction[valid_direction])) if valid_direction.any() else None
    correct, total, same_correct, same_total = 0, 0, 0, 0
    for left, right in itertools.combinations(range(len(y_true)), 2):
        true_delta = y_true[left] - y_true[right]
        if abs(true_delta) < 0.5:
            continue
        predicted_delta = y_pred[left] - y_pred[right]
        correct += int(np.sign(predicted_delta) == np.sign(true_delta))
        total += 1
        if categories is not None and categories[left] == categories[right]:
            same_correct += int(np.sign(predicted_delta) == np.sign(true_delta))
            same_total += 1
    return {
        "samples": int(len(y_true)),
        "spearman": _safe_spearman(y_true, y_pred),
        "mae": float(np.mean(np.abs(y_true - y_pred))),
        "direction_accuracy": direction,
        "pairwise_accuracy": correct / total if total else None,
        "same_category_pairwise_accuracy": same_correct / same_total if same_total else None,
        "same_category_pairs": same_total,
    }


def _load_matrices() -> dict[str, Any]:
    config = load_experiment()
    with np.load(PATHS.artifacts / "product_axis_targets.npz", allow_pickle=False) as arrays:
        product_ids = np.asarray(arrays["product_ids"]).astype(str)
        axis_ids = np.asarray(arrays["axis_ids"]).astype(str)
        values = np.asarray(arrays["values"], dtype=np.float32)
        mask = np.asarray(arrays["mask"], dtype=bool)
        support = np.asarray(arrays["support"], dtype=np.float32)
        agreement = np.asarray(arrays["agreement"], dtype=np.float32)
    with np.load(Path(config["inputs"]["fashionclip_embeddings"]), allow_pickle=False) as arrays:
        image_ids = np.asarray(arrays["asins"]).astype(str)
        image_values = np.asarray(arrays["image"], dtype=np.float32)
    image_lookup = {value: index for index, value in enumerate(image_ids)}
    if any(value not in image_lookup for value in product_ids):
        raise RuntimeError("FashionCLIP embeddings do not cover product targets")
    image = np.stack([image_values[image_lookup[value]] for value in product_ids])
    products = read_json(Path(config["inputs"]["product_master"]))
    metadata = {str(row["product_id"]): row for row in products}
    categories = np.asarray([str(metadata[value]["category"]) for value in product_ids])
    return {
        "config": config, "product_ids": product_ids, "axis_ids": axis_ids,
        "values": values, "mask": mask, "support": support,
        "agreement": agreement, "image": image, "categories": categories,
    }


def _weights(name: str, support: np.ndarray, agreement: np.ndarray) -> np.ndarray:
    if name == "W0":
        values = np.ones_like(support, dtype=float)
    elif name == "W1":
        values = np.log1p(support)
    elif name == "W2":
        values = np.clip(agreement, 0.05, 1.0)
    elif name == "W3":
        values = np.log1p(support) * np.clip(agreement, 0.05, 1.0)
    else:
        raise ValueError(name)
    return values / max(float(np.mean(values)), 1e-12)


def _ridge_axis(
    x: np.ndarray,
    y: np.ndarray,
    observed: np.ndarray,
    train: np.ndarray,
    development: np.ndarray,
    alphas: list[float],
    sample_weight: np.ndarray,
) -> tuple[np.ndarray, dict[str, Any], dict[str, Any]]:
    train_obs = train[observed[train]]
    development_obs = development[observed[development]]
    if len(train_obs) < 3:
        constant = float(np.mean(y[train_obs])) if len(train_obs) else 0.0
        return np.full(len(y), constant, dtype=np.float32), {"type": "constant", "value": constant}, {"alpha": None, "development_spearman": None}
    scaler = StandardScaler().fit(x[train_obs])
    scaled = scaler.transform(x)
    best = None
    search = []
    for alpha in alphas:
        model = Ridge(alpha=float(alpha)).fit(
            scaled[train_obs], y[train_obs], sample_weight=sample_weight[train_obs]
        )
        prediction = model.predict(scaled).astype(np.float32)
        score = _safe_spearman(y[development_obs], prediction[development_obs])
        search.append({"alpha": float(alpha), "development_spearman": score})
        comparison = -float("inf") if score is None else score
        if best is None or comparison > best[0]:
            best = (comparison, model, prediction, float(alpha))
    assert best is not None
    bundle = {"type": "ridge", "model": best[1], "scaler": scaler}
    return best[2], bundle, {"alpha": best[3], "development_spearman": None if best[0] == -float("inf") else best[0], "search": search}


def _ordinal_axis(
    x: np.ndarray,
    y: np.ndarray,
    observed: np.ndarray,
    train: np.ndarray,
    bins: np.ndarray,
) -> tuple[np.ndarray, dict[str, Any]]:
    train_obs = train[observed[train]]
    labels = np.asarray([int(np.argmin(np.abs(bins - value))) for value in y[train_obs]])
    if len(train_obs) < 5 or len(np.unique(labels)) < 2:
        constant = float(np.mean(y[train_obs])) if len(train_obs) else 0.0
        return np.full(len(y), constant, dtype=np.float32), {"type": "constant", "value": constant}
    scaler = StandardScaler().fit(x[train_obs])
    scaled = scaler.transform(x)
    model = LogisticRegression(max_iter=2000, C=1.0).fit(scaled[train_obs], labels)
    probabilities = model.predict_proba(scaled)
    class_values = bins[model.classes_.astype(int)]
    prediction = probabilities @ class_values
    return prediction.astype(np.float32), {"type": "ordinal_logistic", "model": model, "scaler": scaler}


def _pairwise_axis(
    x: np.ndarray,
    y: np.ndarray,
    observed: np.ndarray,
    train: np.ndarray,
    margin: float,
) -> tuple[np.ndarray, dict[str, Any]]:
    train_obs = train[observed[train]]
    differences, labels = [], []
    for left, right in itertools.combinations(train_obs.tolist(), 2):
        delta = float(y[left] - y[right])
        if abs(delta) < margin:
            continue
        vector = x[left] - x[right]
        label = int(delta > 0)
        differences.extend([vector, -vector])
        labels.extend([label, 1 - label])
    if len(differences) < 10:
        constant = float(np.mean(y[train_obs])) if len(train_obs) else 0.0
        return np.full(len(y), constant, dtype=np.float32), {"type": "constant", "value": constant, "pairs": len(differences) // 2}
    scaler = StandardScaler().fit(x[train_obs])
    scaled_differences = np.asarray(differences) / np.clip(scaler.scale_, 1e-12, None)
    model = LogisticRegression(max_iter=2000, C=1.0).fit(scaled_differences, labels)
    prediction = scaler.transform(x) @ model.coef_[0]
    prediction = (prediction - np.mean(prediction[train_obs])) / max(float(np.std(prediction[train_obs])), 1e-12)
    target_std = float(np.std(y[train_obs]))
    prediction = prediction * target_std + float(np.mean(y[train_obs]))
    return prediction.astype(np.float32), {"type": "pairwise_logistic", "model": model, "scaler": scaler, "pairs": len(differences) // 2}


def _tiny_mlp(
    x: np.ndarray,
    y: np.ndarray,
    mask: np.ndarray,
    train: np.ndarray,
    development: np.ndarray,
    config: dict[str, Any],
    seed: int,
) -> tuple[np.ndarray, dict[str, Any]]:
    import torch
    from torch import nn

    torch.manual_seed(seed)
    scaler = StandardScaler().fit(x[train])
    scaled = scaler.transform(x).astype(np.float32)
    values = np.nan_to_num(y, nan=0.0).astype(np.float32)
    network = nn.Sequential(
        nn.Linear(scaled.shape[1], int(config["mlp_hidden_dim"])),
        nn.GELU(), nn.Dropout(0.15), nn.Linear(int(config["mlp_hidden_dim"]), y.shape[1]),
    )
    optimizer = torch.optim.AdamW(
        network.parameters(), lr=float(config["mlp_learning_rate"]), weight_decay=1e-4
    )
    train_x = torch.from_numpy(scaled[train])
    train_y = torch.from_numpy(values[train])
    train_mask = torch.from_numpy(mask[train].astype(np.float32))
    best_loss, best_epoch, best_state = float("inf"), 0, None
    patience = int(config["mlp_patience"])
    for epoch in range(1, int(config["mlp_epochs"]) + 1):
        network.train()
        prediction = network(train_x)
        element = torch.nn.functional.huber_loss(prediction, train_y, reduction="none")
        loss = (element * train_mask).sum() / train_mask.sum().clamp_min(1.0)
        optimizer.zero_grad(set_to_none=True)
        loss.backward()
        optimizer.step()
        network.eval()
        with torch.inference_mode():
            dev_prediction = network(torch.from_numpy(scaled[development]))
            dev_values = torch.from_numpy(values[development])
            dev_mask = torch.from_numpy(mask[development].astype(np.float32))
            dev_element = torch.nn.functional.huber_loss(dev_prediction, dev_values, reduction="none")
            dev_loss = float(((dev_element * dev_mask).sum() / dev_mask.sum().clamp_min(1.0)).item())
        if dev_loss < best_loss - 1e-7:
            best_loss, best_epoch = dev_loss, epoch
            best_state = {key: value.detach().clone() for key, value in network.state_dict().items()}
        elif epoch - best_epoch >= patience:
            break
    if best_state is not None:
        network.load_state_dict(best_state)
    network.eval()
    with torch.inference_mode():
        prediction = network(torch.from_numpy(scaled)).numpy().astype(np.float32)
    return prediction, {"best_epoch": best_epoch, "development_masked_huber": best_loss, "seed": seed}


def run_model_experiments() -> dict[str, Any]:
    data = _load_matrices()
    config = data["config"]
    axis_ids = data["axis_ids"]
    if not len(axis_ids):
        manifest = {"status": "gate_failed_no_active_axes", "phase": "6-7", "generated_at": utc_now()}
        write_json(PATHS.manifests / "phase6_7_models.json", manifest)
        return manifest
    product_index = {value: index for index, value in enumerate(data["product_ids"])}
    category_encoder = OneHotEncoder(handle_unknown="ignore", sparse_output=False, dtype=np.float32)
    category_onehot = category_encoder.fit_transform(data["categories"][:, None])
    dino_status: dict[str, Any]
    try:
        from .visual_features import extract_dino_embeddings
        dino_status = extract_dino_embeddings()
    except Exception as exc:
        dino_status = {"status": "unavailable", "error": f"{type(exc).__name__}: {exc}"}
    x_variants = {
        "fashionclip_ridge": data["image"],
        "image_category_ridge": np.concatenate([data["image"], category_onehot], axis=1),
    }
    dino_path = PATHS.artifacts / "dino_image_embeddings.npz"
    if dino_path.is_file():
        with np.load(dino_path, allow_pickle=False) as arrays:
            dino_ids = np.asarray(arrays["product_ids"]).astype(str)
            dino_values = np.asarray(arrays["image"], dtype=np.float32)
        if np.array_equal(dino_ids, data["product_ids"]):
            x_variants["dino_ridge"] = dino_values
    all_seed_results = []
    primary_predictions: dict[str, np.ndarray] = {}
    model_bundles = {}
    for seed in config["experiment"]["split_seeds"]:
        split = read_json(PATHS.manifests / f"family_split_{seed}.json")["splits"]
        indices = {
            name: np.asarray([product_index[value] for value in values], dtype=int)
            for name, values in split.items()
        }
        seed_results = {"seed": int(seed), "axes": {}, "objective_robustness": {}}
        for axis_number, axis_id in enumerate(axis_ids):
            y = data["values"][:, axis_number]
            observed = data["mask"][:, axis_number]
            test_obs = indices["test"][observed[indices["test"]]]
            axis_result: dict[str, Any] = {}
            candidate_predictions = {}
            train_obs = indices["train"][observed[indices["train"]]]
            category_means = {}
            for category in np.unique(data["categories"]):
                members = train_obs[data["categories"][train_obs] == category]
                if len(members):
                    category_means[category] = float(np.mean(y[members]))
            global_mean = float(np.mean(y[train_obs])) if len(train_obs) else 0.0
            category_prediction = np.asarray([category_means.get(value, global_mean) for value in data["categories"]], dtype=np.float32)
            candidate_predictions["category_only"] = category_prediction
            axis_result["category_only"] = _metrics(y[test_obs], category_prediction[test_obs], data["categories"][test_obs])
            for model_name, x in x_variants.items():
                weight = _weights("W0", data["support"][:, axis_number], np.nan_to_num(data["agreement"][:, axis_number], nan=0.05))
                prediction, bundle, selection = _ridge_axis(
                    x, y, observed, indices["train"], indices["development"],
                    [float(value) for value in config["models"]["ridge_alphas"]], weight,
                )
                candidate_predictions[model_name] = prediction
                axis_result[model_name] = {**_metrics(y[test_obs], prediction[test_obs], data["categories"][test_obs]), "selection": selection}
                if int(seed) == int(config["experiment"]["seed"]):
                    model_bundles[f"{axis_id}:{model_name}"] = bundle
            linear_prediction, linear_bundle, linear_selection = _ridge_axis(
                data["image"], y, observed, indices["train"], indices["development"],
                [0.0], np.ones(len(y), dtype=float),
            )
            candidate_predictions["fashionclip_linear"] = linear_prediction
            axis_result["fashionclip_linear"] = {
                **_metrics(y[test_obs], linear_prediction[test_obs], data["categories"][test_obs]),
                "selection": linear_selection,
            }
            if int(seed) == int(config["experiment"]["seed"]):
                model_bundles[f"{axis_id}:fashionclip_linear"] = linear_bundle
            ordinal_prediction, ordinal_bundle = _ordinal_axis(
                data["image"], y, observed, indices["train"],
                np.asarray(config["targets"]["score_bins"], dtype=float),
            )
            pairwise_observed = (
                observed
                & (data["support"][:, axis_number] >= int(config["models"]["pairwise_min_support"]))
                & (np.nan_to_num(data["agreement"][:, axis_number], nan=0.0) >= float(config["models"]["pairwise_min_agreement"]))
            )
            pairwise_prediction, pairwise_bundle = _pairwise_axis(
                data["image"], y, pairwise_observed, indices["train"], float(config["models"]["pairwise_margin"])
            )
            candidate_predictions["ordinal"] = ordinal_prediction
            candidate_predictions["pairwise"] = pairwise_prediction
            axis_result["ordinal"] = _metrics(y[test_obs], ordinal_prediction[test_obs], data["categories"][test_obs])
            axis_result["pairwise"] = {**_metrics(y[test_obs], pairwise_prediction[test_obs], data["categories"][test_obs]), "training_pairs": pairwise_bundle.get("pairs")}

            robustness = {}
            for weight_name in ("W0", "W1", "W2", "W3"):
                sample_weight = _weights(weight_name, data["support"][:, axis_number], np.nan_to_num(data["agreement"][:, axis_number], nan=0.05))
                prediction, _, selection = _ridge_axis(
                    data["image"], y, observed, indices["train"], indices["development"],
                    [float(value) for value in config["models"]["ridge_alphas"]], sample_weight,
                )
                robustness[f"masked_regression_{weight_name}"] = {**_metrics(y[test_obs], prediction[test_obs], data["categories"][test_obs]), "selection": selection}
            subsets = {
                "high_support": observed & (data["support"][:, axis_number] >= 2),
                "extreme_only": observed & (np.abs(y) >= 1.5),
                "moderate_only": observed & (np.abs(y) < 1.5),
            }
            for subset_name, subset_mask in subsets.items():
                prediction, _, _ = _ridge_axis(
                    data["image"], y, subset_mask, indices["train"], indices["development"],
                    [float(value) for value in config["models"]["ridge_alphas"]], np.ones(len(y)),
                )
                robustness[subset_name] = _metrics(y[test_obs], prediction[test_obs], data["categories"][test_obs])
            seed_results["axes"][axis_id] = axis_result
            seed_results["objective_robustness"][axis_id] = robustness
            if int(seed) == int(config["experiment"]["seed"]):
                development_obs = indices["development"][observed[indices["development"]]]
                ranked = []
                for name, prediction in candidate_predictions.items():
                    score = _safe_spearman(y[development_obs], prediction[development_obs])
                    ranked.append((-float("inf") if score is None else score, name, prediction))
                ranked.sort(key=lambda value: (value[0], value[1]), reverse=True)
                primary_predictions[axis_id] = ranked[0][2]
                axis_result["selected_by_development"] = {"method": ranked[0][1], "spearman": None if ranked[0][0] == -float("inf") else ranked[0][0]}
        mlp_prediction, mlp_info = _tiny_mlp(
            data["image"], data["values"], data["mask"], indices["train"],
            indices["development"], config["models"], int(seed),
        )
        for axis_number, axis_id in enumerate(axis_ids):
            test_obs = indices["test"][data["mask"][indices["test"], axis_number]]
            seed_results["axes"][axis_id]["tiny_mlp"] = _metrics(
                data["values"][test_obs, axis_number], mlp_prediction[test_obs, axis_number], data["categories"][test_obs]
            )
        seed_results["tiny_mlp_training"] = mlp_info
        all_seed_results.append(seed_results)

    prediction_matrix = np.stack([primary_predictions[axis_id] for axis_id in axis_ids], axis=1).astype(np.float32)
    prediction_path = PATHS.artifacts / "structured_image_predictions.npz"
    np.savez_compressed(
        prediction_path, product_ids=data["product_ids"], axis_ids=axis_ids,
        prediction=prediction_matrix, target=data["values"], mask=data["mask"],
    )
    model_path = PATHS.artifacts / "structured_model_bundles.joblib"
    joblib.dump(model_bundles, model_path)
    open_baseline = _run_open_vector_baseline(data)
    summary = _summarize(all_seed_results, axis_ids)
    result_path = PATHS.artifacts / "phase6_7_model_results.json"
    result = {
        "status": "complete",
        "phase": "6-7",
        "generated_at": utc_now(),
        "axes": axis_ids.tolist(),
        "seeds": [int(value) for value in config["experiment"]["split_seeds"]],
        "per_seed": all_seed_results,
        "summary": summary,
        "open_384d_baseline": open_baseline,
        "dino_baseline": dino_status,
        "vlm_zero_shot": _evaluate_cached_vlm(data),
        "limitations": [
            "All Amazon labels are review-derived Qwen pseudo-targets.",
            "Current family splits are feasibility splits, not a never-seen final Amazon test.",
        ],
    }
    write_json(result_path, result)
    manifest = {
        "status": "complete", "phase": "6-7", "generated_at": utc_now(),
        "axes": axis_ids.tolist(), "summary": summary,
        "outputs": {
            "results": str(result_path), "results_sha256": sha256_file(result_path),
            "predictions": str(prediction_path), "predictions_sha256": sha256_file(prediction_path),
            "models": str(model_path), "models_sha256": sha256_file(model_path),
        },
    }
    write_json(PATHS.manifests / "phase6_7_models.json", manifest)
    _write_model_report(result)
    return manifest


def _evaluate_cached_vlm(data: dict[str, Any]) -> dict[str, Any]:
    path = PATHS.artifacts / "qwen_vlm_zero_shot.npz"
    if not path.is_file():
        return {"status": "unavailable_not_executed"}
    with np.load(path, allow_pickle=False) as arrays:
        ids = np.asarray(arrays["product_ids"]).astype(str)
        axes = np.asarray(arrays["axis_ids"]).astype(str)
        prediction = np.asarray(arrays["prediction"], dtype=np.float32)
        visual_mask = np.asarray(arrays["visual_mask"], dtype=bool)
    if not np.array_equal(ids, data["product_ids"]) or not np.array_equal(axes, data["axis_ids"]):
        return {"status": "unavailable_alignment_mismatch"}
    config = data["config"]
    split = read_json(PATHS.manifests / f"family_split_{config['experiment']['seed']}.json")["splits"]
    lookup = {value: index for index, value in enumerate(data["product_ids"])}
    test = np.asarray([lookup[value] for value in split["test"]], dtype=int)
    results = {}
    for axis_number, axis_id in enumerate(data["axis_ids"]):
        eligible = test[
            data["mask"][test, axis_number] & visual_mask[test, axis_number]
        ]
        results[str(axis_id)] = _metrics(
            data["values"][eligible, axis_number], prediction[eligible, axis_number],
            data["categories"][eligible],
        )
    return {"status": "complete", "results": results}


def _run_open_vector_baseline(data: dict[str, Any]) -> dict[str, Any]:
    path = Path(data["config"]["inputs"]["open_review_targets"])
    if not path.is_file():
        return {"status": "unavailable"}
    with np.load(path, allow_pickle=False) as arrays:
        ids = np.asarray(arrays["asins"]).astype(str)
        target = np.asarray(arrays["material"], dtype=np.float32)
    lookup = {value: index for index, value in enumerate(ids)}
    members = np.asarray([i for i, value in enumerate(data["product_ids"]) if value in lookup], dtype=int)
    if not len(members):
        return {"status": "unavailable_no_alignment"}
    split = read_json(PATHS.manifests / f"family_split_{data['config']['experiment']['seed']}.json")["splits"]
    product_index = {value: index for index, value in enumerate(data["product_ids"])}
    train = np.asarray([product_index[value] for value in split["train"] if value in lookup], dtype=int)
    test = np.asarray([product_index[value] for value in split["test"] if value in lookup], dtype=int)
    y = np.stack([target[lookup[value]] for value in data["product_ids"] if value in lookup])
    aligned_ids = [value for value in data["product_ids"] if value in lookup]
    aligned_lookup = {value: i for i, value in enumerate(aligned_ids)}
    x = np.stack([data["image"][product_index[value]] for value in aligned_ids])
    train_aligned = np.asarray([aligned_lookup[value] for value in split["train"] if value in aligned_lookup], dtype=int)
    test_aligned = np.asarray([aligned_lookup[value] for value in split["test"] if value in aligned_lookup], dtype=int)
    scaler = StandardScaler().fit(x[train_aligned])
    model = Ridge(alpha=1000.0).fit(scaler.transform(x[train_aligned]), y[train_aligned])
    prediction = model.predict(scaler.transform(x)).astype(np.float32)
    prediction /= np.clip(np.linalg.norm(prediction, axis=1, keepdims=True), 1e-12, None)
    prediction_path = PATHS.artifacts / "open_384d_predictions.npz"
    np.savez_compressed(
        prediction_path,
        product_ids=np.asarray(aligned_ids),
        prediction=prediction,
        target=y,
    )
    train_mean = y[train_aligned].mean(axis=0, keepdims=True)
    centered_y = y - train_mean
    centered_p = prediction - train_mean
    centered_y /= np.clip(np.linalg.norm(centered_y, axis=1, keepdims=True), 1e-12, None)
    centered_p /= np.clip(np.linalg.norm(centered_p, axis=1, keepdims=True), 1e-12, None)
    return {
        "status": "complete", "dimension": int(y.shape[1]), "test_products": int(len(test_aligned)),
        "mean_cosine": float(np.mean(np.sum(prediction[test_aligned] * y[test_aligned], axis=1))),
        "centered_mean_cosine": float(np.mean(np.sum(centered_p[test_aligned] * centered_y[test_aligned], axis=1))),
        "predictions": str(prediction_path),
        "predictions_sha256": sha256_file(prediction_path),
    }


def _summarize(results: list[dict[str, Any]], axis_ids: np.ndarray) -> dict[str, Any]:
    output = {}
    for axis_id in axis_ids:
        methods = set.intersection(*(set(row["axes"][axis_id]) for row in results))
        output[axis_id] = {}
        for method in sorted(methods):
            if not isinstance(results[0]["axes"][axis_id][method], dict) or "spearman" not in results[0]["axes"][axis_id][method]:
                continue
            values = [row["axes"][axis_id][method].get("spearman") for row in results]
            valid = [float(value) for value in values if value is not None]
            output[axis_id][method] = {
                "spearman_mean": float(np.mean(valid)) if valid else None,
                "spearman_std": float(np.std(valid)) if valid else None,
            }
    return output


def _write_model_report(result: dict[str, Any]) -> None:
    lines = ["# Phase 6–7 — Image Prediction and Objective Robustness", ""]
    for axis, methods in result["summary"].items():
        lines.extend([f"## {axis}", "", "| Method | Spearman mean | std |", "|---|---:|---:|"])
        for method, values in methods.items():
            mean = "—" if values["spearman_mean"] is None else f"{values['spearman_mean']:.3f}"
            std = "—" if values["spearman_std"] is None else f"{values['spearman_std']:.3f}"
            lines.append(f"| {method} | {mean} | {std} |")
        lines.append("")
    lines.extend(
        [
            "## Interpretation", "",
            "Category-only and same-category pairwise metrics are mandatory controls. A structured model is not considered visually grounded when it only improves across categories. The 384-dimensional result remains an open-vector baseline and is not physical tactile ground truth.",
        ]
    )
    (PATHS.reports / "phase6_7_image_prediction.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
