#!/usr/bin/env python3
"""Offline ranking evaluation for the full-catalog (Last2) agent mode.

There is no human-labelled relevance set for the 825,840-item catalog, so this
does not report accuracy. It measures whether the ranker moves the signal it
claims to move, against the candidate pool it actually searched:

  lift            mean Last2 probability of the requested class in the top-K,
                  minus the mean over the whole category pool. Positive means
                  the ranking surfaced the property that was asked for.
  negation_gap    mean probability for a negated phrasing subtracted from the
                  same term phrased positively. Positive means negation flipped
                  the direction rather than being ignored.
  category_purity fraction of top-K rows inside the parsed category.
  duplicate_rate  fraction of top-K rows sharing a product-family title key.

Run:
    python -m shopping_agent.evaluation.full_catalog_offline_eval
    python -m shopping_agent.evaluation.full_catalog_offline_eval --top-k 30
"""

from __future__ import annotations

import argparse
import json
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from shopping_agent.v1.full_catalog import FullCatalogTools

REPORT_PATH = Path(__file__).resolve().parent / "full_catalog_v1.json"

# Each case states the Last2 class the phrasing is supposed to drive.
POSITIVE_CASES: tuple[tuple[str, str], ...] = (
    ("부드러운 니트 추천해줘", "soft"),
    ("두껍고 따뜻한 자켓", "thick"),
    ("얇고 시원한 셔츠 찾아줘", "thin"),
    ("신축성 있는 바지", "elastic"),
    ("폭신한 후드", "spongy"),
    ("매끄러운 원피스", "smooth"),
    ("뻣뻣한 청바지", "stiff"),
    ("따뜻한 코트", "warm"),
)

# (positive phrasing, negated phrasing, class the pair drives)
NEGATION_CASES: tuple[tuple[str, str, str], ...] = (
    ("까슬한 니트", "까슬거리지 않는 니트", "rough"),
    ("두꺼운 자켓", "두껍지 않은 자켓", "thick"),
    ("따뜻한 셔츠", "따뜻하지 않은 셔츠", "warm"),
    ("신축성 있는 바지", "잘 늘어나지 않는 바지", "elastic"),
)


def _pool_mean(tools: FullCatalogTools, query: str, tactile_class: str) -> tuple[float, int]:
    """Mean probability over every candidate the query's category filter kept."""
    from demo_agent.tactile_parser import parse_message

    parsed = parse_message(query)
    rows, _ = tools.index.candidate_rows(parsed.category)
    column = tools.index._class_index[tactile_class]
    return float(tools.index.matrix[rows, column].mean()), int(rows.size)


def _top_k_mean(items: list[dict[str, Any]], tactile_class: str) -> float:
    return float(statistics.fmean(row["last2_predictions"][tactile_class] for row in items))


def evaluate(top_k: int) -> dict[str, Any]:
    started = time.perf_counter()
    tools = FullCatalogTools()

    lift_rows = []
    for query, tactile_class in POSITIVE_CASES:
        payload = tools.tactile.search(query, limit=top_k)
        items = payload["items"]
        pool_mean, pool_size = _pool_mean(tools, query, tactile_class)
        top_mean = _top_k_mean(items, tactile_class)
        title_keys = [tools.index.title_key(tools.index.row_of(row["product_id"])) for row in items]
        in_category = (
            sum(1 for row in items if row["category"] in _broad(payload["category"])) / len(items)
            if items
            else 0.0
        )
        lift_rows.append(
            {
                "query": query,
                "target_class": tactile_class,
                "candidate_pool": pool_size,
                "pool_mean_probability": round(pool_mean, 4),
                "top_k_mean_probability": round(top_mean, 4),
                "lift": round(top_mean - pool_mean, 4),
                "category": payload["category"],
                "category_purity": round(in_category, 4),
                "duplicate_rate": round(1.0 - len(set(title_keys)) / max(1, len(title_keys)), 4),
                "ranking_mode": payload["ranking_mode"],
            }
        )

    negation_rows = []
    for positive_query, negated_query, tactile_class in NEGATION_CASES:
        positive = tools.tactile.search(positive_query, limit=top_k)["items"]
        negated = tools.tactile.search(negated_query, limit=top_k)["items"]
        positive_mean = _top_k_mean(positive, tactile_class)
        negated_mean = _top_k_mean(negated, tactile_class)
        negation_rows.append(
            {
                "positive_query": positive_query,
                "negated_query": negated_query,
                "target_class": tactile_class,
                "positive_mean_probability": round(positive_mean, 4),
                "negated_mean_probability": round(negated_mean, 4),
                "negation_gap": round(positive_mean - negated_mean, 4),
                "direction_correct": bool(negated_mean < positive_mean),
            }
        )

    lifts = [row["lift"] for row in lift_rows]
    gaps = [row["negation_gap"] for row in negation_rows]
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "catalog_mode": "full",
        "catalog_products": len(tools.index),
        "tactile_provider": tools.tactile.version,
        "tactile_source": "image_predicted_last2",
        "top_k": top_k,
        "config": {
            "relevance": tools.index.config["relevance"],
            "concept_fidelity": tools.index.config["concept_fidelity"],
            "retrieval": tools.index.config["retrieval"],
        },
        "summary": {
            "mean_lift": round(statistics.fmean(lifts), 4),
            "min_lift": round(min(lifts), 4),
            "positive_cases_with_lift": sum(1 for value in lifts if value > 0),
            "positive_cases_total": len(lifts),
            "mean_negation_gap": round(statistics.fmean(gaps), 4),
            "negation_direction_correct": sum(
                1 for row in negation_rows if row["direction_correct"]
            ),
            "negation_cases_total": len(negation_rows),
            "mean_category_purity": round(
                statistics.fmean(row["category_purity"] for row in lift_rows), 4
            ),
            "max_duplicate_rate": round(max(row["duplicate_rate"] for row in lift_rows), 4),
        },
        "positive_cases": lift_rows,
        "negation_cases": negation_rows,
        "runtime_seconds": round(time.perf_counter() - started, 2),
        "caveats": [
            "Last2 확률은 상품 이미지에서 예측한 값이며 구매자 리뷰 근거가 아니다.",
            "사람이 라벨링한 relevance set이 없으므로 이 수치는 정확도가 아니라 진단용이다.",
            "lift는 같은 카테고리 후보 풀 평균 대비 상승분이며 절대 품질이 아니다.",
        ],
    }


def _broad(category: str | None) -> set[str]:
    from demo_agent.recommender import CATEGORY_SPECS

    if category is None:
        return set()
    spec = CATEGORY_SPECS.get(category)
    return set(spec.broad_categories) if spec else set()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--top-k", type=int, default=30)
    parser.add_argument("--output", type=Path, default=REPORT_PATH)
    args = parser.parse_args()

    report = evaluate(args.top_k)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    summary = report["summary"]
    print(f"catalog            {report['catalog_products']:,} products")
    print(f"mean lift          {summary['mean_lift']:+.4f}  (min {summary['min_lift']:+.4f})")
    print(
        f"positive cases     {summary['positive_cases_with_lift']}/{summary['positive_cases_total']} with lift > 0"
    )
    print(
        f"negation direction {summary['negation_direction_correct']}/{summary['negation_cases_total']} correct"
        f"  (mean gap {summary['mean_negation_gap']:+.4f})"
    )
    print(f"category purity    {summary['mean_category_purity']:.4f}")
    print(f"max duplicate rate {summary['max_duplicate_rate']:.4f}")
    print(f"report             {args.output}")


if __name__ == "__main__":
    main()
