#!/usr/bin/env python3
"""Merge the two Codex-adjudicated audit sets and write transparent results.

The output deliberately retains the historical ``human_*`` CSV column names
required by ``material_span.human_audit`` while identifying every annotator as
``codex_ai_adjudicator_not_human``.  It must not be presented as human gold.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

from material_span.common import ROOT
from material_span.human_audit import analyze_and_write


ANNOTATOR = "codex_ai_adjudicator_not_human"
SOURCE_DIRS = [
    ROOT / "audit_app" / "data" / "vllm_dense_500_200_a",
    ROOT / "audit_app" / "data" / "vllm_dense_500_200_b",
]
COMBINED_DIR = (
    ROOT / "audit_app" / "data" / "vllm_dense_500_200_codex_combined"
)
RESULT_DIR = (
    ROOT
    / "experiments"
    / "11_vllm_dense_500_human_audit"
    / "results"
    / "codex_ai_combined"
)
REPORT_PATH = ROOT / "notion" / "13_CODEX_AI_AUDIT_RESULTS.md"


def read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        return list(reader.fieldnames or []), list(reader)


def merge_csv(filename: str, unique_key: str) -> Path:
    fields: list[str] | None = None
    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    for source in SOURCE_DIRS:
        current_fields, current_rows = read_csv(source / filename)
        if fields is None:
            fields = current_fields
        elif current_fields != fields:
            raise RuntimeError(f"CSV schema mismatch for {filename}")
        for row in current_rows:
            key = row.get(unique_key, "").strip()
            if not key or key in seen:
                raise RuntimeError(f"Invalid/duplicate {unique_key}={key!r} in {filename}")
            if row.get("annotator_id", "").strip() != ANNOTATOR:
                raise RuntimeError(f"Non-Codex annotation found in {filename}: {key}")
            seen.add(key)
            rows.append(row)

    output = COMBINED_DIR / filename
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields or [])
        writer.writeheader()
        writer.writerows(rows)
    return output


def pct(value: float | None) -> str:
    return "—" if value is None else f"{value:.1%}"


def interval(values: list[float] | None) -> str:
    return "—" if values is None else f"{values[0]:.1%}–{values[1]:.1%}"


def write_notional_report(metrics: dict) -> None:
    sample = metrics["sample"]
    matrix = metrics["confusion_matrix"]
    decisions = metrics["decision_metrics"]
    agreements = metrics["field_agreement_on_mutual_accepts"]
    recall = metrics["recall_audit"]
    errors = metrics["error_analysis"]
    report = f"""# Dense-500 Codex AI 자체 검수 결과

> 완료일: 2026-08-13  
> 범위: vLLM dense-500 층화 표본 200 span, review-complete 68개 리뷰  
> 판정자: `{ANNOTATOR}`  
> **주의: 사람 검수가 아니며, 독립적인 human gold 또는 논문용 최종 평가로 보고할 수 없다.**

## 결론

Codex가 200개 후보를 전부 다시 읽고 68개 전체 리뷰에서 누락 span을 검사했다.
Qwen 판정 18개를 변경했고, 기존 추출에 없던 소재 근거 24개를 추가했다.

Qwen accepted precision과 rejected false-negative rate는 설정된 판정 gate를 충족했다.
그러나 review-complete 표본의 observed span recall은 {pct(recall['observed_span_recall'])}로,
누락 보완 없이 dense gold와 M0/M1 재평가로 바로 넘어가기에는 낮다.

## 검수 범위

| 항목 | 결과 |
|---|---:|
| 후보 판정 | {sample['labeled']} / {sample['expected']} |
| 전체 리뷰 확인 | {recall['checked_reviews']} / 68 |
| Qwen accepted / rejected 표본 | {sample['qwen_accepted_labeled']} / {sample['qwen_rejected_labeled']} |
| Codex accepted / rejected | {sample['human_accepted']} / {sample['human_rejected']} |
| 판정 변경 | {matrix['qwen_accept_human_reject'] + matrix['qwen_reject_human_accept']} |
| 추가한 missing span | {recall['missing_spans']} |

## 판정 지표

| 지표 | 값 | Wilson 95% CI | 개발 기준 |
|---|---:|---:|---:|
| Accepted precision | {pct(decisions['accepted_precision'])} | {interval(decisions['accepted_precision_wilson_95'])} | ≥ 90% |
| Rejected false-negative rate | {pct(decisions['rejected_false_negative_rate'])} | {interval(decisions['rejected_false_negative_rate_wilson_95'])} | ≤ 15% |
| Overall decision accuracy | {pct(decisions['overall_decision_accuracy'])} | {interval(decisions['overall_decision_accuracy_wilson_95'])} | 참고 |
| Scope agreement | {pct(agreements['scope']['rate'])} | {interval(agreements['scope']['wilson_95'])} | ≥ 90% |
| Property-status agreement | {pct(agreements['property_status']['rate'])} | {interval(agreements['property_status']['wilson_95'])} | ≥ 90% |
| Visual-observability agreement | {pct(agreements['visual_observability']['rate'])} | {interval(agreements['visual_observability']['wilson_95'])} | ≥ 80% |

