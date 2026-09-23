from __future__ import annotations

import math
from typing import Any

import numpy as np
import joblib
from scipy.stats import spearmanr
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.preprocessing import StandardScaler

from .common import PATHS, load_experiment, read_json, sha256_file, utc_now, write_json, write_jsonl
from .modeling import _load_matrices


METHODS = ("confidence_only", "recoverability_only", "product", "learned_calibrator")


def risk_coverage_curve(errors: np.ndarray, scores: np.ndarray) -> dict[str, Any]:
    if len(errors) == 0:
        return {"coverage": [], "risk": [], "aurc": None}
    order = np.argsort(-scores, kind="stable")
    ordered = np.asarray(errors, dtype=float)[order]
    risk = np.cumsum(ordered) / np.arange(1, len(ordered) + 1)
    coverage = np.arange(1, len(ordered) + 1, dtype=float) / len(ordered)
    return {
        "coverage": coverage.tolist(),
        "risk": risk.tolist(),
        "aurc": float(np.trapezoid(risk, coverage)),
    }


def score_threshold(scores: np.ndarray, coverage: float) -> float:
    if not len(scores):
        return float("inf")
    if coverage >= 1.0:
        return float(np.min(scores) - 1e-12)
    count = max(1, int(math.ceil(len(scores) * coverage)))
    return float(np.sort(scores)[-count])


def _fixed_coverage(
    errors: np.ndarray,
    scores: np.ndarray,
    development_scores: np.ndarray,
    coverages: list[float],
) -> dict[str, Any]:
    output = {}
    for coverage in coverages:
        threshold = score_threshold(development_scores, coverage)
        accepted = scores >= threshold
        output[str(coverage)] = {
            "development_threshold": threshold,
            "test_coverage": float(np.mean(accepted)) if len(accepted) else 0.0,
            "test_risk_mae": float(np.mean(errors[accepted])) if accepted.any() else None,
            "test_examples": int(accepted.sum()),
        }
    return output


def _confidence_error_correlation(scores: np.ndarray, errors: np.ndarray) -> float | None:
    if len(scores) < 3 or np.ptp(scores) <= 1e-7 or np.ptp(errors) <= 1e-7:
        return None
    value = float(spearmanr(scores, errors).statistic)
    return value if math.isfinite(value) else None


def _expected_calibration_error(
    scores: np.ndarray,
    errors: np.ndarray,
    tolerance: float,
    bins: int,
) -> float | None:
    if not len(scores):
        return None
    correctness = (errors <= tolerance).astype(float)
    edges = np.linspace(0.0, 1.0, bins + 1)
    total = float(len(scores))
    value = 0.0
    for left, right in zip(edges[:-1], edges[1:]):
        members = (scores >= left) & (scores <= right if right == 1.0 else scores < right)
        if members.any():
            value += members.sum() / total * abs(float(scores[members].mean()) - float(correctness[members].mean()))
    return float(value)


def _fit_bootstrap_ensemble(
    x: np.ndarray,
    y: np.ndarray,
    train_observed: np.ndarray,
    alpha: float,
    members: int,
    seed: int,
) -> tuple[np.ndarray, np.ndarray]:
    if len(train_observed) < 3:
        constant = float(np.mean(y[train_observed])) if len(train_observed) else 0.0
        return np.full(len(y), constant, dtype=np.float32), np.ones(len(y), dtype=np.float32)
    scaler = StandardScaler().fit(x[train_observed])
    scaled = scaler.transform(x)
    rng = np.random.default_rng(seed)
    predictions = []
    for _ in range(members):
        sample = rng.choice(train_observed, size=len(train_observed), replace=True)
        model = Ridge(alpha=alpha).fit(scaled[sample], y[sample])
        predictions.append(model.predict(scaled))
    matrix = np.asarray(predictions, dtype=np.float32)
    return matrix.mean(axis=0), matrix.std(axis=0)


def _generic_calibrator(features: np.ndarray, errors: np.ndarray, tolerance: float) -> dict[str, Any]:
    labels = (errors <= tolerance).astype(int)
    if len(np.unique(labels)) < 2:
        return {"type": "constant", "value": float(labels[0]) if len(labels) else 0.0}
    model = LogisticRegression(max_iter=2000, class_weight="balanced", random_state=0)
    model.fit(features, labels)
    return {"type": "logistic", "model": model}


def _calibrator_prediction(bundle: dict[str, Any], features: np.ndarray) -> np.ndarray:
    if bundle["type"] == "constant":
        return np.full(len(features), float(bundle["value"]), dtype=np.float32)
    return bundle["model"].predict_proba(features)[:, 1].astype(np.float32)


