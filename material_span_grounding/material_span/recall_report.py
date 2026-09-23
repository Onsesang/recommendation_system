from __future__ import annotations

from collections import Counter
from pathlib import Path
from statistics import mean, median

from .common import ROOT, read_jsonl, save_json


def build_recall_report(output_root: Path | None = None) -> dict:
    root = output_root or ROOT / "data" / "v2"
    v1_rows = read_jsonl(ROOT / "data" / "output" / "span_extractions.jsonl")
    v2_rows = read_jsonl(root / "span_extractions.jsonl")
    lens_rows = read_jsonl(root / "lens_extractions.jsonl")
    verification_rows = read_jsonl(root / "semantic_verifications.jsonl")
    v1_by_review = {row["review_id"]: row for row in v1_rows}
    new_candidates = []
    recovered_reviews = []
    contribution = Counter()
    for row in v2_rows:
        old_quotes = {
            evidence["quote"]
            for evidence in v1_by_review.get(row["review_id"], {}).get("evidence", [])
        }
        new_for_review = [
            evidence for evidence in row["evidence"] if evidence["quote"] not in old_quotes
        ]
        for evidence in row["evidence"]:
            for source in evidence.get("sources", []):
                contribution[source] += 1
        for evidence in new_for_review:
            candidate = {
                "review_id": row["review_id"],
                "asin": row["asin"],
                "review": row["text"],
                "quote": evidence["quote"],
                "sources": evidence.get("sources", []),
            }
            span = next(
                (
                    verification
                    for verification in verification_rows
                    if verification["review_id"] == row["review_id"]
                    and verification["quote"] == evidence["quote"]
                ),
                None,
            )
            if span:
                candidate.update(
                    {
                        "qwen_accepted": span.get("accepted"),
                        "qwen_claim": span.get("claim", ""),
                        "qwen_rejection_reason": span.get("rejection_reason", ""),
                    }
                )
            new_candidates.append(candidate)
        if not old_quotes and new_for_review:
            recovered_reviews.append(
                {
                    "review_id": row["review_id"],
                    "asin": row["asin"],
                    "review": row["text"],
                    "new_quotes": [item["quote"] for item in new_for_review],
                }
            )

    v1_counts = [len(row["evidence"]) for row in v1_rows]
    v2_counts = [len(row["evidence"]) for row in v2_rows]
    new_verified = [
        row for row in verification_rows if not row.get("reused_from_v1", False)
    ]
    accepted_new = [row for row in new_verified if row.get("accepted") is True]
    rejected_new = [row for row in new_verified if row.get("accepted") is False]
    lens_status = Counter(row.get("status", "unknown") for row in lens_rows)
    metrics = {
        "protocol": {
            "version": "span_extraction_v2.1_three_lens_union_v1",
            "source": "same 1,000 train-only pilot reviews as v1",
            "protected_test_used": False,
            "interpretation": "candidate coverage comparison; human recall is not yet measured",
        },
        "comparison": {
            "reviews": len(v2_rows),
            "v1_spans": sum(v1_counts),
            "v2_union_spans": sum(v2_counts),
            "candidate_span_increase": sum(v2_counts) - sum(v1_counts),
            "candidate_span_increase_rate": (
                (sum(v2_counts) - sum(v1_counts)) / max(sum(v1_counts), 1)
            ),
            "v1_reviews_with_evidence": sum(count > 0 for count in v1_counts),
            "v2_reviews_with_evidence": sum(count > 0 for count in v2_counts),
            "recovered_v1_empty_reviews": len(recovered_reviews),
            "v1_mean_spans_per_review": mean(v1_counts) if v1_counts else 0.0,
            "v2_mean_spans_per_review": mean(v2_counts) if v2_counts else 0.0,
            "v1_median_spans_per_review": median(v1_counts) if v1_counts else 0.0,
            "v2_median_spans_per_review": median(v2_counts) if v2_counts else 0.0,
        },
        "lens_extraction": {
            "tasks": len(lens_rows),
            "status_counts": dict(lens_status),
            "returned_quotes": sum(row.get("returned_quote_count", 0) for row in lens_rows),
            "invalid_quotes": sum(len(row.get("invalid_quotes", [])) for row in lens_rows),
            "merged_source_contribution_counts": dict(contribution),
        },
        "semantic_verification": {
            "total_candidates": len(verification_rows),
            "reused_v1_judgments": sum(
                bool(row.get("reused_from_v1")) for row in verification_rows
            ),
            "new_candidates_verified": len(new_verified),
            "new_candidates_qwen_accepted": len(accepted_new),
            "new_candidates_qwen_rejected": len(rejected_new),
            "new_candidate_acceptance_rate": len(accepted_new)
            / max(len(new_verified), 1),
            "warning": "Qwen acceptance is not human precision or recall.",
        },
        "examples": {
            "new_qwen_accepted": [
                row for row in new_candidates if row.get("qwen_accepted") is True
            ][:30],
            "new_qwen_rejected": [
                row for row in new_candidates if row.get("qwen_accepted") is False
            ][:20],
            "recovered_reviews": recovered_reviews[:30],
        },
    }
    result_dir = ROOT / "experiments" / "04_recall_extraction_v2" / "results"
    result_dir.mkdir(parents=True, exist_ok=True)
    save_json(result_dir / "metrics.json", metrics)
    save_json(result_dir / "examples.json", metrics["examples"])
    comparison = metrics["comparison"]
    verification = metrics["semantic_verification"]
    report = f"""# 실험 04 — Recall 중심 소재 Span 재수집 v2

## 결론 요약

- 동일 train-only 리뷰: {comparison['reviews']:,}개
- v1 exact span: {comparison['v1_spans']:,}개
- v2 union 후보: {comparison['v2_union_spans']:,}개
- 후보 증가: {comparison['candidate_span_increase']:+,}개 ({comparison['candidate_span_increase_rate']:.1%})
- v1 evidence 0개에서 새 후보가 생긴 리뷰: {comparison['recovered_v1_empty_reviews']:,}개
- 새 후보 Qwen 2차 채택: {verification['new_candidates_qwen_accepted']:,}/{verification['new_candidates_verified']:,}

## 방법

v1 결과를 안전망으로 유지하고, 리뷰 전체를 두 번 독립적으로 탐색했다.

1. surface/use lens: 정체성·촉감·두께·구조·신축·통기·착용 반응
2. behavior/care lens: 세탁·수축·보풀·손상·흡수·형태 변화·내구
3. exact substring 코드 검사
4. 기존 quote와 포함 관계인 후보 병합
5. v1과 v2 후보 union
6. 기존 span의 Qwen v1.1 판단은 재사용하고 새 span만 의미 검증

## 해석 제한

후보 수 증가는 recall 향상의 가능성을 보여주지만, 그 자체가 recall 향상을 증명하지는
않는다. 새 후보에는 fit·construction 같은 false positive가 포함될 수 있어 Qwen verifier와
새 사람 검수를 거친다. 최종 평가는 review-complete audit의 accepted precision과 사람이
추가한 missing span 기반 observed recall로 판단한다.
"""
    (result_dir / "report.md").write_text(report, encoding="utf-8")
    notion_path = ROOT / "notion" / "06_RECALL_EXTRACTION_V2.md"
    notion_path.write_text(report, encoding="utf-8")
    return metrics
