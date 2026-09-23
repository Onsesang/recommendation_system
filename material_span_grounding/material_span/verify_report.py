from __future__ import annotations

import csv
import re
from collections import Counter

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


def build_verification_report() -> dict:
    cfg = load_config()
    input_manifest = load_json(ROOT / "data" / "manifests" / "verification_input_manifest.json")
    run = load_json(ROOT / "data" / "manifests" / "verification_run.json")
    rows = read_jsonl(ROOT / "data" / "output" / "semantic_verifications.jsonl")
    raw = read_jsonl(ROOT / "data" / "output" / "semantic_verification_raw.jsonl")
    successful = [row for row in rows if row["status"] == "success"]
    accepted = [row for row in successful if row["accepted"]]
    rejected = [row for row in successful if not row["accepted"]]
    status_counts = Counter(row["status"] for row in rows)
    raw_status_counts = Counter(row["validation_status"] for row in raw)
    distributions = {
        field: dict(Counter(row[field] for row in accepted))
        for field in [
            "scope",
            "property_status",
            "intensity",
            "sentiment",
            "evidence_basis",
            "visual_observability",
        ]
    }
    rejection_counts = Counter(row["rejection_reason"].strip().lower() for row in rejected)
    vague_pattern = re.compile(
        r"\b(comfortable|comfort|nice|quality|cheap|cozy|flattering)\b", re.I
    )
    concrete_pattern = re.compile(
        r"\b(soft|rough|scratch|itch|thick|thickness|thin|stretch|elastic|warm|cool|"
        r"breath|sheer|see.through|opaque|lightweight|heavy|weight|cotton|polyester|"
        r"fleece|leather|wool|silk|linen|smooth|stiff|flow|drape|absorb|wick|dry|"
        r"pill|lint|shrink|tear|thread|durable|flexible|moisture)\b",
        re.I,
    )
    vague_flags = [
        row
        for row in accepted
        if vague_pattern.search(row["quote"]) and not concrete_pattern.search(row["quote"])
    ]
    accessory_pattern = re.compile(r"\b(zipper|button|buckle|strap|seam)\b", re.I)
    accessory_flags = [row for row in accepted if accessory_pattern.search(row["quote"])]
    metrics = {
        "protocol": {
            "model": run["model"],
            "prompt_version": run["prompt_version"],
            "source": "stage-1 exact spans from train-only pilot",
            "protected_test_used": False,
        },
        "input": input_manifest,
        "execution": {
            "processed_spans": len(rows),
            "generation_attempts": len(raw),
            "retry_attempts": max(len(raw) - len(rows), 0),
            "raw_validation_status_counts": dict(raw_status_counts),
            "elapsed_seconds": run.get("cumulative_elapsed_seconds", run["elapsed_seconds"]),
            "status_counts": dict(status_counts),
        },
        "verification": {
            "accepted": len(accepted),
            "rejected": len(rejected),
            "acceptance_rate": len(accepted) / max(len(successful), 1),
            "ambiguous_accepted": sum(row["ambiguous"] for row in accepted),
            "distributions": distributions,
            "top_rejection_reasons": rejection_counts.most_common(20),
            "boundary_diagnostics": {
                "accepted_vague_without_concrete_keyword": len(vague_flags),
                "accepted_vague_examples": [row["quote"] for row in vague_flags[:20]],
                "accepted_accessory_keyword": len(accessory_flags),
                "accepted_accessory_examples": [row["quote"] for row in accessory_flags[:20]],
                "note": "Lexical flags are review candidates, not gold errors.",
            },
        },
        "quality_status": {
            "automatic_schema_checks": "complete",
            "human_semantic_accuracy": "not_measured",
            "warning": "Qwen verification is a model judgment, not gold annotation.",
        },
    }
    result_dir = ROOT / "experiments" / "02_semantic_verification" / "results"
    save_json(result_dir / "metrics.json", metrics)
    examples = {
        "accepted": [
            {k: row[k] for k in ["span_id", "quote", "claim", "scope", "property_status", "visual_observability"]}
            for row in accepted[:30]
        ],
        "rejected": [
            {k: row[k] for k in ["span_id", "quote", "rejection_reason"]}
            for row in rejected[:30]
        ],
    }
    save_json(result_dir / "examples.json", examples)

    audit_path = ROOT / "experiments" / "02_semantic_verification" / "human_semantic_audit.csv"
    should_write = not audit_path.exists()
    if audit_path.exists():
        with audit_path.open(encoding="utf-8", newline="") as handle:
            existing = list(csv.DictReader(handle))
        should_write = not any(str(row.get("annotator_id", "")).strip() for row in existing)
    if should_write:
        sample = sorted(accepted, key=lambda row: row["span_id"])[:100] + sorted(
            rejected, key=lambda row: row["span_id"]
        )[:100]
        audit_path.parent.mkdir(parents=True, exist_ok=True)
        fields = [
            "span_id", "review_id", "asin", "review", "quote", "qwen_accepted",
            "qwen_claim", "qwen_scope", "qwen_property_status", "qwen_intensity",
            "qwen_sentiment", "qwen_evidence_basis", "qwen_visual_observability",
            "qwen_rejection_reason", "human_accepted", "human_claim", "human_scope",
            "human_property_status", "human_visual_observability", "annotator_id", "comment",
        ]
        with audit_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            for row in sample:
                writer.writerow(
                    {
                        "span_id": row["span_id"], "review_id": row["review_id"],
                        "asin": row["asin"], "review": row["review_text"], "quote": row["quote"],
                        "qwen_accepted": row["accepted"], "qwen_claim": row["claim"],
                        "qwen_scope": row["scope"], "qwen_property_status": row["property_status"],
                        "qwen_intensity": row["intensity"], "qwen_sentiment": row["sentiment"],
                        "qwen_evidence_basis": row["evidence_basis"],
                        "qwen_visual_observability": row["visual_observability"],
                        "qwen_rejection_reason": row["rejection_reason"],
                        "human_accepted": "", "human_claim": "", "human_scope": "",
                        "human_property_status": "", "human_visual_observability": "",
                        "annotator_id": "", "comment": "",
                    }
                )

    distribution_rows = [
        {"필드": field, "분포": ", ".join(f"{k}={v}" for k, v in values.items())}
        for field, values in distributions.items()
    ]
    report = f"""# 실험 02 — Qwen 소재 semantic verification pilot

## 목적

1차 Qwen이 복사한 exact span이 실제 소재 evidence인지 다시 검증하고, 채택된
span에 자유 텍스트 claim과 scope·극성·강도·근거 방식·시각 관찰 가능성을 붙인다.
고정 소재 taxonomy로 분류하지 않는다.

## 입력과 누수 통제

- 입력 exact span: {len(rows):,}개
- 원천: 실험 01의 train-only 리뷰 1,000건
- validation/calibration/protected test: 사용하지 않음
- 모델: `{run['model']}`
- prompt: `{run['prompt_version']}`
- 생성 시간: {metrics['execution']['elapsed_seconds'] / 60:.1f}분

## 자동 결과

- schema 검증 성공: {len(successful):,}/{len(rows):,}
- schema 재시도: {metrics['execution']['retry_attempts']:,}회
- 채택: {len(accepted):,}개 ({metrics['verification']['acceptance_rate']:.1%})
- 거절: {len(rejected):,}개
- ambiguous로 표시된 채택 span: {metrics['verification']['ambiguous_accepted']:,}개

{_table(distribution_rows)}

## Prompt smoke test와 경계 진단

- v1.0 16-span smoke test에서 단순 `thick`을 `strong/direct_touch`로 과대
  구조화하고 `likely cotton`을 확정 진술로 처리해 실행을 중단했다. 해당 결과는
  `pilot_v1_0/`에 보존했다.
- v1.1은 강도·불확실성·근거 방식을 명시적 어휘에 근거하도록 수정했고 전체
  {len(rows):,}개를 이 버전으로 다시 처리했다.
- v1.1은 1차 span의 {metrics['verification']['acceptance_rate']:.1%}를 채택해
  강한 필터보다 metadata 정제기로 동작했다.
- 자동 lexical 감사에서 구체 속성 keyword가 없는 comfort/quality 계열 채택
  후보가 {len(vague_flags):,}개, 부속품 keyword 채택 후보가
  {len(accessory_flags):,}개 발견됐다. 예: `{vague_flags[0]['quote'] if vague_flags else '없음'}`,
  `{accessory_flags[0]['quote'] if accessory_flags else '없음'}`.
- 이 flag는 사람이 확인할 우선 표본이지 자동 오답 수가 아니다.

## 해석

채택률은 semantic precision이 아니다. 같은 Qwen 계열 모델이 1차 후보를 만들고
2차 판정도 했으므로 오류가 상관될 수 있다. 특히 self-contained claim이 원문
의미를 보존하는지, `comfortable` 같은 모호 표현이 적절히 제거됐는지,
visual observability 판정이 일관적인지는 사람 감사가 필요하다.

## 다음 단계

1. accepted 100개와 rejected 전체 {len(rejected)}개의 사람 semantic audit을 수행한다.
2. accepted precision, rejected false-negative rate, scope/status/observability agreement를 계산한다.
3. 통과한 span만 동일 사용자 반복 제거와 polarity-aware semantic deduplication에 전달한다.
"""
    result_dir.mkdir(parents=True, exist_ok=True)
    (result_dir / "report.md").write_text(report, encoding="utf-8")
    notion_dir = ROOT / "notion"
    notion_dir.mkdir(parents=True, exist_ok=True)
    notion = f"""# 소재 서술 파이프라인 — 2차 Qwen semantic verification

> 실험일: 2026-08-04  
> 프로젝트: `/home/user/onsesang/material_span_grounding`  
> 상태: 자동 검증 완료, 사람 semantic audit 대기

{report.split('## 목적', 1)[1]}

## 산출물

| 파일 | 설명 |
|---|---|
| `data/input/semantic_verification_input.jsonl` | 1차 exact span과 원문 |
| `data/output/semantic_verifications.jsonl` | 구조화된 2차 검증 결과 |
| `data/output/semantic_verification_raw.jsonl` | Qwen 원시 출력과 재시도 |
| `experiments/02_semantic_verification/results/metrics.json` | 자동 통계 |
| `experiments/02_semantic_verification/human_semantic_audit.csv` | 사람 검토표 |

## 전체 파이프라인 상태

```text
[완료] Qwen 1차 exact span 추출
[완료] Qwen 2차 소재 여부·scope·극성 검증
[다음] 사람 검증 → 동일 사용자 반복 제거 → semantic deduplication
       → 합의도·가중치 → 상품 target embedding → M1~M5
```
"""
    (notion_dir / "02_QWEN_SEMANTIC_VERIFICATION.md").write_text(notion, encoding="utf-8")
    return metrics
