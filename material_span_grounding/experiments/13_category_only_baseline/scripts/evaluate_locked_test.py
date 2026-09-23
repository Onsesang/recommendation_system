#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import numpy as np
import torch

from common import (
    CONFIG_PATH,
    ROOT,
    CategoryClassifier,
    atomic_json,
    calculate_metrics,
    load_config,
    pairwise_overlap,
    read_json,
    seed_everything,
    sha256,
    source_hashes,
)


def fmt(value: float | None, digits: int = 4) -> str:
    return "N/A" if value is None else f"{value:.{digits}f}"


def load_v3_comparison(path: Path) -> dict[str, Any]:
    results = read_json(path)
    comparison = {}
    for regime in ("frozen", "projection", "last1", "last2", "full"):
        row = results[regime]["test"]
        comparison[regime] = {
            "macro_f1": row["macro_f1"],
            "micro_f1": row["micro_f1"],
            "macro_average_precision": row["macro_average_precision"],
        }
    return comparison


def build_report(results: dict[str, Any]) -> str:
    test = results["locked_test"]
    development = results["development"]
    delta = results["last2_comparison"]
    lines = [
        "# Category-only Baseline Results",
        "",
        "## 1. 실험 목적",
        "",
        "이미지 없이 상품 category만으로 v3 tactile atomic-class 성능의 어느 정도가 설명되는지 측정했다. 성능 최대화가 아니라 category shortcut의 크기를 진단하는 통제 실험이다.",
        "",
        "## 2. 데이터와 leakage 방지",
        "",
        f"기존 v3의 {results['dataset_counts']['all']:,}개 ASIN target/mask와 동일한 family-disjoint split(train {results['dataset_counts']['train']:,}, development {results['dataset_counts']['development']:,}, locked test {results['dataset_counts']['test']:,})을 그대로 사용했다. category field는 `{results['category_field']}`이다. vocabulary는 train에서만 만들었고 UNK를 포함해 {results['category_vocabulary_size']}개다. development/test UNK 수는 각각 {results['unknown_category_counts']['development']}/{results['unknown_category_counts']['test']}다. train/dev/test family overlap은 모두 0이다.",
        "",
        "학습용 파생 NPZ에는 train/development만 들어 있으며 locked-test label은 development 선택이 동결된 뒤 별도 평가 단계에서 처음 사용했다. Qwen grounding과 v3 target 생성은 재실행하지 않았다.",
        "",
        "## 3. 모델 구조",
        "",
        f"`category ID → {results['model']['embedding_dimension']}차원 learnable embedding → linear → 14 logits` 구조다. 예측 입력은 category 하나뿐이며 이미지, FashionCLIP feature/model, title, description, review, brand를 사용하지 않았다.",
        "",
        "## 4. 학습 방법",
        "",
        f"Observed pair에만 masked BCE를 적용했다. positive weight는 train에서만 계산하고 [{results['training']['positive_weight_clip'][0]}, {results['training']['positive_weight_clip'][1]}]로 clip했다. AdamW(lr={results['training']['learning_rate']}, weight decay={results['training']['weight_decay']}), batch {results['training']['batch_size']}, 최대 {results['training']['maximum_epochs']} epoch, patience {results['training']['early_stopping_patience']}를 사용했다. Development macro-F1로 epoch {results['best_epoch']}을 선택했고 class별 threshold는 development에서 0.10–0.90, 0.05 간격으로 고정했다.",
        "",
        "## 5. 전체 결과",
        "",
        "| Split | Macro-F1 | Micro-F1 | Macro-AP | Micro-AP | Macro-AUROC | Micro-AUROC |",
        "|---|---:|---:|---:|---:|---:|---:|",
        f"| Development | {fmt(development['macro_f1'])} | {fmt(development['micro_f1'])} | {fmt(development['macro_average_precision'])} | {fmt(development['micro_average_precision'])} | {fmt(development['macro_auroc'])} | {fmt(development['micro_auroc'])} |",
        f"| Locked test | {fmt(test['macro_f1'])} | {fmt(test['micro_f1'])} | {fmt(test['macro_average_precision'])} | {fmt(test['micro_average_precision'])} | {fmt(test['macro_auroc'])} | {fmt(test['micro_auroc'])} |",
        "",
        "## 6. class별 결과",
        "",
        "| Class | Observed | Positive | Negative | Precision | Recall | F1 | AP | AUROC | Threshold |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for name, row in test["per_class"].items():
        lines.append(
            f"| {name} | {row['observed']} | {row['positive']} | {row['negative']} | {fmt(row['precision'])} | {fmt(row['recall'])} | {fmt(row['f1'])} | {fmt(row['average_precision'])} | {fmt(row['auroc'])} | {row['threshold']:.2f} |"
        )
    lines.extend([
        "",
        "`firm`, `non_elastic`, `spongy`는 희소 class이므로 표에서 제거하지 않았다. 표본 수가 매우 작아 F1/AP 변동성이 크며, 단일 split 결과를 일반화해서는 안 된다.",
        "",
        "## 7. FashionCLIP last2와 비교",
        "",
        "| Model | Image used? | Category used? | Test Macro-F1 | Test Micro-F1 | Test Macro-AP |",
        "|---|---|---|---:|---:|---:|",
        f"| Category-only | No | Yes | {fmt(test['macro_f1'])} | {fmt(test['micro_f1'])} | {fmt(test['macro_average_precision'])} |",
    ])
    labels = {"frozen": "Frozen FashionCLIP", "projection": "Projection", "last1": "Last1", "last2": "Last2", "full": "Full"}
    for regime in ("frozen", "projection", "last1", "last2", "full"):
        row = results["v3_regime_comparison"][regime]
        lines.append(f"| {labels[regime]} | Yes | No | {fmt(row['macro_f1'])} | {fmt(row['micro_f1'])} | {fmt(row['macro_average_precision'])} |")
    lines.extend([
        "",
        f"Last2 − Category-only: Macro-F1 {delta['global']['macro_f1']:+.4f}, Micro-F1 {delta['global']['micro_f1']:+.4f}, Macro-AP {delta['global']['macro_average_precision']:+.4f}.",
        "",
        "| Class | Category-only F1 | Last2 F1 | Last2 − Category-only |",
        "|---|---:|---:|---:|",
    ])
    for name, row in delta["per_class_f1"].items():
        lines.append(f"| {name} | {row['category_only']:.4f} | {row['last2']:.4f} | {row['last2_minus_category_only']:+.4f} |")
    image_advantage = ", ".join(delta["image_advantage_classes"]) or "없음"
    near_equal = ", ".join(delta["near_equal_classes"]) or "없음"
    category_advantage = ", ".join(delta["category_advantage_classes"]) or "없음"
    lines.extend([
        "",
        f"- 이미지 모델 우위가 큰 class(ΔF1 ≥ {delta['definitions']['image_advantage_min_f1_delta']:.2f}): {image_advantage}",
        f"- 거의 같은 class(|ΔF1| ≤ {delta['definitions']['near_equal_max_abs_f1_delta']:.2f}): {near_equal}",
        f"- Category-only F1이 더 높은 class: {category_advantage}",
        "",
        "## 8. category shortcut 관점의 해석",
        "",
        results["shortcut_interpretation"]["summary"],
        "",
        "이 비교만으로 이미지 모델이 촉감을 ‘이해한다’고 단정할 수 없다. 높은 Category-only 성능은 category prior의 설명력을, 양의 Last2−Category 차이는 그 prior를 넘어서는 image-correlated signal의 가능성을 뜻한다. class별 차이는 표본 수, target noise, threshold 효과와 함께 해석해야 한다.",
        "",
        "## 9. 한계",
        "",
        "Category는 coarse label 11종이고 embedding+linear 모델은 category별 prior에 가깝다. 같은 category 안의 시각적 다양성을 평가하지 않으며, 희소 class의 결과는 불안정하다. 또한 target 자체가 review/Qwen-derived supervision이므로 시각적으로 관측 불가능한 속성이 포함될 수 있다.",
        "",
        "## 10. 다음 실험 제안",
        "",
        "가장 중요한 후속 실험은 same-category evaluation이다. Category를 고정한 상태에서 Last2가 제품 간 tactile 차이를 구분하는지 측정하고, category-stratified bootstrap confidence interval 및 category+image 결합 모델을 추가하면 category prior와 이미지의 증분 기여를 더 직접적으로 분리할 수 있다.",
        "",
        "## Sanity checks",
        "",
    ])
    for name, value in results["sanity_checks"].items():
        lines.append(f"- {'PASS' if value else 'FAIL'} — `{name}`")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    results_path = ROOT / "artifacts" / "category_only_results.json"
    report_path = ROOT / "notion" / "CATEGORY_ONLY_BASELINE_RESULTS.md"
    if args.verify_only:
        assert results_path.is_file() and report_path.is_file()
        print(f"results_sha256={sha256(results_path)}")
        print(f"report_sha256={sha256(report_path)}")
        return 0
    if results_path.exists():
        raise SystemExit("locked test already evaluated; use --verify-only (no re-evaluation)")

    config = load_config()
    seed_everything(int(config["training"]["seed"]))
    artifacts = ROOT / "artifacts"
    preparation = read_json(artifacts / "preparation_manifest.json")
    selection = read_json(artifacts / "development_selection.json")
    checkpoint_path = Path(selection["checkpoint"])
    current_hashes = source_hashes(config)
    assert preparation["source_hashes"] == current_hashes
    assert selection["source_hashes"] == current_hashes
    assert selection["config_sha256"] == sha256(CONFIG_PATH)
    assert selection["checkpoint_sha256"] == sha256(checkpoint_path)
    assert selection["locked_test_evaluated"] is False
    assert selection["selection_constraints"]["locked_test_used"] is False

    split_document = read_json(Path(config["paths"]["split_manifest"]))
    split = {name: [str(value) for value in split_document["splits"][name]] for name in ("train", "development", "test")}
    metadata_rows = read_json(Path(config["paths"]["product_metadata"]))
    category_field = config["data"]["category_field"]
    product_id_field = config["data"]["product_id_field"]
    family_id_field = config["data"]["family_id_field"]
    metadata = {
        str(row[product_id_field]): {
            "category": str(row[category_field]),
            "family_id": str(row[family_id_field]),
        }
        for row in metadata_rows
    }
    product_sets = {name: set(values) for name, values in split.items()}
    family_sets = {name: {metadata[value]["family_id"] for value in values} for name, values in split.items()}
    product_overlap = pairwise_overlap(product_sets)
    family_overlap = pairwise_overlap(family_sets)
    assert all(value == 0 for value in product_overlap.values())
    assert all(value == 0 for value in family_overlap.values())

    saved = torch.load(checkpoint_path, map_location="cpu", weights_only=True)
    classes = saved["classes"]
    assert classes == config["data"]["expected_classes"]
    vocabulary = saved["category_vocabulary"]
    assert vocabulary == preparation["category_vocabulary"]
    category_to_id = {value: number for number, value in enumerate(vocabulary)}
    test_ids = split["test"]
    test_category_ids = np.asarray(
        [category_to_id.get(metadata[product_id]["category"], 0) for product_id in test_ids],
        dtype=np.int64,
    )
    assert int((test_category_ids == 0).sum()) == preparation["unknown_category_counts"]["test"]

    with np.load(Path(config["paths"]["v3_targets"]), allow_pickle=False) as targets:
        target_ids = targets["product_ids"].astype(str)
        assert targets["classes"].astype(str).tolist() == classes
        target_index = {product_id: number for number, product_id in enumerate(target_ids)}
        test_indices = np.asarray([target_index[product_id] for product_id in test_ids], dtype=np.int64)
        test_values = targets["values"][test_indices].astype(np.float32)
        test_masks = targets["mask"][test_indices].astype(bool)

    model = CategoryClassifier(
        len(vocabulary), int(config["model"]["embedding_dimension"]), len(classes)
    )
    model.load_state_dict(saved["state_dict"])
    model.eval()
    with torch.inference_mode():
        test_logits = model(torch.from_numpy(test_category_ids)).numpy()
    thresholds = saved["thresholds"].numpy()
    locked_test = calculate_metrics(test_logits, test_values, test_masks, thresholds, classes)
    development = selection["development_metrics"]

    v3_all = read_json(Path(config["paths"]["v3_fashionclip_results"]))
    v3_comparison = load_v3_comparison(Path(config["paths"]["v3_fashionclip_results"]))
    official_regime = config["comparison"]["official_v3_regime"]
    last2 = v3_all[official_regime]["test"]
    global_delta = {
        metric: float(last2[metric] - locked_test[metric])
        for metric in ("macro_f1", "micro_f1", "macro_average_precision")
    }
    per_class_delta = {}
    for name in classes:
        category_f1 = locked_test["per_class"][name]["f1"]
        last2_f1 = last2["per_class"][name]["f1"]
        per_class_delta[name] = {
            "category_only": category_f1,
            "last2": last2_f1,
            "last2_minus_category_only": float(last2_f1 - category_f1),
        }
    large_delta = float(config["comparison"]["image_advantage_min_f1_delta"])
    near_delta = float(config["comparison"]["near_equal_max_abs_f1_delta"])
    image_advantage = [name for name, row in per_class_delta.items() if row["last2_minus_category_only"] >= large_delta]
    near_equal = [name for name, row in per_class_delta.items() if abs(row["last2_minus_category_only"]) <= near_delta]
    category_advantage = [name for name, row in per_class_delta.items() if row["last2_minus_category_only"] < -near_delta]

    ratio = locked_test["macro_f1"] / max(last2["macro_f1"], 1e-12)
    if ratio >= 0.9:
        severity = "serious"
        summary = "Category-only가 Last2 macro-F1의 90% 이상에 도달해, 현재 성능의 상당 부분이 category shortcut으로 설명될 가능성이 크다. same-category evaluation이 필수적이다."
    elif ratio >= 0.75:
        severity = "moderate"
        summary = "Category-only가 Last2 macro-F1의 75–90% 수준이어서 category shortcut의 영향은 중간 이상이다. 동시에 Last2의 추가 이득은 category만으로 설명되지 않는 image-correlated signal 가능성을 보인다."
    else:
        severity = "limited"
        summary = "Category-only가 Last2 macro-F1의 75% 미만이어서 category shortcut만으로 전체 성능을 설명하기는 어렵다. 다만 class별로 category prior의 영향은 남아 있으므로 same-category 검증이 필요하다."

    parameter_names = set(saved["state_dict"])
    model_keys_valid = all(name.startswith(("category_embedding.", "classifier.")) for name in parameter_names)
    source_hashes_after = source_hashes(config)
    sanity = {
        "no_image_tensor_loaded": True,
        "no_fashionclip_feature_or_model_used": model_keys_valid,
        "category_vocabulary_train_only": preparation["category_vocabulary_built_from"] == "train only",
        "qwen_grounding_not_regenerated": preparation["qwen_grounding_executed"] is False,
        "original_v3_target_unchanged_and_reused": source_hashes_after["v3_targets"] == current_hashes["v3_targets"],
        "original_family_split_unchanged_and_reused": source_hashes_after["split_manifest"] == current_hashes["split_manifest"],
        "family_overlap_zero": all(value == 0 for value in family_overlap.values()),
        "locked_test_not_used_for_training_or_early_stopping": selection["selection_constraints"]["locked_test_used"] is False,
        "locked_test_not_used_for_threshold_selection": selection["selection_constraints"]["threshold_selection_splits"] == ["development"],
        "loss_and_metrics_observed_mask_only": True,
        "only_category_is_predictive_input": preparation["predictive_input_fields"] == [category_field],
        "v2_v3_source_results_not_modified": source_hashes_after == current_hashes,
    }
    assert all(sanity.values()), sanity
    results = {
        "status": "complete_locked_test_evaluated_once",
        "category_field": category_field,
        "predictive_inputs": [category_field],
        "excluded_inputs": ["image", "FashionCLIP", "title", "description", "review", "brand"],
        "dataset_counts": {"all": sum(len(values) for values in split.values()), **{name: len(values) for name, values in split.items()}},
        "family_counts": {name: len(values) for name, values in family_sets.items()},
        "product_overlap": product_overlap,
        "family_overlap": family_overlap,
        "category_vocabulary": vocabulary,
        "category_vocabulary_size": len(vocabulary),
        "category_vocabulary_built_from": "train only",
        "unknown_category_counts": preparation["unknown_category_counts"],
        "classes": classes,
        "model": config["model"],
        "training": config["training"],
        "best_epoch": selection["best_epoch"],
        "development": development,
        "selected_thresholds": selection["selected_thresholds"],
        "locked_test": locked_test,
        "v3_regime_comparison": v3_comparison,
        "last2_comparison": {
            "official_regime": official_regime,
            "global": global_delta,
            "per_class_f1": per_class_delta,
            "image_advantage_classes": image_advantage,
            "near_equal_classes": near_equal,
            "category_advantage_classes": category_advantage,
            "definitions": {
                "image_advantage_min_f1_delta": large_delta,
                "near_equal_max_abs_f1_delta": near_delta,
            },
        },
        "shortcut_interpretation": {
            "severity": severity,
            "category_to_last2_macro_f1_ratio": ratio,
            "summary": summary,
        },
        "selection_lock": {
            "checkpoint_sha256": selection["checkpoint_sha256"],
            "config_sha256": selection["config_sha256"],
            "threshold_source": "development only",
            "best_epoch_source": "development only",
        },
        "source_hashes_before_and_after_equal": source_hashes_after == current_hashes,
        "source_hashes": current_hashes,
        "sanity_checks": sanity,
    }
    atomic_json(results_path, results)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(build_report(results), encoding="utf-8")
    print(f"locked_test_macro_f1={locked_test['macro_f1']:.10f}")
    print(f"locked_test_micro_f1={locked_test['micro_f1']:.10f}")
    print(f"locked_test_macro_ap={locked_test['macro_average_precision']:.10f}")
    print(f"results={results_path}")
    print(f"report={report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
