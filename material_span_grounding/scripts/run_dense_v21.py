#!/usr/bin/env python3
"""Run the Codex-audit-informed dense-500 v2.1 development rerun with vLLM."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from material_span.ai_audit_regression import build_fixture, evaluate_fixture
from material_span.common import ROOT, read_jsonl, save_json
from material_span.vllm_pipeline import (
    LENSES,
    ProgressNotifier,
    VLLMRunner,
    run_recall_extraction,
    run_verification,
)


DENSE_INPUT = ROOT / "data" / "dense" / "reviews_product_dense.jsonl"
AUDIT_ROOT = ROOT / "audit_app" / "data" / "vllm_dense_500_200_codex_combined"
FIXTURE_ROOT = ROOT / "data" / "regression" / "codex_ai_audit_v2_1"
FIXTURE_PATH = FIXTURE_ROOT / "fixture.json"
REGRESSION_INPUT = FIXTURE_ROOT / "reviews_68.jsonl"
REGRESSION_ROOT = ROOT / "data" / "vllm" / "dense_500" / "v2_1_regression_r3"
FULL_ROOT = ROOT / "data" / "vllm" / "dense_500" / "v2_1_ai_recall"
RESULT_ROOT = ROOT / "experiments" / "12_dense_500_v2_1_ai_recall"
OLD_ROOT = ROOT / "data" / "vllm" / "dense_500" / "v2"


def prepare_fixture() -> dict[str, Any]:
    return build_fixture(
        AUDIT_ROOT / "human_semantic_audit_live.csv",
        AUDIT_ROOT / "human_missing_spans_live.csv",
        DENSE_INPUT,
        FIXTURE_PATH,
        REGRESSION_INPUT,
    )


def run_dataset(
    runner: VLLMRunner,
    input_path: Path,
    output_root: Path,
    extraction_progress,
    verification_progress,
) -> dict[str, Any]:
    v1_rows = read_jsonl(
        ROOT / "data" / "vllm" / "pilot" / "v1" / "span_extractions.jsonl"
    )
    extracted = run_recall_extraction(
        runner, input_path, output_root, v1_rows, extraction_progress
    )
    verified = run_verification(runner, output_root, verification_progress)
    return {"reviews": len(extracted), "verified": len(verified)}


def evaluate_and_save(
    fixture: dict[str, Any], output_root: Path, name: str
) -> dict[str, Any]:
    metrics = evaluate_fixture(
        fixture,
        output_root / "span_extractions.jsonl",
        output_root / "semantic_verifications.jsonl",
    )
    destination = RESULT_ROOT / name
    save_json(destination / "regression_metrics.json", metrics)
    return metrics


def rate(numerator: int, denominator: int) -> str:
    return "—" if not denominator else f"{numerator / denominator:.1%}"


def build_report(regression: dict[str, Any], full: dict[str, Any]) -> Path:
    old_extract = read_jsonl(OLD_ROOT / "span_extractions.jsonl")
    old_verify = read_jsonl(OLD_ROOT / "semantic_verifications.jsonl")
    new_extract = read_jsonl(FULL_ROOT / "span_extractions.jsonl")
    new_verify = read_jsonl(FULL_ROOT / "semantic_verifications.jsonl")
    new_run = json.loads(
        (FULL_ROOT / "verification_run.json").read_text(encoding="utf-8")
    )
    old_schema_success = sum(row.get("status") == "success" for row in old_verify)
    new_schema_success = sum(row.get("status") == "success" for row in new_verify)
    old_accepted = sum(
        row.get("status") == "success" and row.get("accepted") is True
        for row in old_verify
    )
    new_accepted = sum(
        row.get("status") == "success" and row.get("accepted") is True
        for row in new_verify
    )
    old_spans = sum(len(row.get("evidence", [])) for row in old_extract)
    new_spans = sum(len(row.get("evidence", [])) for row in new_extract)
    missing = full["missing_span_regression"]
    positives = full["all_codex_positive_extraction"]
    decisions = full["candidate_decision_regression"]
    regression_missing = regression["missing_span_regression"]
    report = f"""# Dense-500 Recall v2.1 재추출·재검증 결과

> 실행일: 2026-08-13  
> 백엔드: vLLM 0.27.1 / Qwen3-VL-8B-Instruct / BNB 4-bit  
> 개발 근거: Codex AI 자체 검수 200 span + missing span 24건  
> **이 회귀 세트는 사람 gold가 아니며 prompt 개발에 사용됐으므로 독립 평가가 아니다.**

## 결과 요약

| 항목 | v2.0 | v2.1 |
|---|---:|---:|
| 전체 리뷰 | {len(old_extract):,} | {len(new_extract):,} |
| exact span | {old_spans:,} | {new_spans:,} |
| semantic schema 성공 | {old_schema_success:,}/{len(old_verify):,} | {new_schema_success:,}/{len(new_verify):,} |
| semantic accepted | {old_accepted:,} | {new_accepted:,} |
| semantic rejected | {len(old_verify) - old_accepted:,} | {len(new_verify) - new_accepted:,} |

