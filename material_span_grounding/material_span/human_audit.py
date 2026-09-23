from __future__ import annotations

import argparse
import csv
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path

from .common import ROOT, save_json


LIVE_CSV = ROOT / "audit_app" / "data" / "human_semantic_audit_live.csv"
MISSING_CSV = ROOT / "audit_app" / "data" / "human_missing_spans_live.csv"
RECALL_CHECKS_CSV = (
    ROOT / "audit_app" / "data" / "human_review_recall_checks_live.csv"
)
RESULT_DIR = ROOT / "experiments" / "03_human_semantic_audit" / "results"
METRICS_PATH = RESULT_DIR / "metrics.json"
REPORT_PATH = RESULT_DIR / "status.md"
ERROR_CASES_PATH = RESULT_DIR / "error_cases.json"

MINIMUM_SAMPLE = {
    "total": 50,
    "qwen_accepted": 30,
    "qwen_rejected": 15,
    "field_pairs": 25,
}
FINAL_TARGETS = {
    "accepted_precision": 0.90,
    "rejected_false_negative_rate_max": 0.15,
    "scope_agreement": 0.90,
    "property_status_agreement": 0.90,
    "visual_observability_agreement": 0.80,
}
SEVERE_EARLY_FAILURE = {
    "accepted_precision": 0.80,
    "rejected_false_negative_rate_max": 0.30,
    "scope_agreement": 0.70,
    "property_status_agreement": 0.70,
    "visual_observability_agreement": 0.60,
}


def _parse_bool(value: object) -> bool | None:
    normalized = str(value).strip().lower()
    if normalized in {"true", "1", "yes"}:
        return True
    if normalized in {"false", "0", "no"}:
        return False
    return None