def run_selective_calibration() -> dict[str, Any]:
    config = load_experiment()
    selective = config["selective"]
    data = _load_matrices()
    split = read_json(PATHS.manifests / f"family_split_{config['experiment']['seed']}.json")["splits"]
    product_index = {value: index for index, value in enumerate(data["product_ids"])}
    indices = {
        name: np.asarray([product_index[value] for value in values], dtype=int)
        for name, values in split.items()
    }
    external = read_json(PATHS.artifacts / "external_transfer_results.json")
    recovery_rows = external.get("property_recoverability", {})
    recovery = np.asarray(
        [float(recovery_rows.get(axis, {}).get("value", 0.0)) for axis in data["axis_ids"]],
        dtype=np.float32,
    )
    members = int(selective["ensemble_members"])
    model_bundles = joblib.load(PATHS.artifacts / "structured_model_bundles.joblib")
    mean_prediction = np.zeros_like(data["values"], dtype=np.float32)
    uncertainty = np.zeros_like(data["values"], dtype=np.float32)
    instance_confidence = np.zeros_like(data["values"], dtype=np.float32)
    for axis_number, axis_id in enumerate(data["axis_ids"]):
        observed = data["mask"][:, axis_number]
        train_observed = indices["train"][observed[indices["train"]]]
        fitted = model_bundles.get(f"{axis_id}:fashionclip_ridge", {})
        alpha = float(getattr(fitted.get("model"), "alpha", config["models"]["ridge_alphas"][0]))
        mean, std = _fit_bootstrap_ensemble(
            data["image"], data["values"][:, axis_number], train_observed,
            alpha=alpha, members=members,
            seed=int(config["experiment"]["seed"]) + axis_number,
        )
        development_observed = indices["development"][observed[indices["development"]]]
        scale = float(np.median(std[development_observed])) if len(development_observed) else float(np.median(std))
        scale = max(scale, 1e-6)
        mean_prediction[:, axis_number] = mean
        uncertainty[:, axis_number] = std
        instance_confidence[:, axis_number] = np.exp(-std / scale)

    dev_features, dev_errors, dev_locations = [], [], []
    test_features, test_errors, test_locations = [], [], []
    for subset, feature_rows, errors, locations in (
        ("development", dev_features, dev_errors, dev_locations),
        ("test", test_features, test_errors, test_locations),
    ):
        for product_number in indices[subset]:
            for axis_number in range(len(data["axis_ids"])):
                if not data["mask"][product_number, axis_number]:
                    continue
                confidence = float(instance_confidence[product_number, axis_number])
                recoverability = float(recovery[axis_number])
                feature_rows.append([confidence, recoverability, confidence * recoverability])
                errors.append(abs(float(mean_prediction[product_number, axis_number] - data["values"][product_number, axis_number])))
                locations.append((product_number, axis_number))
    dev_features_array = np.asarray(dev_features, dtype=np.float32).reshape(-1, 3)
    test_features_array = np.asarray(test_features, dtype=np.float32).reshape(-1, 3)
    dev_error_array = np.asarray(dev_errors, dtype=np.float32)
    test_error_array = np.asarray(test_errors, dtype=np.float32)
    tolerance = float(selective["correctness_tolerance"])
    calibrator = _generic_calibrator(dev_features_array, dev_error_array, tolerance)
    dev_scores = {
        "confidence_only": dev_features_array[:, 0],
        "recoverability_only": dev_features_array[:, 1],
        "product": dev_features_array[:, 2],
        "learned_calibrator": _calibrator_prediction(calibrator, dev_features_array),
    }
    test_scores = {
        "confidence_only": test_features_array[:, 0],
        "recoverability_only": test_features_array[:, 1],
        "product": test_features_array[:, 2],
        "learned_calibrator": _calibrator_prediction(calibrator, test_features_array),
    }
    coverages = [float(value) for value in selective["fixed_coverages"]]
    method_results = {}
    for method in METHODS:
        curve = risk_coverage_curve(test_error_array, test_scores[method])
        method_results[method] = {
            "test_examples": int(len(test_error_array)),
            "aurc": curve["aurc"],
            "confidence_error_spearman": _confidence_error_correlation(test_scores[method], test_error_array),
            "expected_calibration_error": _expected_calibration_error(
                np.clip(test_scores[method], 0.0, 1.0), test_error_array, tolerance,
                int(selective["calibration_bins"]),
            ),
            "fixed_coverage": _fixed_coverage(test_error_array, test_scores[method], dev_scores[method], coverages),
            "risk_coverage_curve": curve,
        }

    reliability_matrices = {method: np.zeros_like(data["values"], dtype=np.float32) for method in METHODS}
    for product_number in range(len(data["product_ids"])):
        feature_matrix = np.stack(
            [
                instance_confidence[product_number],
                recovery,
                instance_confidence[product_number] * recovery,
            ],
            axis=1,
        )
        reliability_matrices["confidence_only"][product_number] = feature_matrix[:, 0]
        reliability_matrices["recoverability_only"][product_number] = feature_matrix[:, 1]
        reliability_matrices["product"][product_number] = feature_matrix[:, 2]
        reliability_matrices["learned_calibrator"][product_number] = _calibrator_prediction(calibrator, feature_matrix)
    primary_coverage = float(selective["primary_coverage"])
    thresholds = {method: score_threshold(dev_scores[method], primary_coverage) for method in METHODS}
    decisions = {
        method: (reliability_matrices[method] >= threshold).astype(np.uint8)
        for method, threshold in thresholds.items()
    }
    matrix_path = PATHS.artifacts / "selective_predictions.npz"
    np.savez_compressed(
        matrix_path,
        product_ids=data["product_ids"], axis_ids=data["axis_ids"],
        prediction=mean_prediction, uncertainty=uncertainty,
        instance_confidence=instance_confidence, property_recoverability=recovery,
        **{f"reliability_{key}": value for key, value in reliability_matrices.items()},
        **{f"decision_{key}": value for key, value in decisions.items()},
    )
    records = []
    for product_number, product_id in enumerate(data["product_ids"]):
        for axis_number, axis_id in enumerate(data["axis_ids"]):
            records.append(
                {
                    "product_id": str(product_id), "axis_id": str(axis_id),
                    "prediction": float(mean_prediction[product_number, axis_number]),
                    "uncertainty": float(uncertainty[product_number, axis_number]),
                    "instance_confidence": float(instance_confidence[product_number, axis_number]),
                    "property_recoverability": float(recovery[axis_number]),
                    "reliability": {method: float(reliability_matrices[method][product_number, axis_number]) for method in METHODS},
                    "visual_state": {
                        method: "SUPPORTED" if decisions[method][product_number, axis_number] else "VISUAL_ABSTAIN"
                        for method in METHODS
                    },
                }
            )
    records_path = PATHS.artifacts / "selective_prediction_records.jsonl"
    write_jsonl(records_path, records)
    results_path = PATHS.artifacts / "phase9_selective_results.json"
    results = {
        "status": "complete", "phase": 9, "generated_at": utc_now(),
        "predictor": "FashionCLIP Ridge bootstrap ensemble",
        "ensemble_members": members,
        "property_recoverability_source": "Phase 8 external MLLM-Fabric pairwise accuracy",
        "calibration_split": "development only",
        "generic_calibrator": "one cross-axis logistic calibrator over [instance confidence, property recoverability, product]",
        "correctness_tolerance": tolerance,
        "primary_coverage": primary_coverage,
        "thresholds": thresholds,
        "methods": method_results,
        "limitations": [
            "Property recoverability is zero when no compatible external benchmark was available.",
            "The bootstrap ensemble estimates model instability, not total epistemic or perceptual uncertainty.",
            "Amazon targets remain hidden-review pseudo-targets rather than physical touch measurements.",
        ],
    }
    write_json(results_path, results)
    manifest = {
        "status": "complete", "phase": 9, "generated_at": utc_now(),
        "outputs": {
            "results": str(results_path), "results_sha256": sha256_file(results_path),
            "matrices": str(matrix_path), "matrices_sha256": sha256_file(matrix_path),
            "records": str(records_path), "records_sha256": sha256_file(records_path),
        },
        "method_aurc": {method: method_results[method]["aurc"] for method in METHODS},
    }
    write_json(PATHS.manifests / "phase9_selective.json", manifest)
    _write_report(results)
    return manifest


def _write_report(results: dict[str, Any]) -> None:
    lines = [
        "# Phase 9 — Confidence and Recoverability Calibration", "",
        "Property recoverability and instance confidence remain separate inputs. Thresholds and the generic cross-axis calibrator use only the development split.", "",
        "| Method | AURC ↓ | confidence/error Spearman | ECE ↓ | risk @ nominal 80% |", "|---|---:|---:|---:|---:|",
    ]
    for method, values in results["methods"].items():
        correlation = "—" if values["confidence_error_spearman"] is None else f"{values['confidence_error_spearman']:.3f}"
        ece = "—" if values["expected_calibration_error"] is None else f"{values['expected_calibration_error']:.3f}"
        risk = values["fixed_coverage"]["0.8"]["test_risk_mae"]
        lines.append(f"| {method} | {values['aurc']:.3f} | {correlation} | {ece} | {'—' if risk is None else f'{risk:.3f}'} |")
    lines.extend(["", "VISUAL_ABSTAIN is an inference decision. It is never used as a target class and never converts REVIEW_UNOBSERVED to neutral."])
    (PATHS.reports / "phase9_selective_prediction.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
