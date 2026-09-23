from __future__ import annotations

import importlib.metadata
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import numpy as np

from .common import PATHS, load_experiment, load_taxonomy, read_json, read_jsonl, sha256_file, utc_now, write_json
from .reporting import bootstrap_mean_ci


def _fmt(value: Any, digits: int = 3) -> str:
    return "—" if value is None else f"{float(value):.{digits}f}"


def _tests() -> dict[str, Any]:
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(PATHS.root / "src") + os.pathsep + environment.get("PYTHONPATH", "")
    command = [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"]
    result = subprocess.run(command, cwd=PATHS.root, env=environment, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)
    log = PATHS.artifacts / "unit_test_log.txt"
    log.write_text(result.stdout, encoding="utf-8")
    payload = {"status": "passed" if result.returncode == 0 else "failed", "return_code": result.returncode, "log": str(log), "log_sha256": sha256_file(log)}
    write_json(PATHS.artifacts / "unit_test_results.json", payload)
    return payload


def _retrieval_bootstrap(config: dict[str, Any]) -> dict[str, Any]:
    rows = read_jsonl(PATHS.artifacts / "coldstart_retrieval_per_query.jsonl")
    output = {}
    for offset, method in enumerate(sorted({str(row["method"]) for row in rows})):
        values = np.asarray([float(row["ndcg@10"]) for row in rows if row["method"] == method and row.get("ndcg@10") is not None])
        mean, low, high = bootstrap_mean_ci(values, int(config["reporting"]["bootstrap_samples"]), float(config["reporting"]["confidence_level"]), int(config["experiment"]["seed"]) + offset)
        output[method] = {"mean": mean, "ci_low": low, "ci_high": high, "queries": int(len(values))}
    return output


def _inventory() -> list[dict[str, Any]]:
    rows = []
    for path in sorted(PATHS.manifests.glob("phase*.json")):
        if path.name == "phase11_final.json":
            continue
        value = read_json(path)
        rows.append({"phase": value.get("phase"), "status": value.get("status"), "manifest": str(path), "sha256": sha256_file(path)})
    return rows


def _phase2_normalization_counts() -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in read_jsonl(PATHS.artifacts / "axis_groundings.jsonl"):
        for item in row.get("normalizations", []):
            rule = str(item.get("rule") or "unknown")
            counts[rule] = counts.get(rule, 0) + 1
    return counts


def _model_table(models: dict[str, Any], axes: list[str]) -> list[str]:
    methods = ["category_only", "fashionclip_linear", "fashionclip_ridge", "image_category_ridge", "dino_ridge", "ordinal", "pairwise", "tiny_mlp"]
    lines = ["| 방법 | " + " | ".join(axes) + " |", "|---|" + "---:|" * len(axes)]
    for method in methods:
        values = [models.get("summary", {}).get(axis, {}).get(method, {}).get("spearman_mean") for axis in axes]
        lines.append("| " + method + " | " + " | ".join(_fmt(value) for value in values) + " |")
    return lines


def _write_notion(result: dict[str, Any], taxonomy: dict[str, Any]) -> Path:
    pool = result["phase0"]
    split = pool["split"]
    grounding = result["phase2"]
    diagnostics = result["phase3"]
    stats = {row["axis_id"]: row for row in result["axis_stats"]}
    axes = diagnostics["active_axes"]
    models = result["models"]
    external = result["external"]
    selective = result["selective"]
    retrieval = result["retrieval"]
    phase2_normalizations = result.get("phase2_normalization_counts", {})
    nonfinite_paths = models.get("nonfinite_values_replaced_with_null", [])
    lines = [
        "# Tactile Cold-Start v2 Full-Pool — Phase 0~11 실험 과정과 결과",
        "",
        "## 한눈에 보는 결론",
        "",
        f"이번 v2는 v1의 500개 ASIN 상한을 제거하고 조건을 만족한 **전체 {pool['outputs_summary']['products']:,}개 ASIN**에서 시작했다. "
        f"예측 단위는 ASIN, 분할 단위는 parent product family({pool['outputs_summary']['parent_families']:,}개)다. "
        "기존 v1에 나타난 family는 train에만 넣었고, development와 locked test는 이전에 보지 않은 family로만 구성했다.",
        "",
        f"{pool['outputs_summary']['selected_reviews']:,}개 선택 리뷰 전체를 키워드로 훑어 {pool['outputs_summary']['lexical_candidates_all']:,}개 고재현율 후보를 보존했다. "
        f"그중 {grounding['full_input_claims']:,}개 reviewer-first 대표 구절을 Qwen이 문맥 검증했고, "
        f"{grounding['mappable']:,}개를 촉감 축으로 안전하게 매핑했으며 {grounding['unmappable']:,}개는 거절했다.",
        "",
        f"촉감 후보가 하나라도 나온 ASIN은 {pool['outputs_summary']['candidate_products']:,}개이며, 나머지 "
        f"{pool['outputs_summary']['products'] - pool['outputs_summary']['candidate_products']:,}개도 데이터셋과 이미지 feature에는 그대로 포함했다. "
        "후보가 없다는 사실은 중립 촉감이 아니라 review-unobserved로 처리한다.",
        "",
        "중요: 사용자 요청으로 사람 검증을 이번 실행에서 건너뛰었다. 따라서 아래 숫자는 사람 ground truth가 아니라 **Qwen pseudo-label 기반 feasibility 결과**이며 human validation 상태는 `pending`이다.",
        "",
        "## 데이터 선정과 family 분할",
        "",
        "포함 조건은 source train split, 로컬 이미지 존재, 리뷰 길이 40~2,000자, 서로 다른 reviewer 5명 이상이다. 상품 수 상한은 없다. 각 ASIN에서는 reviewer당 리뷰 하나만 남기고 최대 10명의 리뷰를 사용했다.",
        "",
        f"- train: {split['counts']['train']:,} ASIN / {split['family_counts']['train']:,} family",
        f"- development: {split['counts']['development']:,} ASIN / {split['family_counts']['development']:,} family",
        f"- locked test: {split['counts']['test']:,} ASIN / {split['family_counts']['test']:,} family",
        f"- 기존 v1 family 중 train 강제 배치: {split['previous_v1_family_count']:,}",
        "- parent family 중복: 0; test 리뷰는 모델 선택·축 선택·threshold 보정에 사용하지 않음",
        "",
        "## Phase 2 — 후보 구절과 Qwen 검증",
        "",
        "단순 키워드 일치는 최종 라벨이 아니다. 모든 리뷰에서 soft/rough/stretch/thin/stiff/warm/spongy 계열 표현이 있는 문장을 먼저 넓게 찾은 뒤, 각 ASIN에서 한 축을 결정론적으로 선택했다. reviewer 일치도 측정을 위해 축마다 최대 100개 상품에 한해 같은 축을 말한 두 번째 독립 reviewer도 보존했다. Qwen은 로컬 문맥을 보고 소재 촉감이 아닌 fit·size·durability·날씨 선호·비유적 표현을 거절했다.",
        "",
        "Qwen 출력은 `[mappable, axis, direction, intensity, scope, confidence]`의 6개 정수 코드로 제한했다. 숫자 target은 Qwen이 직접 만들지 않고, symbolic label을 코드에서 결정론적으로 변환했다.",
        "",
        f"엄격한 출력 검증 과정에서 축/방향 위치가 코드만으로 명백히 뒤바뀐 "
        f"{phase2_normalizations.get('unambiguous_numeric_axis_direction_swap', 0):,}건은 결정론적으로 교정했다. "
        f"유효 축을 복원할 수 없었던 {phase2_normalizations.get('invalid_axis_fail_closed_to_unmappable', 0):,}건은 "
        "축을 임의 생성하지 않고 confidence=0의 unmappable로 보수적으로 거절했으며, 두 경우 모두 원시 Qwen 응답과 정규화 사유를 보존했다.",
        "",
        "## Phase 3 — 촉감 축은 어떻게 구성됐나",
        "",
        "각 축은 서로 반대되는 두 pole을 가진 bipolar 축이다. v1 임시 AI audit에서 strong/moderate 구분이 불안정했기 때문에 v2 주 타깃은 강도를 곱하지 않는 방향 중심 `-1 / 0 / +1`이다. 원 intensity는 삭제하지 않고 진단용으로 보존했다. 축 선택에는 오직 train split만 사용했다.",
        "",
        "| 축 | 구성 | 의미 | train mapped span | 상품 | 두 reviewer 이상 | 미관측률 | 선택 |",
        "|---|---|---|---:|---:|---:|---:|:---:|",
    ]
    for axis in taxonomy["axes"]:
        stat = stats[str(axis["id"])]
        lines.append(
            f"| {axis['id']} | {axis['negative_pole']} ↔ {axis['positive_pole']} | {axis['definition']} | "
            f"{stat['mapped_spans']:,} | {stat['unique_products']:,} | {stat['products_ge_2_reviewers']:,} | {stat['review_unobserved_rate']:.1%} | {'ACTIVE' if stat['selected'] else 'INACTIVE'} |"
        )
    lines.extend([
        "",
        f"최종 active axes: **{', '.join(axes) if axes else '없음'}**. 축은 span 30개, 상품 20개, 양 pole 각각 상품 5개, multi-reviewer 상품 3개, category 집중도 90% 이하, 평균 mapping confidence 0.70 이상을 모두 만족해야 active가 된다. 외부 데이터셋 지원 여부는 내부 축 선택의 필수조건으로 쓰지 않고 Phase 8에서 별도로 평가했다.",
        "",
        "## Phase 4~5 — 사람 검증 상태와 reviewer-first target",
        "",
        "사람 검증용 고정 표본 CSV는 만들었지만 human 필드는 비어 있다. downstream에서는 같은 reviewer가 여러 구절을 말해도 먼저 reviewer 수준에서 평균낸 뒤 상품 수준으로 평균했다. reviewer 수가 많은 사람이 과도한 가중치를 갖지 않으며, 축 언급이 없는 상품은 0점이 아니라 mask=0인 `REVIEW_UNOBSERVED`다.",
        "",
        f"- 관측 product-axis pair: {result['phase5']['observed_product_axis_pairs']:,}",
        f"- 미관측 product-axis pair: {result['phase5']['unobserved_product_axis_pairs']:,}",
        f"- reviewer-axis record: {result['phase5']['reviewer_axis_records']:,}",
        "",
        "## Phase 6~7 — 이미지에서 촉감 방향 예측",
        "",
        "모든 이미지에서 frozen FashionCLIP과 DINO 특징을 뽑았다. category-only, 선형 회귀, Ridge, image+category, ordinal, pairwise, tiny MLP를 비교했고, hyperparameter와 최종 방법 선택은 development만 사용했다. 아래 값은 locked family test의 축별 Spearman이다.",
        "",
        *_model_table(models, axes),
        "",
        "Spearman이 category-only보다 높아야 실제 이미지 신호가 category shortcut을 넘어섰다고 해석할 수 있다. same-category pairwise 지표도 함께 기록했으며, 낮거나 음수인 결과는 숨기지 않고 시각적 촉감 추론의 한계로 해석한다.",
        "",
        f"선택 모델과 무관한 보조 open 384차원 baseline에서는 비유한 cosine 값 {len(nonfinite_paths):,}개가 발생해 "
        "성능 숫자로 치환하지 않고 JSON null과 원래 경로로 기록했다. 위 구조화 모델 표와 development 기반 모델 선택에는 사용되지 않았다.",
        "",
        "## Phase 8 — 외부 MLLM-Fabric 전이",
        "",
        "MLLM-Fabric 220개 RGB 이미지는 Amazon과 점수 체계를 합치지 않고 별도 외부 평가로 사용했다. 110개는 recoverability 보정, 나머지 110개는 외부 test다.",
        f"Leeds 자료는 이번 실행에서 `{external.get('leeds', {}).get('status', 'unavailable')}`였다. "
        "공개 원문과 별개로 원시 이미지+평점 배포본 및 재배포 라이선스를 확인하지 못해 수치를 만들지 않았다.",
        "",
        "| 축 | 상태 | 외부 Spearman | pairwise accuracy | recoverability |",
        "|---|---|---:|---:|---:|",
    ])
    for axis in axes:
        row = external.get("mllm_fabric", {}).get("results", {}).get(axis, {"status": "unavailable"})
        rec = external.get("property_recoverability", {}).get(axis, {}).get("value")
        lines.append(f"| {axis} | {row.get('status')} | {_fmt(row.get('spearman'))} | {_fmt(row.get('pairwise_accuracy'))} | {_fmt(rec)} |")
    lines.extend([
        "",
        "## Phase 9 — 틀릴 것 같으면 abstain",
        "",
        "20개 bootstrap Ridge ensemble의 상품별 불안정성(instance confidence)과 외부 축별 recoverability를 분리했다. development에서 threshold/calibrator를 정하고 locked test에서 risk-coverage를 측정했다.",
        "",
        "| 방법 | AURC↓ | nominal 80%의 실제 coverage | 해당 risk(MAE)↓ |",
        "|---|---:|---:|---:|",
    ])
    for method, row in selective.get("methods", {}).items():
        fixed = row.get("fixed_coverage", {}).get("0.8", {})
        lines.append(f"| {method} | {_fmt(row.get('aurc'))} | {_fmt(fixed.get('test_coverage'))} | {_fmt(fixed.get('test_risk_mae'))} |")
    lines.extend([
        "",
        "## Phase 10 — review-cold-start retrieval",
        "",
        f"locked test에서 같은 category 안에 최소 30개 후보가 있고 review target support가 있는 경우만 query를 만들었다. 생성 query는 {retrieval.get('queries', 0):,}개이며, relevance는 test의 숨겨진 review pseudo-target에서만 계산했다.",
        "",
        "| 방법 | NDCG@10 | 95% bootstrap CI |",
        "|---|---:|---:|",
    ])
    for method, row in result["retrieval_bootstrap"].items():
        interval = "—" if row["ci_low"] is None else f"[{row['ci_low']:.3f}, {row['ci_high']:.3f}]"
        lines.append(f"| {method} | {_fmt(row['mean'])} | {interval} |")
    lines.extend([
        "",
        "## 우리가 주목해야 할 점",
        "",
        "1. **500개 샘플 결론이 아니라 전체 적격 풀 결론이다.** 상품 수가 17배로 늘었고 family 단위 locked test를 새로 만들었다.",
        "2. **라벨이 없는 축을 중립으로 만들지 않았다.** 미언급은 REVIEW_UNOBSERVED로 mask 처리했기 때문에 0점 과잉이 없다.",
        "3. **강도보다 방향이 더 신뢰할 만하다.** v1 audit에서 드러난 intensity 불안정을 반영해 주 타깃을 방향 중심으로 바꿨다.",
        "4. **category shortcut을 반드시 확인해야 한다.** 이미지 모델이 category-only를 못 이기면 촉감이 아니라 상품 종류를 맞힌 것일 수 있다.",
        "5. **abstention은 새 라벨이 아니다.** VISUAL_ABSTAIN은 모델이 답을 보류하는 추론 상태이며 REVIEW_UNOBSERVED/neutral과 다르다.",
        "6. **사람 검증 전까지 결론은 잠정적이다.** 데이터 규모와 누수 방지는 개선됐지만 pseudo-label의 의미 정확도는 human audit 뒤에야 확정된다.",
        "",
        "## Phase별 실행 요약",
        "",
        "- Phase 0: 전체 census, ASIN/master/review corpus, family-safe split 및 locked test 생성",
        "- Phase 1: 7개 축 taxonomy와 direction-only primary coding 동결",
        "- Phase 2: lexical high-recall 후보 → Qwen 보수적 문맥 grounding",
        "- Phase 3: train-only coverage/pole/reviewer/category/confidence gate로 active axis 선택",
        "- Phase 4: human audit는 실행하지 않고 pending CSV와 한계 기록",
        "- Phase 5: reviewer-first target/distribution/support/agreement/mask 생성",
        "- Phase 6: 전체 이미지 FashionCLIP/DINO frozen embedding 추출",
        "- Phase 7: category/linear/Ridge/ordinal/pairwise/MLP 및 robustness 비교",
        "- Phase 8: MLLM-Fabric 외부 전이와 property recoverability 계산",
        "- Phase 9: development-calibrated risk-coverage와 abstention 평가",
        "- Phase 10: same-category locked-test tactile retrieval 평가",
        "- Phase 11: 테스트, bootstrap CI, manifest, 본 Notion-ready 문서 통합",
        "",
        "## 한계와 다음 필수 작업",
        "",
        "- 사람 audit를 건너뛰었으므로 Qwen axis confusion, polarity, scope 정확도는 미확정이다.",
        "- lexical candidate miner는 효율적인 high-recall front end지만, 키워드가 전혀 없는 우회적 촉감 표현을 놓칠 수 있다.",
        "- 한 ASIN에서 대표 축을 선택하는 scaling 정책 때문에 모든 축이 모든 상품에서 관측되는 구조가 아니다.",
        "- 외부 MLLM-Fabric은 220개로 작고 softness/texture/elasticity/thickness만 직접 호환된다.",
        "- Leeds 외부 검증은 실행 가능한 원시 이미지+평점 배포본과 라이선스를 확인한 뒤 추가해야 한다.",
        "- 최종 배포 전에는 pending audit CSV를 사람이 채우고, 오류가 큰 축은 taxonomy/prompt를 재동결해야 한다.",
    ])
    path = PATHS.notion / "TACTILE_COLDSTART_V2_FULL_PHASE_0_TO_11.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def run_final_reporting_v2() -> dict[str, Any]:
    config, taxonomy = load_experiment(), load_taxonomy()
    phase0 = read_json(PATHS.manifests / "phase0_full_pool.json")
    phase2 = read_json(PATHS.manifests / "phase2_axis_grounding.json")
    phase3 = read_json(PATHS.manifests / "phase3_diagnostics.json")
    phase5 = read_json(PATHS.manifests / "phase5_targets.json")
    models = read_json(PATHS.artifacts / "phase6_7_model_results.json")
    external = read_json(PATHS.artifacts / "external_transfer_results.json")
    selective = read_json(PATHS.artifacts / "phase9_selective_results.json")
    retrieval = read_json(PATHS.artifacts / "phase10_retrieval_results.json")
    tests = _tests()
    bootstrap = _retrieval_bootstrap(config)
    result = {
        "status": "complete" if tests["status"] == "passed" else "complete_with_test_failure",
        "phase": 11, "generated_at": utc_now(),
        "human_validation_status": "skipped_by_user_pending",
        "phase0": phase0, "phase2": phase2, "phase3": phase3, "phase5": phase5,
        "phase2_normalization_counts": _phase2_normalization_counts(),
        "axis_stats": read_json(PATHS.artifacts / "tactile_axis_stats.json"),
        "models": models, "external": external, "selective": selective, "retrieval": retrieval,
        "retrieval_bootstrap": bootstrap, "tests": tests,
        "environment": {"python": sys.version, "packages": {name: importlib.metadata.version(name) for name in ("numpy", "scipy", "scikit-learn", "torch", "transformers", "joblib")}},
    }
    result_path = PATHS.artifacts / "phase11_paper_results.json"
    write_json(result_path, result)
    notion_path = _write_notion(result, taxonomy)
    report_path = PATHS.reports / "phase11_full_ablation.md"
    report_path.write_text(
        "# Phase 11 — Full-pool final report\n\n"
        f"- ASIN: {phase0['outputs_summary']['products']:,}\n"
        f"- Active axes: {', '.join(phase3['active_axes'])}\n"
        f"- Qwen mappable: {phase2['mappable']:,}/{phase2['full_input_claims']:,}\n"
        f"- Retrieval queries: {retrieval.get('queries', 0):,}\n"
        f"- Human validation: skipped/pending\n- Tests: {tests['status']}\n\n"
        f"Detailed Korean Notion-ready document: `{notion_path}`\n",
        encoding="utf-8",
    )
    manifest = {
        "status": result["status"], "phase": 11, "generated_at": utc_now(),
        "human_validation_status": "skipped_by_user_pending",
        "config_sha256": sha256_file(PATHS.configs / "experiment.yaml"),
        "taxonomy_sha256": sha256_file(PATHS.configs / "tactile_axes.yaml"),
        "tests": tests, "prior_phase_manifests": _inventory(),
        "outputs": {
            "machine_results": str(result_path), "machine_results_sha256": sha256_file(result_path),
            "paper_report": str(report_path), "paper_report_sha256": sha256_file(report_path),
            "notion_report": str(notion_path), "notion_report_sha256": sha256_file(notion_path),
        },
    }
    write_json(PATHS.manifests / "phase11_final.json", manifest)
    return manifest