def _rate(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def _wilson_interval(successes: int, total: int, z: float = 1.96) -> list[float] | None:
    if total == 0:
        return None
    proportion = successes / total
    denominator = 1 + z * z / total
    center = (proportion + z * z / (2 * total)) / denominator
    margin = (
        z
        * math.sqrt(
            proportion * (1 - proportion) / total + z * z / (4 * total * total)
        )
        / denominator
    )
    return [max(0.0, center - margin), min(1.0, center + margin)]


def _agreement(rows: list[dict], qwen_field: str, human_field: str) -> dict:
    comparable = [
        row
        for row in rows
        if str(row.get(qwen_field, "")).strip()
        and str(row.get(human_field, "")).strip()
    ]
    matches = sum(
        str(row[qwen_field]).strip() == str(row[human_field]).strip()
        for row in comparable
    )
    return {
        "matches": matches,
        "total": len(comparable),
        "rate": _rate(matches, len(comparable)),
        "wilson_95": _wilson_interval(matches, len(comparable)),
    }


def _error_category(row: dict) -> str:
    text = f"{row.get('quote', '')} {row.get('comment', '')}".lower()
    patterns = [
        ("vague_comfort_or_quality", r"\b(comfortable|comfort|nice|quality|cozy|cheap)\b"),
        ("fit_or_size", r"\b(fit|fits|fitted|size|tight|loose|baggy)\b"),
        ("construction_or_component", r"\b(zipper|button|seam|strap|hem|pocket|wire)\b"),
        ("appearance_only", r"\b(color|colour|print|pattern|look|looks|cute|pretty)\b"),
        ("care_or_durability", r"\b(wash|washed|dry|shrink|shrunk|pill|tear|rip|lint)\b"),
    ]
    for category, pattern in patterns:
        if re.search(pattern, text):
            return category
    return "other"


def _case(row: dict) -> dict:
    fields = [
        "span_id",
        "asin",
        "quote",
        "review",
        "qwen_accepted",
        "qwen_claim",
        "qwen_scope",
        "qwen_property_status",
        "qwen_visual_observability",
        "qwen_rejection_reason",
        "human_accepted",
        "human_claim",
        "human_scope",
        "human_property_status",
        "human_visual_observability",
        "annotator_id",
        "comment",
    ]
    return {field: row.get(field, "") for field in fields}


def _compute_observed_recall(
    rows: list[dict], missing_rows: list[dict], review_checks: list[dict]
) -> dict:
    checked_review_ids = {
        str(row.get("review_id", "")).strip()
        for row in review_checks
        if _parse_bool(row.get("checked", "")) is True
    }
    rows_by_review: dict[str, list[dict]] = {}
    for row in rows:
        review_id = str(row.get("review_id", "")).strip()
        if review_id:
            rows_by_review.setdefault(review_id, []).append(row)
    missing_by_review: dict[str, list[dict]] = {}
    for row in missing_rows:
        review_id = str(row.get("review_id", "")).strip()
        if review_id:
            missing_by_review.setdefault(review_id, []).append(row)

    eligible_reviews = []
    pending_reviews = []
    accepted_extracted = 0
    missing_count = 0
    for review_id in sorted(checked_review_ids):
        review_rows = rows_by_review.get(review_id, [])
        labeled = [
            row for row in review_rows if _parse_bool(row.get("human_accepted", "")) is not None
        ]
        if not review_rows or len(labeled) != len(review_rows):
            pending_reviews.append(
                {
                    "review_id": review_id,
                    "extracted_candidates": len(review_rows),
                    "labeled_candidates": len(labeled),
                }
            )
            continue
        accepted = sum(
            _parse_bool(row.get("human_accepted", "")) is True for row in labeled
        )
        missing = len(missing_by_review.get(review_id, []))
        accepted_extracted += accepted
        missing_count += missing
        eligible_reviews.append(
            {
                "review_id": review_id,
                "accepted_extracted_spans": accepted,
                "missing_spans": missing,
                "span_recall": _rate(accepted, accepted + missing),
            }
        )
    denominator = accepted_extracted + missing_count
    return {
        "definition": "accepted extracted spans / (accepted extracted spans + human-added missing spans)",
        "scope": "Only full-review-checked reviews whose extracted candidates are all human-labeled.",
        "checked_reviews": len(checked_review_ids),
        "eligible_reviews": len(eligible_reviews),
        "pending_checked_reviews": pending_reviews,
        "accepted_extracted_spans": accepted_extracted,
        "missing_spans": missing_count,
        "observed_span_recall": _rate(accepted_extracted, denominator),
        "observed_span_recall_wilson_95": _wilson_interval(
            accepted_extracted, denominator
        ),
        "per_review": eligible_reviews,
        "note": "This is within-review observed span recall, not corpus-wide recall; zero-extraction reviews are outside this extracted-span audit sample.",
    }


def compute_metrics(
    rows: list[dict],
    missing_rows: list[dict] | None = None,
    review_checks: list[dict] | None = None,
) -> dict:
    valid = []
    invalid_human_values = []
    for row in rows:
        human = _parse_bool(row.get("human_accepted", ""))
        if human is None:
            if str(row.get("human_accepted", "")).strip():
                invalid_human_values.append(row.get("span_id", ""))
            continue
        qwen = _parse_bool(row.get("qwen_accepted", ""))
        if qwen is None:
            continue
        valid.append({**row, "_human": human, "_qwen": qwen})

    tp = sum(row["_qwen"] and row["_human"] for row in valid)
    fp = sum(row["_qwen"] and not row["_human"] for row in valid)
    fn = sum(not row["_qwen"] and row["_human"] for row in valid)
    tn = sum(not row["_qwen"] and not row["_human"] for row in valid)
    qwen_accepted_total = tp + fp
    qwen_rejected_total = fn + tn
    accepted_precision = _rate(tp, qwen_accepted_total)
    rejected_fnr = _rate(fn, qwen_rejected_total)
    decision_accuracy = _rate(tp + tn, len(valid))

    positive_pairs = [row for row in valid if row["_qwen"] and row["_human"]]
    false_positives = [row for row in valid if row["_qwen"] and not row["_human"]]
    false_negatives = [row for row in valid if not row["_qwen"] and row["_human"]]
    agreements = {
        "scope": _agreement(positive_pairs, "qwen_scope", "human_scope"),
        "property_status": _agreement(
            positive_pairs, "qwen_property_status", "human_property_status"
        ),
        "visual_observability": _agreement(
            positive_pairs,
            "qwen_visual_observability",
            "human_visual_observability",
        ),
    }

    sample_ready = (
        len(valid) >= MINIMUM_SAMPLE["total"]
        and qwen_accepted_total >= MINIMUM_SAMPLE["qwen_accepted"]
        and qwen_rejected_total >= MINIMUM_SAMPLE["qwen_rejected"]
    )
    complete = len(valid) == len(rows) and not invalid_human_values
    failures = []
    if sample_ready:
        thresholds = FINAL_TARGETS if complete else SEVERE_EARLY_FAILURE
        checks = [
            (
                "accepted_precision",
                accepted_precision,
                thresholds["accepted_precision"],
                "min",
            ),
            (
                "rejected_false_negative_rate",
                rejected_fnr,
                thresholds["rejected_false_negative_rate_max"],
                "max",
            ),
        ]
        if len(positive_pairs) >= MINIMUM_SAMPLE["field_pairs"] or complete:
            checks.extend(
                [
                    (
                        "scope_agreement",
                        agreements["scope"]["rate"],
                        thresholds["scope_agreement"],
                        "min",
                    ),
                    (
                        "property_status_agreement",
                        agreements["property_status"]["rate"],
                        thresholds["property_status_agreement"],
                        "min",
                    ),
                    (
                        "visual_observability_agreement",
                        agreements["visual_observability"]["rate"],
                        thresholds["visual_observability_agreement"],
                        "min",
                    ),
                ]
            )
        for name, value, threshold, direction in checks:
            if value is None:
                continue
            failed = value < threshold if direction == "min" else value > threshold
            if failed:
                failures.append(
                    {
                        "metric": name,
                        "value": value,
                        "required": f">={threshold:.0%}"
                        if direction == "min"
                        else f"<={threshold:.0%}",
                    }
                )

    if not sample_ready:
        status = "waiting_for_labels"
        development_triggered = False
    elif failures:
        status = "final_needs_development" if complete else "early_severe_failure"
        development_triggered = True
    elif complete:
        status = "final_pass"
        development_triggered = False
    else:
        status = "provisional_monitoring"
        development_triggered = False

    annotators = sorted(
        {
            str(row.get("annotator_id", "")).strip()
            for row in valid
            if str(row.get("annotator_id", "")).strip()
        }
    )
    category_counts: dict[str, int] = {}
    for row in false_positives:
        category = _error_category(row)
        category_counts[category] = category_counts.get(category, 0) + 1
    disagreements = {}
    for name, qwen_field, human_field in [
        ("scope", "qwen_scope", "human_scope"),
        ("property_status", "qwen_property_status", "human_property_status"),
        (
            "visual_observability",
            "qwen_visual_observability",
            "human_visual_observability",
        ),
    ]:
        disagreements[name] = [
            _case(row)
            for row in positive_pairs
            if str(row.get(qwen_field, "")).strip()
            and str(row.get(human_field, "")).strip()
            and str(row[qwen_field]).strip() != str(row[human_field]).strip()
        ]
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "development_triggered": development_triggered,
        "sample": {
            "expected": len(rows),
            "labeled": len(valid),
            "remaining": len(rows) - len(valid),
            "qwen_accepted_labeled": qwen_accepted_total,
            "qwen_rejected_labeled": qwen_rejected_total,
            "human_accepted": tp + fn,
            "human_rejected": fp + tn,
            "annotators": annotators,
            "invalid_human_accepted_span_ids": invalid_human_values,
        },
        "confusion_matrix": {
            "qwen_accept_human_accept": tp,
            "qwen_accept_human_reject": fp,
            "qwen_reject_human_accept": fn,
            "qwen_reject_human_reject": tn,
        },
        "decision_metrics": {
            "accepted_precision": accepted_precision,
            "accepted_precision_wilson_95": _wilson_interval(tp, qwen_accepted_total),
            "rejected_false_negative_rate": rejected_fnr,
            "rejected_false_negative_rate_wilson_95": _wilson_interval(
                fn, qwen_rejected_total
            ),
            "overall_decision_accuracy": decision_accuracy,
            "overall_decision_accuracy_wilson_95": _wilson_interval(
                tp + tn, len(valid)
            ),
        },
        "field_agreement_on_mutual_accepts": agreements,
        "recall_audit": _compute_observed_recall(
            rows, missing_rows or [], review_checks or []
        ),
        "error_analysis": {
            "false_positive_category_counts": category_counts,
            "false_positives": [_case(row) for row in false_positives],
            "false_negatives": [_case(row) for row in false_negatives],
            "metadata_disagreements": disagreements,
        },
        "gate": {
            "minimum_sample": MINIMUM_SAMPLE,
            "final_targets": FINAL_TARGETS,
            "severe_early_failure": SEVERE_EARLY_FAILURE,
            "sample_ready": sample_ready,
            "complete": complete,
            "failures": failures,
            "note": (
                "Early development is triggered only by severe failures; final targets "
                f"apply at {len(rows)}/{len(rows)}."
            ),
        },
    }


