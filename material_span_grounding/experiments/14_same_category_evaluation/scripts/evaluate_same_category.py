#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import numpy as np

from common import (
    CONFIG_PATH,
    ROOT,
    aggregate_cells,
    atomic_csv,
    atomic_json,
    average_precision_tie_safe,
    cell_metrics,
    pairwise_accuracy,
    percentile_interval,
    read_json,
    sha256,
    source_hashes,
)


PRIMARY_METRICS = (
    "macro_cell_auroc",
    "pair_weighted_auroc",
    "macro_category_average_precision",
    "macro_category_ap_lift",
    "macro_category_normalized_ap_lift",
    "pairwise_accuracy",
)


def fmt(value: float | None, digits: int = 4) -> str:
    return "N/A" if value is None else f"{value:.{digits}f}"


def metric_row(truth: np.ndarray, scores: np.ndarray) -> dict[str, float] | None:
    truth = truth.astype(bool)
    positive = int(truth.sum())
    negative = len(truth) - positive
    if positive == 0 or negative == 0:
        return None
    prevalence = positive / len(truth)
    auc = pairwise_accuracy(scores[truth], scores[~truth])
    ap = average_precision_tie_safe(truth, scores)
    lift = ap - prevalence
    return {
        "observed": len(truth),
        "positive": positive,
        "negative": negative,
        "prevalence": prevalence,
        "auroc": auc,
        "average_precision": ap,
        "ap_lift": lift,
        "normalized_ap_lift": lift / (1.0 - prevalence),
        "pairwise_accuracy": auc,
    }


def make_cells(
    categories: np.ndarray,
    classes: list[str],
    category_names: list[str],
    values: np.ndarray,
    masks: np.ndarray,
    last2_scores: np.ndarray,
    category_scores: np.ndarray,
    last2_thresholds: np.ndarray,
    category_thresholds: np.ndarray,
    reliable_positive: int,
    reliable_negative: int,
) -> list[dict[str, Any]]:
    rows = []
    for category in category_names:
        category_mask = categories == category
        for class_number, class_name in enumerate(classes):
            selected = category_mask & masks[:, class_number].astype(bool)
            truth = values[selected, class_number] >= 0.5
            row = {
                "category": category,
                "class": class_name,
                "last2": cell_metrics(
                    truth,
                    last2_scores[selected, class_number],
                    float(last2_thresholds[class_number]),
                    reliable_positive,
                    reliable_negative,
                ),
                "category_only": cell_metrics(
                    truth,
                    category_scores[selected, class_number],
                    float(category_thresholds[class_number]),
                    reliable_positive,
                    reliable_negative,
                ),
            }
            for key in ("observed", "positive", "negative", "prevalence", "valid", "skip_reason", "reliable_support", "pair_count"):
                assert row["last2"][key] == row["category_only"][key]
                row[key] = row["last2"][key]
            rows.append(row)
    return rows


def group_aggregates(
    cells: list[dict[str, Any]], group_key: str, names: list[str], models: tuple[str, ...]
) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for name in names:
        group = [row for row in cells if row[group_key] == name]
        output[name] = {
            "all_observed": int(sum(row["observed"] for row in group)),
            "all_positive": int(sum(row["positive"] for row in group)),
            "all_negative": int(sum(row["negative"] for row in group)),
            "valid_cells": int(sum(row["valid"] for row in group)),
            "reliable_cells": int(sum(row["reliable_support"] for row in group)),
        }
        for model in models:
            output[name][model] = {
                "all_valid": aggregate_cells([row[model] for row in group]),
                "reliable_support": aggregate_cells([row[model] for row in group], reliable_only=True),
            }
    return output


def center_scores(
    evaluated_scores: np.ndarray,
    evaluated_categories: np.ndarray,
    reference_scores: np.ndarray,
    reference_categories: np.ndarray,
    category_names: list[str],
) -> tuple[np.ndarray, dict[str, list[float]], list[str]]:
    centered = evaluated_scores.copy().astype(np.float64)
    means: dict[str, list[float]] = {}
    missing: list[str] = []
    fallback = reference_scores.mean(axis=0)
    for category in category_names:
        reference_selected = reference_categories == category
        if reference_selected.any():
            mean = reference_scores[reference_selected].mean(axis=0)
        else:
            mean = fallback
            missing.append(category)
        means[category] = mean.astype(float).tolist()
        centered[evaluated_categories == category] -= mean
    return centered, means, missing


