from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean, median
from typing import Any

from .common import ROOT, load_json, read_jsonl, save_json


DEFAULT_ROOT = ROOT / "data" / "dense" / "v2"


def build_dense_500_report(root: Path = DEFAULT_ROOT) -> dict[str, Any]:
    extraction_run = load_json(root / "extraction_run.json")
    verification_run = load_json(root / "verification_run.json")
    extraction_rows = read_jsonl(root / "span_extractions.jsonl")
    lens_rows = read_jsonl(root / "lens_extractions.jsonl")
    verification_rows = read_jsonl(root / "semantic_verifications.jsonl")

    accepted = [
        row
        for row in verification_rows
        if row.get("status") == "success" and row.get("accepted") is True
    ]
    rejected = [
        row
        for row in verification_rows
        if row.get("status") == "success" and row.get("accepted") is False
    ]
    input_products = {str(row["asin"]) for row in extraction_rows}
    evidence_products = {
        str(row["asin"]) for row in extraction_rows if row.get("evidence")
    }
    accepted_products = {str(row["asin"]) for row in accepted}
    accepted_reviews = {str(row["review_id"]) for row in accepted}
    users_by_product: dict[str, set[str]] = defaultdict(set)
    for row in accepted:
        users_by_product[str(row["asin"])].add(
            str(row.get("user_id") or f"missing:{row['review_id']}")
        )
    user_counts = [len(users) for users in users_by_product.values()]
    user_histogram = Counter(user_counts)
    lens_status = Counter(str(row.get("status", "unknown")) for row in lens_rows)
    invalid_quotes = sum(len(row.get("invalid_quotes", [])) for row in lens_rows)

    metrics: dict[str, Any] = {
        "status": "complete",
        "root": str(root.relative_to(ROOT)),
        "protected_test_used": False,
        "input": {
            "products": len(input_products),
            "reviews": len(extraction_rows),
            "input_sha256": extraction_run.get("input_sha256"),
        },
        "extraction": {
            "model": extraction_run.get("model"),
            "prompt_version": extraction_run.get("prompt_version"),
            "tasks": len(lens_rows),
            "task_status_counts": dict(lens_status),
            "invalid_quotes": invalid_quotes,
            "union_exact_spans": sum(
                len(row.get("evidence", [])) for row in extraction_rows
            ),
            "reviews_with_evidence": sum(
                bool(row.get("evidence")) for row in extraction_rows
            ),
            "products_with_evidence": len(evidence_products),
            "elapsed_seconds": extraction_run.get("elapsed_seconds"),
        },
        "verification": {
            "prompt_version": verification_run.get("prompt_version"),
            "candidates": len(verification_rows),
            "schema_success": verification_run.get("schema_success"),
            "accepted": len(accepted),
            "rejected": len(rejected),
            "qwen_acceptance_rate": len(accepted) / max(len(verification_rows), 1),
            "reviews_with_accepted_claim": len(accepted_reviews),
            "products_with_accepted_claim": len(accepted_products),
            "elapsed_seconds": verification_run.get("elapsed_seconds"),
        },
        "target_readiness": {
            "products": len(accepted_products),
            "products_with_multiple_evidence_users": sum(
                count >= 2 for count in user_counts
            ),
            "evidence_users_per_product_histogram": {
                str(key): user_histogram[key] for key in sorted(user_histogram)
            },
            "mean_evidence_users_per_product": mean(user_counts) if user_counts else 0,
            "median_evidence_users_per_product": (
                median(user_counts) if user_counts else 0
            ),
        },
        "interpretation_limits": [
            "Qwen acceptance rate is not human precision.",
            "Precision drift must be measured with a stratified human audit.",
            "Products without accepted material claims cannot form M1 targets.",
        ],
    }

    result_root = ROOT / "experiments" / "09_dense_500_extraction" / "results"
    save_json(result_root / "metrics.json", metrics)

    extraction = metrics["extraction"]
    verification = metrics["verification"]
    readiness = metrics["target_readiness"]
    total_hours = (
        float(extraction.get("elapsed_seconds") or 0)
        + float(verification.get("elapsed_seconds") or 0)
    ) / 3600
    histogram_rows = "\n".join(
        f"| {count}명 | {products:,} |"
        for count, products in readiness["evidence_users_per_product_histogram"].items()
    )
    report = f"""# DENSE 500 Recall v2 추출·검증 결과

> 실행일: 2026-08-13  
> 입력: 500상품·4,158리뷰 product-dense train-only corpus  
> protected test: 미사용

## 핵심 결과

| 항목 | 결과 |
|---|---:|
| 처리 리뷰 | {metrics['input']['reviews']:,} |
| 두-lens task | {extraction['tasks']:,} |
| exact span이 있는 리뷰 | {extraction['reviews_with_evidence']:,} |
| union exact span | {extraction['union_exact_spans']:,} |
| 원문 불일치 후보 | {extraction['invalid_quotes']:,} |
| semantic accepted | {verification['accepted']:,} |
| semantic rejected | {verification['rejected']:,} |
| Qwen acceptance rate | {verification['qwen_acceptance_rate']:.2%} |
| 최종 target 가능 상품 | {readiness['products']:,} / {metrics['input']['products']:,} |
| 다중 근거 사용자 상품 | {readiness['products_with_multiple_evidence_users']:,} |
| 추출+검증 GPU 시간 | {total_hours:.2f}시간 |

## 상품별 소재 근거 사용자 수

| 근거 사용자 | 상품 수 |
|---:|---:|
{histogram_rows}

## 해석

- 모든 quote는 코드의 exact-substring 검사를 통과한 span만 union에 포함된다.
- Qwen acceptance rate는 사람 precision이 아니다.
- 기존 100-span audit의 93.75% precision을 이 corpus에 그대로 확정 적용하지 않는다.
- 다음 단계는 New V2, Qwen reject, 카테고리와 사용자 밀도를 반영한 층화 사람 검수다.
- M0/M1 비교는 검수 drift와 dense gold 평가 구성을 확인한 뒤 수행한다.

## 재현성

- 입력 SHA-256: `{metrics['input']['input_sha256']}`
- extraction prompt: `{extraction['prompt_version']}`
- verification prompt: `{verification['prompt_version']}`
- machine-readable metrics: `experiments/09_dense_500_extraction/results/metrics.json`
- 동결 protocol: `notion/09_DENSE_500_PROTOCOL_FREEZE.md`
"""
    (result_root / "report.md").write_text(report, encoding="utf-8")
    (ROOT / "notion" / "10_DENSE_500_EXTRACTION_RESULTS.md").write_text(
        report, encoding="utf-8"
    )
    return metrics


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the dense-500 result report")
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    args = parser.parse_args()
    metrics = build_dense_500_report(args.root)
    print(
        f"dense-500 report complete: "
        f"{metrics['verification']['accepted']} accepted claims"
    )


if __name__ == "__main__":
    main()