v2.1 최초 검증에서 1건의 `span_id` 복사 오류가 발생했으며, 정확한 identifier 복사를
강조한 targeted vLLM retry {new_run.get('targeted_retries', 0)}건으로 복구했다. 최종
verification SHA-256은 `{new_run['output_sha256']}`다.

## 68-review 개발 회귀 결과

| 지표 | 보강 후 소규모 점검 | 전체 재실행에서 동일 68리뷰 |
|---|---:|---:|
| 기존 missing 24건 exact 재추출 | {regression_missing['exact_extracted']} / 24 | {missing['exact_extracted']} / 24 |
| 기존 missing 24건 containment coverage | {regression_missing['containment_covered']} / 24 | {missing['containment_covered']} / 24 |
| coverage 후 verifier accepted | {regression_missing['covered_and_accepted']} / 24 | {missing['covered_and_accepted']} / 24 |

- Codex 승인 전체 138개 추출 coverage: {positives['containment_covered']} / {positives['total']}
  ({rate(positives['containment_covered'], positives['total'])})
- 기존 200개 후보 중 v2.1에도 exact 존재: {decisions['available']} / 200
- 존재하는 후보의 Codex 판정 일치: {decisions['matches']} / {decisions['available']}
  ({rate(decisions['matches'], decisions['available'])})
- 과거 오판 18개 중 v2.1에서 판정 교정: {decisions['changed_cases_fixed']} /
  {decisions['changed_cases_available']} available

## 해석

이 수치는 누락을 발견하고 prompt를 수정하는 데 사용한 같은 68개 리뷰에서 계산한 개발
회귀 성능이다. 따라서 개선 여부를 확인하는 용도이며 독립적인 일반화 성능으로 보고하지
않는다. 다음 M0/M1 입력은 v2.1 전체 결과로 다시 구성하되, 최종 외부 보고 전에는 별도의
미사용 리뷰 표본을 사람 또는 독립 검수 프로토콜로 확인해야 한다.

## 산출물

- 전체 결과: `data/vllm/dense_500/v2_1_ai_recall/`
- 회귀 fixture: `data/regression/codex_ai_audit_v2_1/fixture.json`
- 소규모 회귀 지표:
  `experiments/12_dense_500_v2_1_ai_recall/regression/regression_metrics.json`
- 전체 재실행 회귀 지표:
  `experiments/12_dense_500_v2_1_ai_recall/full/regression_metrics.json`
"""
    report_path = ROOT / "notion" / "14_DENSE_500_RECALL_V2_1_RESULTS.md"
    report_path.write_text(report, encoding="utf-8")
    (RESULT_ROOT / "report.md").parent.mkdir(parents=True, exist_ok=True)
    (RESULT_ROOT / "report.md").write_text(report, encoding="utf-8")
    return report_path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--phase", choices=["regression", "full"], required=True
    )
    args = parser.parse_args()
    fixture = prepare_fixture()
    notifier = ProgressNotifier(
        (REGRESSION_ROOT if args.phase == "regression" else FULL_ROOT)
        / "progress.json"
    )
    try:
        runner = VLLMRunner()
        if args.phase == "regression":
            total_tasks = len(read_jsonl(REGRESSION_INPUT)) * len(LENSES)
            run_dataset(
                runner,
                REGRESSION_INPUT,
                REGRESSION_ROOT,
                lambda done, total: notifier.update(
                    70 * done / max(total_tasks, 1),
                    f"v2.1 68-review 추출 {done:,}/{total:,}",
                ),
                lambda done, total: notifier.update(
                    70 + 30 * done / max(total, 1),
                    f"v2.1 68-review 의미 검증 {done:,}/{total:,}",
                ),
            )
            metrics = evaluate_and_save(fixture, REGRESSION_ROOT, "regression")
            notifier.update(100, "v2.1 68-review 개발 회귀 점검 완료")
            print(json.dumps(metrics, ensure_ascii=False, indent=2))
            return

        regression_metrics_path = RESULT_ROOT / "regression" / "regression_metrics.json"
        if not regression_metrics_path.is_file():
            raise RuntimeError("Run --phase regression successfully before --phase full")
        regression = json.loads(regression_metrics_path.read_text(encoding="utf-8"))
        total_tasks = len(read_jsonl(DENSE_INPUT)) * len(LENSES)
        run_dataset(
            runner,
            DENSE_INPUT,
            FULL_ROOT,
            lambda done, total: notifier.update(
                70 * done / max(total_tasks, 1),
                f"v2.1 dense-500 추출 {done:,}/{total:,}",
            ),
            lambda done, total: notifier.update(
                70 + 30 * done / max(total, 1),
                f"v2.1 dense-500 의미 검증 {done:,}/{total:,}",
            ),
        )
        full = evaluate_and_save(fixture, FULL_ROOT, "full")
        report_path = build_report(regression, full)
        notifier.update(100, f"v2.1 dense-500 보고서 완료: {report_path.relative_to(ROOT)}")
        print(json.dumps(full, ensure_ascii=False, indent=2))
    except BaseException as exc:
        notifier.failure(f"Dense-500 v2.1 {args.phase} 실패: {type(exc).__name__}: {exc}")
        raise


if __name__ == "__main__":
    main()