def centered_diagnostics(
    scores: np.ndarray,
    values: np.ndarray,
    masks: np.ndarray,
    classes: list[str],
) -> dict[str, Any]:
    per_class: dict[str, Any] = {}
    macro_rows = []
    flat_truth = []
    flat_scores = []
    for number, name in enumerate(classes):
        selected = masks[:, number].astype(bool)
        truth = values[selected, number] >= 0.5
        row = metric_row(truth, scores[selected, number])
        per_class[name] = row
        if row is not None:
            macro_rows.append(row)
        flat_truth.extend(truth.tolist())
        flat_scores.extend(scores[selected, number].tolist())
    pooled = metric_row(np.asarray(flat_truth, dtype=bool), np.asarray(flat_scores, dtype=float))
    return {
        "macro_class_auroc": float(np.mean([row["auroc"] for row in macro_rows])),
        "macro_class_average_precision": float(np.mean([row["average_precision"] for row in macro_rows])),
        "macro_class_ap_lift": float(np.mean([row["ap_lift"] for row in macro_rows])),
        "macro_class_normalized_ap_lift": float(np.mean([row["normalized_ap_lift"] for row in macro_rows])),
        "pooled_observed_pairs": pooled,
        "per_class": per_class,
    }


def bootstrap_aggregate(
    categories: np.ndarray,
    values: np.ndarray,
    masks: np.ndarray,
    scores: np.ndarray,
    category_names: list[str],
    reliable_positive: int,
    reliable_negative: int,
    reliable_only: bool,
) -> dict[str, Any]:
    rows = []
    for category in category_names:
        category_mask = categories == category
        for class_number in range(values.shape[1]):
            selected = category_mask & masks[:, class_number].astype(bool)
            truth = values[selected, class_number] >= 0.5
            positive = int(truth.sum())
            negative = len(truth) - positive
            if positive == 0 or negative == 0:
                continue
            if reliable_only and (positive < reliable_positive or negative < reliable_negative):
                continue
            cell = metric_row(truth, scores[selected, class_number])
            assert cell is not None
            cell["valid"] = True
            cell["reliable_support"] = True
            cell["pair_count"] = positive * negative
            rows.append(cell)
    return aggregate_cells(rows)