def _format_rate(value: float | None) -> str:
    return "—" if value is None else f"{value:.1%}"


def write_report(metrics: dict, report_path: Path = REPORT_PATH) -> None:
    sample = metrics["sample"]
    decision = metrics["decision_metrics"]
    agreement = metrics["field_agreement_on_mutual_accepts"]
    failure_lines = (
        "\n".join(
            f"- `{failure['metric']}`: {_format_rate(failure['value'])} "
            f"(기준 {failure['required']})"
            for failure in metrics["gate"]["failures"]
        )
        or "- 없음"
    )
    error_analysis = metrics["error_analysis"]
    recall = metrics["recall_audit"]
    category_lines = (
        "\n".join(
            f"- `{name}`: {count}건"
            for name, count in sorted(
                error_analysis["false_positive_category_counts"].items(),
                key=lambda item: (-item[1], item[0]),
            )
        )
        or "- 아직 오류 사례 없음"
    )
    report = f"""# 사람 Semantic Audit 자동 품질 상태

> 자동 갱신: {metrics['generated_at']}  
> 상태: `{metrics['status']}`  
> 개발 트리거: `{metrics['development_triggered']}`

## 진행률

- 라벨 완료: {sample['labeled']} / {sample['expected']}
- Qwen 통과 표본 라벨: {sample['qwen_accepted_labeled']}
- Qwen 기각 표본 라벨: {sample['qwen_rejected_labeled']}
- Annotator: {', '.join(sample['annotators']) or '아직 없음'}

50개 전체, Qwen 통과 30개, Qwen 기각 15개가 모이기 전에는 모델을 수정하지 않는다.
중간에는 심각한 실패만 개발을 시작하고, 최종 기준은 {sample['expected']}개 완료 시 적용한다.

## 판단 지표

| 지표 | 현재 값 | 최종 기준 |
|---|---:|---:|
| Accepted precision | {_format_rate(decision['accepted_precision'])} | ≥ {FINAL_TARGETS['accepted_precision']:.0%} |
| Rejected false-negative rate | {_format_rate(decision['rejected_false_negative_rate'])} | ≤ {FINAL_TARGETS['rejected_false_negative_rate_max']:.0%} |
| Overall decision accuracy | {_format_rate(decision['overall_decision_accuracy'])} | 참고 |
| Scope agreement | {_format_rate(agreement['scope']['rate'])} | ≥ {FINAL_TARGETS['scope_agreement']:.0%} |
| Property-status agreement | {_format_rate(agreement['property_status']['rate'])} | ≥ {FINAL_TARGETS['property_status_agreement']:.0%} |
| Visual-observability agreement | {_format_rate(agreement['visual_observability']['rate'])} | ≥ {FINAL_TARGETS['visual_observability_agreement']:.0%} |

## 누락 Span 기반 Recall 점검

- Full review checked: {recall['checked_reviews']}개 리뷰
- Recall 계산 가능: {recall['eligible_reviews']}개 리뷰
- 기존 추출 중 사람 승인: {recall['accepted_extracted_spans']}개
- 사람이 추가한 누락 span: {recall['missing_spans']}개
- Observed span recall: {_format_rate(recall['observed_span_recall'])}

이 값은 현재 표본 안에서 full review 확인을 완료한 리뷰만 대상으로 한 진단값이다.
추출 span이 전혀 없었던 리뷰는 이 extracted-span 표본에 포함되지 않으므로 corpus-wide recall로
해석하지 않는다.

## 현재 실패 항목

{failure_lines}

## 자동 오류 분해

- False positive: {len(error_analysis['false_positives'])}건
- False negative: {len(error_analysis['false_negatives'])}건
- Scope 불일치: {len(error_analysis['metadata_disagreements']['scope'])}건
- Property-status 불일치: {len(error_analysis['metadata_disagreements']['property_status'])}건
- Visual-observability 불일치: {len(error_analysis['metadata_disagreements']['visual_observability'])}건

False-positive 유형:

{category_lines}

전체 오류 문맥은 `error_cases.json`에 저장된다.

## 해석 규칙

- `waiting_for_labels`: 표본 부족. 변경 금지.
- `provisional_monitoring`: 조기 심각 실패 없음. 계속 검수.
- `early_severe_failure`: 충분한 표본에서 큰 오류. 오류 유형 분석과 개발 시작.
- `final_needs_development`: {sample['expected']}개 완료 후 최종 기준 미달. 개발 시작.
- `final_pass`: 다음 단계인 dense gold 구성과 M0/M1 재평가로 진행 가능.

사람 검수가 한 명뿐이면 이 수치는 단일 annotator 기준이다. 최종 논문 보고 전에는
두 번째 annotator의 독립 표본으로 inter-annotator agreement를 추가하는 것이 좋다.
"""
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report, encoding="utf-8")


def _read_optional_csv(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def analyze_and_write(
    csv_path: Path = LIVE_CSV,
    missing_csv_path: Path = MISSING_CSV,
    recall_checks_csv_path: Path = RECALL_CHECKS_CSV,
    result_dir: Path = RESULT_DIR,
) -> dict:
    with csv_path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    metrics = compute_metrics(
        rows,
        _read_optional_csv(missing_csv_path),
        _read_optional_csv(recall_checks_csv_path),
    )
    save_json(result_dir / "metrics.json", metrics)
    save_json(result_dir / "error_cases.json", metrics["error_analysis"])
    write_report(metrics, result_dir / "status.md")
    return metrics


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze live human semantic audit")
    parser.add_argument("--csv", type=Path, default=LIVE_CSV)
    parser.add_argument("--result-dir", type=Path, default=RESULT_DIR)
    args = parser.parse_args()
    print(
        json.dumps(
            analyze_and_write(args.csv, result_dir=args.result_dir),
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
