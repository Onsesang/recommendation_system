from __future__ import annotations

from pathlib import Path
from typing import Any


def write_markdown_report(path: Path, metrics: dict[str, Any]) -> None:
    k = metrics["k"]
    lines = [
        "# Offline Recommendation Evaluation",
        "",
        f"> 평가 case: {metrics['cases']} · candidate ranking · K={k}",
        "",
        "## Overall",
        "",
        f"| Model | Recall@{k} | Hit Rate@{k} | nDCG@{k} | MRR | Precision@{k} | MAP@{k} | Tactile Match@{k} | Tactile profile coverage | Tactile item coverage@{k} |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for name, result in metrics["models"].items():
        row = result["overall"]
        tactile = row[f"tactile_match@{k}"]
        tactile_text = "N/A" if tactile is None else f"{tactile:.6f} ({row['tactile_match_status']})"
        lines.append(
            f"| {name} | {row[f'recall@{k}']:.6f} | {row[f'hit_rate@{k}']:.6f} | "
            f"{row[f'ndcg@{k}']:.6f} | {row['mrr']:.6f} | "
            f"{row[f'precision@{k}']:.6f} | {row[f'map@{k}']:.6f} | {tactile_text} | "
            f"{row['tactile_profile_coverage']:.6f} | {row[f'tactile_item_coverage@{k}']:.6f} |"
        )
    lines.extend(
        [
            "",
            "## 해석 주의",
            "",
            "- 모든 모델은 저장된 동일 candidate set에서 평가한다.",
            "- Tactile Match는 coverage와 함께 해석한다. coverage가 낮은 높은 점수는 전체 추천 품질을 뜻하지 않는다.",
            "- 현재 소재 target은 추천 시점 이전 리뷰만으로 재구성한 것이 아니므로 tactile 결과는 진단용이다.",
            "- 최종 논문 결과에서는 global time cutoff 이전 리뷰로 item target을 다시 만들어야 한다.",
            "",
            "## Cohort",
            "",
        ]
    )
    for model, result in metrics["models"].items():
        lines.extend([f"### {model}: target item cohort", ""])
        for cohort, row in result["by_target_item_cohort"].items():
            lines.append(
                f"- `{cohort}`: n={row['cases']}, Recall@{k}={row[f'recall@{k}']:.6f}, "
                f"nDCG@{k}={row[f'ndcg@{k}']:.6f}, MRR={row['mrr']:.6f}"
            )
        lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