Confusion matrix:

| | Codex accept | Codex reject |
|---|---:|---:|
| Qwen accept | {matrix['qwen_accept_human_accept']} | {matrix['qwen_accept_human_reject']} |
| Qwen reject | {matrix['qwen_reject_human_accept']} | {matrix['qwen_reject_human_reject']} |

## 누락 Span 검사

| 항목 | 결과 |
|---|---:|
| 계산 가능한 full review | {recall['eligible_reviews']} |
| 기존 후보 중 Codex 승인 | {recall['accepted_extracted_spans']} |
| Codex가 추가한 missing span | {recall['missing_spans']} |
| Observed span recall | {pct(recall['observed_span_recall'])} |
| Wilson 95% CI | {interval(recall['observed_span_recall_wilson_95'])} |

주요 누락 유형은 보온성·두께·가벼움·비침·부드러움·압박감·내구성·세탁 조건·
안감/마감 같은 component 속성이었다. 이 recall은 추출 후보가 포함된 68개 리뷰 안에서의
진단값이며, 추출 span이 0개인 리뷰까지 포함한 corpus-wide recall은 아니다.

## 오류 요약

- False positive: {len(errors['false_positives'])}건
- False negative: {len(errors['false_negatives'])}건
- Scope 불일치: {len(errors['metadata_disagreements']['scope'])}건
- Property-status 불일치: {len(errors['metadata_disagreements']['property_status'])}건
- Visual-observability 불일치: {len(errors['metadata_disagreements']['visual_observability'])}건

False positive에는 fit/slippage, 색상, vague comfort/quality 표현이 섞인 경우가 많았다.
False negative에는 구멍·봉제 풀림·세탁 후 냄새 제거·장기 내구성 같은 behavior/care 근거가
포함됐다.

## 다음 단계

1. 추가된 24개와 18개 판정 변경 사례를 Recall v2/semantic verification prompt의 회귀
   테스트 세트로 고정한다.
2. 누락 유형을 반영해 recall extraction을 수정하고 dense-500을 다시 추출한다.
3. 같은 68개 리뷰에서 missing span 수가 충분히 감소하는지 재검사한다.
4. 개발은 이 AI 판정을 사용할 수 있지만, 외부 보고·논문용 수치는 소규모라도 독립 사람
   표본으로 최종 확인한다.

## 산출물

- 통합 판정 CSV: `audit_app/data/vllm_dense_500_200_codex_combined/human_semantic_audit_live.csv`
- 통합 missing span CSV: `audit_app/data/vllm_dense_500_200_codex_combined/human_missing_spans_live.csv`
- 통합 review check CSV: `audit_app/data/vllm_dense_500_200_codex_combined/human_review_recall_checks_live.csv`
- 기계 판독 지표: `experiments/11_vllm_dense_500_human_audit/results/codex_ai_combined/metrics.json`
- 오류 사례: `experiments/11_vllm_dense_500_human_audit/results/codex_ai_combined/error_cases.json`
"""
    REPORT_PATH.write_text(report, encoding="utf-8")


def main() -> None:
    audit_csv = merge_csv("human_semantic_audit_live.csv", "span_id")
    missing_csv = merge_csv("human_missing_spans_live.csv", "missing_span_id")
    checks_csv = merge_csv("human_review_recall_checks_live.csv", "review_id")
    metrics = analyze_and_write(audit_csv, missing_csv, checks_csv, RESULT_DIR)

    if metrics["sample"]["labeled"] != 200:
        raise RuntimeError("Expected exactly 200 labeled candidates")
    if metrics["recall_audit"]["checked_reviews"] != 68:
        raise RuntimeError("Expected exactly 68 full-review checks")
    if metrics["recall_audit"]["missing_spans"] != 24:
        raise RuntimeError("Expected exactly 24 added missing spans")

    write_notional_report(metrics)
    summary = {
        "status": metrics["status"],
        "sample": metrics["sample"],
        "confusion_matrix": metrics["confusion_matrix"],
        "decision_metrics": metrics["decision_metrics"],
        "field_agreement_on_mutual_accepts": metrics[
            "field_agreement_on_mutual_accepts"
        ],
        "recall_audit": {
            key: value
            for key, value in metrics["recall_audit"].items()
            if key != "per_review"
        },
        "report": str(REPORT_PATH),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