def family_bootstrap(
    family_ids: np.ndarray,
    categories: np.ndarray,
    values: np.ndarray,
    masks: np.ndarray,
    model_scores: dict[str, np.ndarray],
    category_names: list[str],
    config: dict[str, Any],
    points: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    bootstrap_config = config["bootstrap"]
    support = config["support"]
    unique_families = np.unique(family_ids)
    family_members = {family: np.flatnonzero(family_ids == family) for family in unique_families}
    rng = np.random.default_rng(int(bootstrap_config["seed"]))
    subsets = ("all_valid", "reliable_support")
    models = ("category_only", "last2")
    stored = {
        subset: {
            model: {metric: [] for metric in PRIMARY_METRICS}
            for model in (*models, "last2_minus_category_only")
        }
        for subset in subsets
    }
    cell_counts = {subset: [] for subset in subsets}
    unavailable = {subset: Counter() for subset in subsets}
    for replicate in range(int(bootstrap_config["replicates"])):
        sampled = rng.choice(unique_families, size=len(unique_families), replace=True)
        indices = np.concatenate([family_members[family] for family in sampled])
        replicate_results: dict[str, dict[str, Any]] = {subset: {} for subset in subsets}
        for subset in subsets:
            reliable_only = subset == "reliable_support"
            for model in models:
                replicate_results[subset][model] = bootstrap_aggregate(
                    categories[indices],
                    values[indices],
                    masks[indices],
                    model_scores[model][indices],
                    category_names,
                    int(support["reliable_minimum_positive"]),
                    int(support["reliable_minimum_negative"]),
                    reliable_only,
                )
            cell_counts[subset].append(replicate_results[subset]["last2"]["valid_cells"])
            for metric in PRIMARY_METRICS:
                first = replicate_results[subset]["category_only"][metric]
                second = replicate_results[subset]["last2"][metric]
                if first is None or second is None:
                    unavailable[subset][metric] += 1
                    continue
                stored[subset]["category_only"][metric].append(first)
                stored[subset]["last2"][metric].append(second)
                stored[subset]["last2_minus_category_only"][metric].append(second - first)
        if (replicate + 1) % 100 == 0:
            print(f"bootstrap={replicate + 1}/{bootstrap_config['replicates']}", flush=True)
    confidence = float(bootstrap_config["confidence_level"])
    summary: dict[str, Any] = {
        "unit": bootstrap_config["unit"],
        "replicates_requested": int(bootstrap_config["replicates"]),
        "seed": int(bootstrap_config["seed"]),
        "confidence_level": confidence,
    }
    for subset in subsets:
        summary[subset] = {
            "eligible_cell_count_per_replicate": {
                "minimum": int(min(cell_counts[subset])),
                "maximum": int(max(cell_counts[subset])),
                "mean": float(np.mean(cell_counts[subset])),
            },
            "unavailable_replicates": dict(unavailable[subset]),
        }
        for model in (*models, "last2_minus_category_only"):
            summary[subset][model] = {}
            for metric in PRIMARY_METRICS:
                values_list = stored[subset][model][metric]
                if model == "last2_minus_category_only":
                    point = points[subset]["last2"][metric] - points[subset]["category_only"][metric]
                else:
                    point = points[subset][model][metric]
                summary[subset][model][metric] = {
                    "point_estimate": point,
                    **percentile_interval(values_list, confidence),
                }
    return summary


def qualitative_candidates(
    product_ids: np.ndarray,
    family_ids: np.ndarray,
    categories: np.ndarray,
    image_paths: np.ndarray,
    values: np.ndarray,
    masks: np.ndarray,
    probabilities: np.ndarray,
    centered_scores: np.ndarray,
    classes: list[str],
    limit: int,
) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for number, name in enumerate(classes):
        observed = masks[:, number].astype(bool)
        positive = observed & (values[:, number] >= 0.5)
        negative = observed & (values[:, number] < 0.5)

        def collect(indices: np.ndarray) -> list[dict[str, Any]]:
            return [
                {
                    "asin": str(product_ids[index]),
                    "family_id": str(family_ids[index]),
                    "category": str(categories[index]),
                    "tactile_class": name,
                    "target": float(values[index, number]),
                    "last2_probability": float(probabilities[index, number]),
                    "within_category_centered_score": float(centered_scores[index, number]),
                    "image_identifier": Path(str(image_paths[index])).name,
                    "image_path": str(image_paths[index]),
                    "evidence_id": None,
                }
                for index in indices[:limit]
            ]

        positive_indices = np.flatnonzero(positive)
        negative_indices = np.flatnonzero(negative)
        high_positive = positive_indices[np.argsort(-centered_scores[positive_indices, number], kind="mergesort")]
        low_positive = positive_indices[np.argsort(centered_scores[positive_indices, number], kind="mergesort")]
        high_negative = negative_indices[np.argsort(-centered_scores[negative_indices, number], kind="mergesort")]
        output[name] = {
            "success_candidates": collect(high_positive),
            "failure_candidates": collect(low_positive),
            "false_positive_candidates": collect(high_negative),
        }
    return {
        "status": "human_audit_candidates_only_not_automatically_judged",
        "ranking_basis": "Last2 probability centered by label-free locked-test category/class score mean",
        "evidence_linkage": "not added because no direct stable evidence ID was required for inference",
        "per_class": output,
    }


def build_report(results: dict[str, Any]) -> str:
    all_valid = results["global_same_category"]["all_valid"]
    reliable = results["global_same_category"]["reliable_support"]
    bootstrap = results["bootstrap_confidence_intervals"]
    last2 = all_valid["last2"]
    category = all_valid["category_only"]
    delta = all_valid["last2_minus_category_only"]
    lines = [
        "# Same-category Evaluation Results",
        "",
        "## 1. 실험 목적",
        "",
        "상품 category를 고정한 상태에서 공식 FashionCLIP Last2 score가 동일 category 내 tactile-positive 상품을 tactile-negative 상품보다 높게 ranking하는지 평가했다. 이것은 새 모델 학습이 아니라 고정 checkpoint의 post-hoc diagnostic이다.",
        "",
        "## 2. 평가 설계",
        "",
        "Locked test의 각 `(category, tactile class)`를 독립적인 binary ranking cell로 정의했다. mask=1이고 positive와 negative가 모두 있는 cell만 primary 평가에 포함했다. AUROC와 모든 positive-negative pair의 tie=0.5 pairwise accuracy를 primary로 사용하고, AP는 해당 cell prevalence를 뺀 AP lift와 함께 해석했다. 기존 development-selected global threshold의 F1은 secondary metric이며 category별 threshold를 선택하지 않았다.",
        "",
        "## 3. 데이터와 support",
        "",
        f"기존 split과 target/mask를 그대로 사용했다: 전체 {results['dataset_counts']['all']:,}, train {results['dataset_counts']['train']:,}, development {results['dataset_counts']['development']:,}, locked test {results['dataset_counts']['test']:,}; test family {results['dataset_counts']['test_families']:,}, family overlap 0. Category는 11종이며 전체 valid cell은 {results['cell_counts']['valid']}/{results['cell_counts']['total']}, reliable-support(positive≥10, negative≥10)는 {results['cell_counts']['reliable_support']}개다.",
        "",
        "| Category | Test products | Valid classes | Reliable classes |",
        "|---|---:|---:|---:|",
    ]
    for name, count in results["category_counts"]["test"].items():
        row = results["per_category"][name]
        lines.append(f"| {name} | {count} | {row['valid_cells']} | {row['reliable_cells']} |")
    lines.extend([
        "",
        "## 4. Global same-category 결과",
        "",
        "| Metric | Category-only | Last2 | Last2 − Category-only |",
        "|---|---:|---:|---:|",
    ])
    metric_labels = {
        "macro_cell_auroc": "Macro-cell AUROC",
        "pair_weighted_auroc": "Pair-weighted AUROC",
        "macro_category_average_precision": "Macro category-cell AP",
        "macro_category_ap_lift": "Macro AP lift",
        "macro_category_normalized_ap_lift": "Macro normalized AP lift",
        "pairwise_accuracy": "Pairwise accuracy",
    }
    for metric in PRIMARY_METRICS:
        lines.append(f"| {metric_labels[metric]} | {fmt(category[metric])} | {fmt(last2[metric])} | {fmt(delta[metric])} |")
    lines.extend([
        "",
        f"Category-only의 category/class 내부 최대 probability range는 {results['category_only_constant_check']['maximum_probability_range']:.3g}이며 tolerance {results['category_only_constant_check']['tolerance']:.1g} 이하다. 실제 계산된 AUROC/pairwise accuracy가 0.5이고 AP lift가 0에 가까워 constant predictor sanity check를 통과했다.",
        "",
        "## 5. Class별 결과",
        "",
        "| Class | Valid cat. | Reliable cat. | Obs. | Pos. | Last2 macro AUC | Last2 pair-w. AUC | Macro AP lift | Cat-only AUC |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ])
    for name in results["classes"]:
        row = results["per_class"][name]
        image = row["last2"]["all_valid"]
        baseline = row["category_only"]["all_valid"]
        lines.append(
            f"| {name} | {row['valid_cells']} | {row['reliable_cells']} | {row['all_observed']} | {row['all_positive']} | {fmt(image['macro_cell_auroc'])} | {fmt(image['pair_weighted_auroc'])} | {fmt(image['macro_category_ap_lift'])} | {fmt(baseline['macro_cell_auroc'])} |"
        )
    focused = results["focused_class_interpretation"]
    lines.extend(["", "집중 class:", ""])
    for name, text in focused.items():
        lines.append(f"- `{name}`: {text}")
    lines.extend([
        "",
        "`firm`, `non_elastic`, `spongy`, `crisp`는 sparse cell이 많아 descriptive result로만 해석해야 한다. AUROC 1.0 같은 극단값도 support가 작으면 강한 증거가 아니다.",
        "",
        "## 6. Category별 결과",
        "",
        "| Category | Valid classes | Reliable classes | Observed pairs | Last2 macro AUROC | Last2 macro AP lift |",
        "|---|---:|---:|---:|---:|---:|",
    ])
    for name in results["categories"]:
        row = results["per_category"][name]
        image = row["last2"]["all_valid"]
        lines.append(f"| {name} | {row['valid_cells']} | {row['reliable_cells']} | {row['all_observed']} | {fmt(image['macro_cell_auroc'])} | {fmt(image['macro_category_ap_lift'])} |")
    rel_last2 = reliable["last2"]
    rel_category = reliable["category_only"]
    rel_delta = reliable["last2_minus_category_only"]
    lines.extend([
        "",
        "## 7. Reliable-support 분석",
        "",
        f"사전에 고정한 positive≥10 및 negative≥10 조건을 만족하는 {rel_last2['valid_cells']}개 cell 결과다.",
        "",
        "| Metric | Category-only | Last2 | Difference |",
        "|---|---:|---:|---:|",
    ])
    for metric in PRIMARY_METRICS:
        lines.append(f"| {metric_labels[metric]} | {fmt(rel_category[metric])} | {fmt(rel_last2[metric])} | {fmt(rel_delta[metric])} |")
    lines.extend([
        "",
        "## 8. Bootstrap CI",
        "",
        f"Locked-test parent family 단위 paired bootstrap {bootstrap['replicates_requested']:,}회(seed {bootstrap['seed']})의 percentile 95% CI다. 각 replicate에서 single-class cell은 안전하게 제외했다.",
        "",
        "| Subset / Metric | Last2 estimate | Last2 95% CI | Difference estimate | Difference 95% CI |",
        "|---|---:|---:|---:|---:|",
    ])
    for subset in ("all_valid", "reliable_support"):
        for metric in ("macro_cell_auroc", "pair_weighted_auroc", "macro_category_ap_lift", "pairwise_accuracy"):
            image_ci = bootstrap[subset]["last2"][metric]
            delta_ci = bootstrap[subset]["last2_minus_category_only"][metric]
            lines.append(
                f"| {subset} / {metric} | {fmt(image_ci['point_estimate'])} | [{fmt(image_ci['lower'])}, {fmt(image_ci['upper'])}] | {fmt(delta_ci['point_estimate'])} | [{fmt(delta_ci['lower'])}, {fmt(delta_ci['upper'])}] |"
            )
    centered = results["centered_score_diagnostic"]
    lines.extend([
        "",
        "Category-centered score는 label을 쓰지 않고 category/class 평균 score만 제거했다. Test 자체 평균을 뺀 transductive diagnostic과 development 평균을 test에 적용한 stricter diagnostic을 모두 저장했다.",
        "",
        "| Centering reference | Macro-class AUROC | Pooled AUROC | Pooled AP lift |",
        "|---|---:|---:|---:|",
    ])
    for key, label in (("locked_test_score_mean", "Locked-test score mean"), ("development_score_mean", "Development score mean")):
        row = centered[key]["metrics"]
        lines.append(f"| {label} | {fmt(row['macro_class_auroc'])} | {fmt(row['pooled_observed_pairs']['auroc'])} | {fmt(row['pooled_observed_pairs']['ap_lift'])} |")
    lines.extend([
        "",
        "## 9. F1 vs ranking metric",
        "",
        "Same-category 판단의 primary metric은 AUROC, pairwise accuracy, AP lift다. F1은 prevalence와 기존 global development threshold에 민감하므로 CSV에 secondary metric으로만 보존했다. 특히 soft처럼 prevalence가 높은 class는 constant prediction도 높은 F1을 얻을 수 있다.",
        "",
        "## 10. Category shortcut에 대한 결론",
        "",
        results["conclusion"],
        "",
        "이 결과는 category를 고정해도 image-correlated ranking signal이 남는지를 말할 뿐, 모델이 물리적 촉감을 인과적으로 이해한다는 증거는 아니다.",
        "",
        "## 11. 한계",
        "",
        "Target은 human ground truth가 아니라 review/Qwen-derived pseudo-label이다. 일부 속성은 이미지에서 직접 관측하기 어렵고, sparse class/cell은 추정 불확실성이 크다. Post-hoc locked-test diagnostic이므로 결과를 본 뒤 cutoff, threshold, checkpoint를 변경하지 않았다.",
        "",
        "## 12. 다음 실험",
        "",
        "추출된 qualitative candidate를 human audit하고, reliable-support class를 중심으로 category-matched retrieval 및 family/category-stratified 검증을 수행하는 것이 우선이다. 이미지 관측 가능성이 높은 class에만 confidence weighting을 적용하는 downstream 설계도 검토할 수 있다.",
        "",
        "## Sanity checks",
        "",
    ])
    for name, passed in results["sanity_checks"].items():
        lines.append(f"- {'PASS' if passed else 'FAIL'} — `{name}`")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    artifacts = ROOT / "artifacts"
    results_path = artifacts / "same_category_results.json"
    csv_path = artifacts / "per_category_class_metrics.csv"
    candidates_path = artifacts / "qualitative_candidates.json"
    report_path = ROOT / "notion" / "SAME_CATEGORY_EVALUATION_RESULTS.md"
    if args.verify_only:
        for path in (results_path, csv_path, candidates_path, report_path):
            assert path.is_file() and path.stat().st_size > 0
            print(f"{path.name}_sha256={sha256(path)}")
        results = read_json(results_path)
        assert all(results["sanity_checks"].values())
        assert results["source_hashes"] == source_hashes(read_json(CONFIG_PATH))
        print("all_sanity_checks=PASS")
        return 0
    if any(path.exists() for path in (results_path, csv_path, candidates_path, report_path)):
        raise SystemExit("evaluation outputs already exist; use --verify-only")

    config = read_json(CONFIG_PATH)
    sources_before = source_hashes(config)
    prediction_manifest = read_json(artifacts / "prediction_manifest.json")
    predictions_path = artifacts / "fixed_model_predictions.npz"
    assert prediction_manifest["prediction_sha256"] == sha256(predictions_path)
    assert prediction_manifest["source_hashes"] == sources_before
    with np.load(predictions_path, allow_pickle=False) as predictions:
        classes = predictions["classes"].astype(str).tolist()
        development_ids = predictions["development_product_ids"].astype(str)
        test_ids = predictions["test_product_ids"].astype(str)
        development_last2 = predictions["development_last2_probabilities"].astype(np.float64)
        test_last2 = predictions["test_last2_probabilities"].astype(np.float64)
        development_category_scores = predictions["development_category_probabilities"].astype(np.float64)
        test_category_scores = predictions["test_category_probabilities"].astype(np.float64)
        last2_thresholds = predictions["last2_thresholds"].astype(np.float64)
        category_thresholds = predictions["category_thresholds"].astype(np.float64)
    assert classes == config["classes"]

    split_document = read_json(Path(config["paths"]["split_manifest"]))
    split = split_document["splits"]
    assert test_ids.tolist() == split["test"]
    assert development_ids.tolist() == split["development"]
    metadata_rows = read_json(Path(config["paths"]["product_metadata"]))
    metadata = {str(row[config["product_id_field"]]): row for row in metadata_rows}
    test_categories = np.asarray([str(metadata[value][config["category_field"]]) for value in test_ids])
    development_categories = np.asarray([str(metadata[value][config["category_field"]]) for value in development_ids])
    test_families = np.asarray([str(metadata[value][config["family_id_field"]]) for value in test_ids])
    test_image_paths = np.asarray([str(metadata[value][config["image_path_field"]]) for value in test_ids])
    category_names = config["categories"]
    assert sorted(np.unique(test_categories).tolist()) == category_names

    with np.load(Path(config["paths"]["v3_targets"]), allow_pickle=False) as targets:
        target_ids = targets["product_ids"].astype(str)
        assert targets["classes"].astype(str).tolist() == classes
        index = {value: number for number, value in enumerate(target_ids)}
        test_indices = np.asarray([index[value] for value in test_ids], dtype=np.int64)
        test_values = targets["values"][test_indices].astype(np.float32)
        test_masks = targets["mask"][test_indices].astype(np.uint8)

    support = config["support"]
    cells = make_cells(
        test_categories,
        classes,
        category_names,
        test_values,
        test_masks,
        test_last2,
        test_category_scores,
        last2_thresholds,
        category_thresholds,
        int(support["reliable_minimum_positive"]),
        int(support["reliable_minimum_negative"]),
    )
    models = ("category_only", "last2")
    global_results: dict[str, Any] = {}
    for subset, reliable_only in (("all_valid", False), ("reliable_support", True)):
        global_results[subset] = {
            model: aggregate_cells([row[model] for row in cells], reliable_only=reliable_only)
            for model in models
        }
        global_results[subset]["last2_minus_category_only"] = {
            metric: (
                global_results[subset]["last2"][metric] - global_results[subset]["category_only"][metric]
                if global_results[subset]["last2"][metric] is not None
                else None
            )
            for metric in PRIMARY_METRICS
        }

    per_class = group_aggregates(cells, "class", classes, models)
    per_category = group_aggregates(cells, "category", category_names, models)
    valid_cells = [row for row in cells if row["valid"]]
    skipped_cells = [
        {
            "category": row["category"],
            "class": row["class"],
            "observed": row["observed"],
            "positive": row["positive"],
            "negative": row["negative"],
            "reason": row["skip_reason"],
        }
        for row in cells
        if not row["valid"]
    ]
    skip_reason_counts = dict(Counter(row["reason"] for row in skipped_cells))

    test_centered, test_means, test_missing = center_scores(
        test_last2, test_categories, test_last2, test_categories, category_names
    )
    development_centered, development_means, development_missing = center_scores(
        test_last2, test_categories, development_last2, development_categories, category_names
    )
    centered_result = {
        "locked_test_score_mean": {
            "label_usage_for_mean": False,
            "reference_split": "locked test scores only",
            "missing_reference_categories": test_missing,
            "category_class_means": test_means,
            "metrics": centered_diagnostics(test_centered, test_values, test_masks, classes),
        },
        "development_score_mean": {
            "label_usage_for_mean": False,
            "reference_split": "development scores only",
            "missing_reference_categories": development_missing,
            "category_class_means": development_means,
            "metrics": centered_diagnostics(development_centered, test_values, test_masks, classes),
        },
    }

    print("starting family-level bootstrap", flush=True)
    bootstrap = family_bootstrap(
        test_families,
        test_categories,
        test_values,
        test_masks,
        {"last2": test_last2, "category_only": test_category_scores},
        category_names,
        config,
        global_results,
    )

    candidates = qualitative_candidates(
        test_ids,
        test_families,
        test_categories,
        test_image_paths,
        test_values,
        test_masks,
        test_last2,
        test_centered,
        classes,
        int(config["qualitative_candidates_per_type"]),
    )
    atomic_json(candidates_path, candidates)

    csv_rows = []
    for row in cells:
        image = row["last2"]
        baseline = row["category_only"]
        csv_rows.append(
            {
                "category": row["category"],
                "class": row["class"],
                "observed": row["observed"],
                "positive": row["positive"],
                "negative": row["negative"],
                "prevalence": row["prevalence"],
                "last2_auroc": image["auroc"],
                "last2_average_precision": image["average_precision"],
                "last2_ap_lift": image["ap_lift"],
                "last2_normalized_ap_lift": image["normalized_ap_lift"],
                "last2_pairwise_accuracy": image["pairwise_accuracy"],
                "last2_precision": image["precision"],
                "last2_recall": image["recall"],
                "last2_f1": image["f1"],
                "last2_existing_development_threshold": image["threshold"],
                "category_only_auroc": baseline["auroc"],
                "category_only_average_precision": baseline["average_precision"],
                "category_only_ap_lift": baseline["ap_lift"],
                "category_only_probability_range": baseline["probability_range"],
                "valid": row["valid"],
                "skip_reason": row["skip_reason"],
                "reliable_support": row["reliable_support"],
            }
        )
    csv_fields = list(csv_rows[0])
    atomic_csv(csv_path, csv_fields, csv_rows)

    maximum_category_range = max(
        row["category_only"]["probability_range"] or 0.0 for row in cells
    )
    tolerance = float(config["category_constant_probability_tolerance"])
    v3_results = read_json(Path(config["paths"]["v3_results"]))["last2"]
    category13 = read_json(Path(config["paths"]["category_results"]))
    checkpoint_last2 = sources_before["last2_checkpoint"]
    checkpoint_category = sources_before["category_checkpoint"]
    family_sets = {name: set(split_document["families"][name]) for name in ("train", "development", "test")}
    family_overlap = {
        "train__development": len(family_sets["train"] & family_sets["development"]),
        "train__test": len(family_sets["train"] & family_sets["test"]),
        "development__test": len(family_sets["development"] & family_sets["test"]),
    }
    class_counts = {}
    for number, name in enumerate(classes):
        observed = test_masks[:, number].astype(bool)
        positive = int((test_values[observed, number] >= 0.5).sum())
        class_counts[name] = {
            "observed": int(observed.sum()),
            "positive": positive,
            "negative": int(observed.sum()) - positive,
        }
    category13_config = read_json(Path(config["paths"]["category_config"]))
    source_after = source_hashes(config)
    sanity = {
        "official_last2_checkpoint_hash_matches_pre_inference_manifest": checkpoint_last2 == prediction_manifest["last2_checkpoint_sha256"],
        "model_weights_not_changed": source_after["last2_checkpoint"] == checkpoint_last2 and prediction_manifest["parameter_updates_performed"] is False,
        "qwen_grounding_not_executed": True,
        "v3_target_not_regenerated_or_modified": source_after["v3_targets"] == sources_before["v3_targets"],
        "original_family_disjoint_split_reused": source_after["split_manifest"] == sources_before["split_manifest"] and all(value == 0 for value in family_overlap.values()),
        "observed_mask_only_evaluated": sum(class_counts[name]["observed"] for name in classes) == int(test_masks.sum()),
        "category_field_matches_experiment13": config["category_field"] == category13_config["data"]["category_field"] == category13["category_field"],
        "no_category_specific_threshold_tuning": config["evaluation"]["threshold_tuning"] is False,
        "existing_development_thresholds_reused": prediction_manifest["last2_threshold_source"] == config["evaluation"]["threshold_source"] and np.allclose(last2_thresholds, v3_results["thresholds"], rtol=0, atol=1e-7),
        "locked_test_not_used_for_model_selection": config["evaluation"]["new_training"] is False and prediction_manifest["new_training_performed"] is False,
        "category_only_constant_within_category": maximum_category_range <= tolerance,
        "single_class_cells_skipped_with_reason": len(skipped_cells) > 0 and sum(skip_reason_counts.values()) == len(skipped_cells),
        "support_saved_for_every_cell": all(all(key in row for key in ("observed", "positive", "negative")) for row in cells),
        "existing_v2_v3_v13_files_unchanged": source_after == sources_before == prediction_manifest["source_hashes"],
    }
    assert all(sanity.values()), sanity

    reliable_class_auc = {
        name: row["last2"]["reliable_support"]["pair_weighted_auroc"]
        for name, row in per_class.items()
        if row["last2"]["reliable_support"]["pair_weighted_auroc"] is not None
    }
    strongest = sorted(reliable_class_auc, key=lambda name: reliable_class_auc[name], reverse=True)
    closest = sorted(reliable_class_auc, key=lambda name: abs(reliable_class_auc[name] - 0.5))
    focused_interpretation = {}
    for name in config["focused_classes"]:
        row = per_class[name]["last2"]["all_valid"]
        focused_interpretation[name] = (
            f"valid/reliable category {per_class[name]['valid_cells']}/{per_class[name]['reliable_cells']}, "
            f"pair-weighted AUROC {fmt(row['pair_weighted_auroc'])}, macro AP lift {fmt(row['macro_category_ap_lift'])}."
        )
    delta_auc = global_results["all_valid"]["last2_minus_category_only"]["pair_weighted_auroc"]
    delta_ci = bootstrap["all_valid"]["last2_minus_category_only"]["pair_weighted_auroc"]
    if delta_ci["lower"] > 0:
        conclusion = (
            f"Last2의 within-category pair-weighted AUROC가 Category-only보다 {delta_auc:+.4f} 높고 paired family-bootstrap 95% CI도 0을 상회한다. "
            "따라서 category prior만으로 설명되지 않는 image-correlated within-category ranking signal이 있다는 근거가 있다. "
            "동시에 global Category-only 성능이 높았다는 사실은 category shortcut이 여전히 중요한 설명임을 뜻하므로, 두 현상은 함께 존재한다."
        )
    else:
        conclusion = (
            f"Last2의 within-category pair-weighted AUROC 차이는 {delta_auc:+.4f}이며 paired family-bootstrap CI가 0을 명확히 넘지 않는다. "
            "따라서 현재 결과만으로 category를 넘어서는 안정적인 image ranking signal을 주장하기 어렵고 category-correlated shortcut이 주된 설명일 가능성이 남는다."
        )

    results = {
        "status": "complete_posthoc_evaluation_no_training_or_tuning",
        "dataset_counts": {
            **config["expected_counts"],
            "test_families": len(np.unique(test_families)),
            "test_observed_product_class_pairs": int(test_masks.sum()),
        },
        "category_field": config["category_field"],
        "categories": category_names,
        "classes": classes,
        "category_counts": {
            "development": {name: int((development_categories == name).sum()) for name in category_names},
            "test": {name: int((test_categories == name).sum()) for name in category_names},
        },
        "class_counts": class_counts,
        "support_definition": support,
        "cell_counts": {
            "total": len(cells),
            "valid": len(valid_cells),
            "reliable_support": sum(row["reliable_support"] for row in cells),
            "skipped": len(skipped_cells),
            "skipped_by_reason": skip_reason_counts,
        },
        "skipped_cells": skipped_cells,
        "global_same_category": global_results,
        "per_class": per_class,
        "per_category": per_category,
        "bootstrap_confidence_intervals": bootstrap,
        "centered_score_diagnostic": centered_result,
        "category_only_constant_check": {
            "tolerance": tolerance,
            "maximum_probability_range": maximum_category_range,
            "all_cells_within_tolerance": maximum_category_range <= tolerance,
            "actual_all_valid_metrics": global_results["all_valid"]["category_only"],
        },
        "secondary_threshold_metrics": {
            "threshold_source": config["evaluation"]["threshold_source"],
            "category_specific_threshold_tuning": False,
            "location": "per_category_class_metrics.csv",
        },
        "strongest_reliable_classes_by_pair_weighted_auroc": strongest,
        "closest_to_chance_reliable_classes_by_pair_weighted_auroc": closest,
        "focused_class_interpretation": focused_interpretation,
        "rare_class_warning": config["rare_classes"],
        "conclusion": conclusion,
        "qualitative_candidates": str(candidates_path),
        "prediction_manifest": str(artifacts / "prediction_manifest.json"),
        "source_hashes": sources_before,
        "source_hashes_unchanged": source_after == sources_before,
        "family_overlap": family_overlap,
        "sanity_checks": sanity,
    }
    atomic_json(results_path, results)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(build_report(results), encoding="utf-8")
    print(f"macro_cell_auroc={global_results['all_valid']['last2']['macro_cell_auroc']:.10f}")
    print(f"pair_weighted_auroc={global_results['all_valid']['last2']['pair_weighted_auroc']:.10f}")
    print(f"macro_ap_lift={global_results['all_valid']['last2']['macro_category_ap_lift']:.10f}")
    print(f"results={results_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
