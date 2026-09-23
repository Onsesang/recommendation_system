from __future__ import annotations

import csv
from collections import Counter
from statistics import mean, median

from .common import ROOT, load_config, load_json, read_jsonl, save_json


def _table(rows: list[dict]) -> str:
    if not rows:
        return "(결과 없음)"
    columns = list(rows[0])
    lines = [
        "| " + " | ".join(columns) + " |",
        "|" + "|".join("---" for _ in columns) + "|",
    ]
    lines.extend("| " + " | ".join(str(row[c]) for c in columns) + " |" for row in rows)
    return "\n".join(lines)


def build_report() -> dict:
    cfg = load_config()
    manifest = load_json(ROOT / "data" / "manifests" / "sample_manifest.json")
    run = load_json(ROOT / "data" / "manifests" / "extraction_run.json")
    rows = read_jsonl(ROOT / "data" / "output" / "span_extractions.jsonl")
    raw_rows = read_jsonl(ROOT / "data" / "output" / "raw_generations.jsonl")
    statuses = Counter(row["status"] for row in rows)
    span_counts = [len(row["evidence"]) for row in rows]
    returned = sum(int(row["returned_quote_count"]) for row in rows)
    valid_spans = sum(span_counts)
    invalid_spans = sum(len(row["invalid_quotes"]) for row in rows)
    exact_returned = returned - invalid_spans
    phrase_counts = Counter(
        item["quote"].strip().lower()
        for row in rows
        for item in row["evidence"]
    )
    examples = [
        {
            "review_id": row["review_id"],
            "asin": row["asin"],
            "review": row["text"],
            "quotes": [item["quote"] for item in row["evidence"]],
        }
        for row in rows
        if row["evidence"]
    ][:12]
    empty_examples = [
        {"review_id": row["review_id"], "asin": row["asin"], "review": row["text"]}
        for row in rows
        if row["status"] == "success" and not row["evidence"]
    ][:5]
    metrics = {
        "protocol": {
            "model": run["model"],
            "prompt_version": run["prompt_version"],
            "source_split": "seoyoung train only",
            "protected_test_used": False,
            "pilot_scope": True,
        },
        "sample": manifest,
        "execution": {
            "processed_reviews": len(rows),
            "elapsed_seconds": run.get("cumulative_elapsed_seconds", run["elapsed_seconds"]),
            "reviews_per_second": len(rows)
            / max(run.get("cumulative_elapsed_seconds", run["elapsed_seconds"]), 1e-9),
            "generation_attempts": len(raw_rows),
            "status_counts": dict(statuses),
        },
        "extraction": {
            "reviews_with_evidence": sum(count > 0 for count in span_counts),
            "review_coverage": sum(count > 0 for count in span_counts) / max(len(rows), 1),
            "valid_exact_spans": valid_spans,
            "exact_returned_before_dedup": exact_returned,
            "invalid_nonexact_spans": invalid_spans,
            "returned_quote_count": returned,
            "exact_quote_validity": exact_returned / max(returned, 1),
            "unique_quote_strings": len(phrase_counts),
            "mean_spans_per_review": mean(span_counts) if span_counts else 0.0,
            "median_spans_per_review": median(span_counts) if span_counts else 0.0,
            "top_exact_quotes": phrase_counts.most_common(30),
        },
        "quality_status": {
            "automatic_contract_checks": "complete",
            "human_span_precision_recall": "not_measured",
            "warning": "Exact substring validity is not semantic correctness.",
        },
    }
    result_dir = ROOT / "experiments" / "01_span_extraction" / "results"
    save_json(result_dir / "metrics.json", metrics)
    save_json(result_dir / "examples.json", {"positive": examples, "empty": empty_examples})

    audit_path = ROOT / "experiments" / "01_span_extraction" / "human_span_audit.csv"
    should_write_audit = not audit_path.exists()
    if audit_path.exists():
        with audit_path.open(encoding="utf-8", newline="") as handle:
            existing_audit = list(csv.DictReader(handle))
        should_write_audit = not any(
            str(row.get("annotator_id", "")).strip() for row in existing_audit
        )
    if should_write_audit:
        positive_pool = sorted(
            (row for row in rows if row["evidence"]), key=lambda row: row["review_id"]
        )[:100]
        empty_pool = sorted(
            (row for row in rows if not row["evidence"]), key=lambda row: row["review_id"]
        )[:100]
        audit_rows = positive_pool + empty_pool
        audit_path.parent.mkdir(parents=True, exist_ok=True)
        with audit_path.open("w", encoding="utf-8", newline="") as handle:
            fields = [
                "review_id",
                "asin",
                "review",
                "model_quotes",
                "human_gold_quotes",
                "human_false_positive_quotes",
                "human_missed_quotes",
                "annotator_id",
                "comment",
            ]
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            for row in audit_rows:
                writer.writerow(
                    {
                        "review_id": row["review_id"],
                        "asin": row["asin"],
                        "review": row["text"],
                        "model_quotes": " || ".join(
                            item["quote"] for item in row["evidence"]
                        ),
                        "human_gold_quotes": "",
                        "human_false_positive_quotes": "",
                        "human_missed_quotes": "",
                        "annotator_id": "",
                        "comment": "",
                    }
                )

    status_rows = [
        {"상태": name, "리뷰 수": count}
        for name, count in sorted(statuses.items())
    ]
    top_rows = [
        {"원문 구절": quote, "횟수": count}
        for quote, count in phrase_counts.most_common(20)
    ]
    report = f"""# 실험 01 — Qwen 소재 exact span 추출 pilot

## 목적

리뷰를 요약하거나 고정 소재 class로 분류하지 않고, 원문에서 명시적으로 언급된
소재·질감 evidence span을 그대로 복사한다. 후속 Qwen 검증과 상품 embedding의
추적 가능한 입력을 만드는 단계다.

## 데이터와 누수 통제

- split: `seoyoung` train only
- 리뷰: {len(rows):,}건, 상품 {manifest['selected_products']:,}개
- 상품당 최대 리뷰: {cfg['max_reviews_per_product']}건
- 표본: seed {cfg['seed']} SHA-256 결정적 표본
- validation/calibration/protected test: 사용하지 않음

## 실행 설정

- 모델: `{run['model']}`
- prompt: `{run['prompt_version']}`
- batch size: {run['batch_size']}
- strict JSON 실패 시 최대 시도: {run['max_attempts']}회
- 생성 시간: {metrics['execution']['elapsed_seconds'] / 60:.1f}분
- 처리량: {metrics['execution']['reviews_per_second']:.2f} reviews/s

## 자동 검증 결과

{_table(status_rows)}

- evidence가 발견된 리뷰: {metrics['extraction']['reviews_with_evidence']:,}/{len(rows):,}
  ({metrics['extraction']['review_coverage']:.1%})
- 유효 exact span: {valid_spans:,}개
- 원문에 없는 quote: {invalid_spans:,}개
- exact quote 자동 유효율: {metrics['extraction']['exact_quote_validity']:.1%}
- 리뷰당 span: 평균 {metrics['extraction']['mean_spans_per_review']:.2f},
  중앙값 {metrics['extraction']['median_spans_per_review']:.1f}

## 자주 추출된 exact quote

{_table(top_rows)}

## 기존 방식과 비교

기존 `exp_k_open_vocab.py`는 400개 리뷰에서 439개 정규화 구절을 얻었지만,
`very soft → soft`처럼 강도를 제거했고 원문 span·review ID·user ID를 보존하지
않았다. 이번 방식은 표현을 정규화하지 않고 exact substring만 채택해 모든 결과를
원문과 사용자까지 역추적할 수 있다.

## 관찰된 v1.0 개선점

1. Qwen이 반환한 quote {returned:,}개 중 {invalid_spans:,}개는 대소문자 변경,
   축약 또는 paraphrase 때문에 exact substring 검사를 통과하지 못했다. 다음
   prompt에서는 `partial_invalid_quote`도 원문과 함께 한 번 교정 재시도한다.
2. `comfortable` 8회, `very comfortable` 3회처럼 소재 원인이 명시되지 않은
   일반 편안함 후보가 남았다. 1차에서 무리하게 없애기보다 사람 감사와 2차
   semantic verifier에서 제외하는 편이 recall 보존에 안전하다.
3. `and stretchy`처럼 문법적으로 불완전하지만 원문에는 정확히 존재하는 span이
   발생했다. 후속 embedding에는 exact quote와 별도로, 2차 검증을 통과한
   self-contained claim을 사용해야 한다.
4. 핏 문맥의 `they do stretch very well` 같은 표현은 소재 stretch인지 의복 fit인지
   경계가 모호해 누락될 수 있다. 빈 결과 표본의 missed span을 사람이 별도로
   기록해야 recall을 측정할 수 있다.
5. 이번 {metrics['extraction']['review_coverage']:.1%}는 무작위 리뷰 한 건 단위
   후보 발견률이다. 기존 98%는 상품당 여러 리뷰를 합친 상품 coverage이므로 두
   값을 직접 비교하지 않는다.

## 해석 제한

exact substring 검사는 Qwen이 문장을 실제로 복사했는지만 보장한다. 그 구절이
정말 소재 정보인지, 소재 구절을 얼마나 놓쳤는지는 사람 gold 없이는 알 수 없다.
따라서 이 결과의 coverage를 소재 정보 보유율이나 extraction recall로 해석하지
않는다.

## 다음 단계

1. evidence가 있는 리뷰와 빈 리뷰를 층화해 사람 감사 표본을 만든다.
2. span precision/recall과 negation 보존 정확도를 측정한다.
3. 통과한 span만 Qwen 2차 검증으로 보내 scope·극성·관찰 가능성을 구조화한다.
4. 동일 사용자 반복 제거와 semantic deduplication은 코드로 수행한다.
"""
    result_dir.mkdir(parents=True, exist_ok=True)
    (result_dir / "report.md").write_text(report, encoding="utf-8")

    notion = f"""# 소재 서술 파이프라인 — 1차 소재 span 추출

> 실험일: 2026-08-04  
> 프로젝트: `/home/user/onsesang/material_span_grounding`  
> 상태: Qwen 1차 exact-span pilot 완료, 사람 의미 검증 대기

{report.split('## 목적', 1)[1]}

## 산출물

| 파일 | 설명 |
|---|---|
| `data/input/reviews_pilot.jsonl` | 결정적으로 선택한 원문 리뷰 |
| `data/output/raw_generations.jsonl` | Qwen 원시 응답과 재시도 기록 |
| `data/output/span_extractions.jsonl` | 코드 검증을 통과한 exact spans |
| `experiments/01_span_extraction/results/metrics.json` | 기계 판독 결과 |
| `experiments/01_span_extraction/results/examples.json` | 검토용 예시 |
| `experiments/01_span_extraction/human_span_audit.csv` | positive/empty 층화 사람 감사표 |

## 전체 파이프라인에서의 위치

```text
[완료] Qwen 1차 소재 span 추출
   ↓
[다음] Qwen 2차 소재 여부·scope·극성 검증
   ↓
exact quote 검사 → 사용자 반복 제거 → semantic dedup
   ↓
사용자 합의도·가중치 → 상품 target embedding → M1~M5 비교
```
"""
    notion_dir = ROOT / "notion"
    notion_dir.mkdir(parents=True, exist_ok=True)
    (notion_dir / "01_QWEN_MATERIAL_SPAN_EXTRACTION.md").write_text(
        notion, encoding="utf-8"
    )
    return metrics
