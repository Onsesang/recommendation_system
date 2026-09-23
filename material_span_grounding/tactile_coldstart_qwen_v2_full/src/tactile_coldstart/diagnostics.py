from __future__ import annotations

import csv
import hashlib
import math
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from .common import (
    PATHS, axis_map, load_experiment, load_taxonomy, read_json, read_jsonl,
    sha256_file, symbolic_score, utc_now, write_json, write_jsonl,
)


def product_lookup(config: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    products = read_json(Path(config["inputs"]["product_master"]))
    lookup: dict[str, dict[str, Any]] = {}
    for row in products:
        for product_id in row.get("alias_product_ids", [row["product_id"]]):
            lookup[str(product_id)] = row
        lookup[str(row["product_id"])] = row
    return products, lookup


def enrich_groundings() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    config = load_experiment()
    products, lookup = product_lookup(config)
    enriched = []
    for row in read_jsonl(PATHS.artifacts / "axis_groundings.jsonl"):
        product = lookup.get(str(row["asin"]))
        if product is None:
            continue
        enriched.append(
            {
                **row,
                "family_id": str(product["product_id"]),
                "category": str(product["category"]),
                "reviewer_key": str(row.get("user_id") or f"missing:{row['review_id']}"),
            }
        )
    return products, enriched


def diagnostic_family_ids(config: dict[str, Any]) -> set[str]:
    """Return prediction-unit product IDs allowed for train-only diagnostics.

    The historical function name is retained for callers, but the split's
    ``splits`` field contains ASIN/product IDs. Parent-family IDs live in the
    separate ``families`` field and are counted by
    :func:`diagnostic_parent_family_ids`.
    """
    allowed_by_seed = []
    for seed in config["experiment"]["split_seeds"]:
        split = read_json(PATHS.manifests / f"family_split_{seed}.json")["splits"]
        allowed_by_seed.append(
            {
                str(product_id)
                for name in config["diagnostics"]["selection_splits"]
                for product_id in split[str(name)]
            }
        )
    policy = str(config["diagnostics"]["selection_seed_policy"])
    if policy == "intersection_across_all_evaluated_seeds":
        return set.intersection(*allowed_by_seed)
    if policy == "primary_seed_only":
        return allowed_by_seed[0]
    raise ValueError(f"Unsupported diagnostics.selection_seed_policy: {policy}")


def diagnostic_parent_family_ids(config: dict[str, Any]) -> set[str]:
    allowed_by_seed = []
    for seed in config["experiment"]["split_seeds"]:
        families = read_json(PATHS.manifests / f"family_split_{seed}.json")["families"]
        allowed_by_seed.append(
            {
                str(family_id)
                for name in config["diagnostics"]["selection_splits"]
                for family_id in families[str(name)]
            }
        )
    policy = str(config["diagnostics"]["selection_seed_policy"])
    if policy == "intersection_across_all_evaluated_seeds":
        return set.intersection(*allowed_by_seed)
    if policy == "primary_seed_only":
        return allowed_by_seed[0]
    raise ValueError(f"Unsupported diagnostics.selection_seed_policy: {policy}")


def _reviewer_axis_values(rows: list[dict[str, Any]], taxonomy: dict[str, Any]) -> dict[tuple[str, str, str], list[float]]:
    grouped: dict[tuple[str, str, str], list[float]] = defaultdict(list)
    for row in rows:
        if row.get("status") == "success" and row.get("mappable"):
            grouped[(row["family_id"], row["reviewer_key"], row["axis_id"])].append(
                symbolic_score(row, taxonomy)
            )
    return grouped


def _entropy(values: list[float], bins: list[float]) -> float:
    if not values:
        return 0.0
    counts = Counter(min(bins, key=lambda item: abs(item - value)) for value in values)
    probabilities = np.asarray(list(counts.values()), dtype=float) / len(values)
    return float(-(probabilities * np.log(probabilities)).sum())


def _category_dependence(product_values: list[tuple[str, float]]) -> float | None:
    if len(product_values) < 2:
        return None
    values = np.asarray([value for _, value in product_values], dtype=float)
    total = float(np.sum((values - values.mean()) ** 2))
    if total <= 1e-12:
        return 0.0
    by_category: dict[str, list[float]] = defaultdict(list)
    for category, value in product_values:
        by_category[category].append(value)
    between = sum(len(group) * (float(np.mean(group)) - float(values.mean())) ** 2 for group in by_category.values())
    return float(between / total)


def _safe_corr(left: list[float], right: list[float]) -> float | None:
    if len(left) < 3 or np.std(left) <= 1e-12 or np.std(right) <= 1e-12:
        return None
    return float(np.corrcoef(np.asarray(left, dtype=float), np.asarray(right, dtype=float))[0, 1])


def _plot_axis(axis_id: str, rows: list[dict[str, Any]], reviewer_values: list[float]) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    directions = Counter(str(row["direction"]) for row in rows)
    intensities = Counter(str(row["intensity"]) for row in rows)
    figure, axes = plt.subplots(1, 3, figsize=(13, 3.6))
    axes[0].bar(list(directions), list(directions.values()))
    axes[0].set_title("Direction")
    axes[0].tick_params(axis="x", rotation=30)
    axes[1].bar(list(intensities), list(intensities.values()))
    axes[1].set_title("Intensity")
    axes[1].tick_params(axis="x", rotation=30)
    axes[2].hist(reviewer_values, bins=np.arange(-2.5, 3.0, 0.5))
    axes[2].set_title("Reviewer-level ordinal value")
    figure.suptitle(axis_id)
    figure.tight_layout()
    figure.savefig(PATHS.plots / f"{axis_id}_diagnostics.png", dpi=150)
    plt.close(figure)


def run_diagnostics() -> dict[str, Any]:
    config = load_experiment()
    taxonomy = load_taxonomy()
    axes = axis_map(taxonomy)
    all_products, all_rows = enrich_groundings()
    allowed_families = diagnostic_family_ids(config)
    allowed_parent_families = diagnostic_parent_family_ids(config)
    products = [row for row in all_products if str(row["product_id"]) in allowed_families]
    rows = [row for row in all_rows if str(row["family_id"]) in allowed_families]
    if not rows:
        raise RuntimeError("No axis grounding outputs are available")
    successful = [row for row in rows if row.get("status") == "success"]
    mapped = [row for row in successful if row.get("mappable")]
    reviewer_groups = _reviewer_axis_values(mapped, taxonomy)
    bins = [float(value) for value in config["targets"]["score_bins"]]
    _, lookup = product_lookup(config)
    reviews = [
        row for row in read_jsonl(Path(config["inputs"]["reviews"]))
        if str(row["asin"]) in lookup and str(lookup[str(row["asin"])]["product_id"]) in allowed_families
    ]
    review_by_id = {str(row["review_id"]): row for row in reviews}
    review_mentions: dict[str, set[str]] = defaultdict(set)
    for row in mapped:
        review_mentions[str(row["axis_id"])].add(str(row["review_id"]))

    stats = []
    examples = []
    active_axes = []
    criteria = config["diagnostics"]
    for axis_id, axis in axes.items():
        axis_rows = [row for row in mapped if row["axis_id"] == axis_id]
        reviewers_by_product: dict[str, set[str]] = defaultdict(set)
        product_scores: dict[str, list[float]] = defaultdict(list)
        product_categories: dict[str, str] = {}
        for (family_id, reviewer, group_axis), values in reviewer_groups.items():
            if group_axis != axis_id:
                continue
            reviewers_by_product[family_id].add(reviewer)
            product_scores[family_id].append(float(np.mean(values)))
        for row in axis_rows:
            product_categories[row["family_id"]] = row["category"]
        product_means = {key: float(np.mean(values)) for key, values in product_scores.items()}
        category_counts = Counter(row["category"] for row in axis_rows)
        directions = Counter(str(row["direction"]) for row in axis_rows)
        intensities = Counter(str(row["intensity"]) for row in axis_rows)
        reviewer_values = [float(np.mean(values)) for key, values in reviewer_groups.items() if key[2] == axis_id]
        dispersions = [float(np.std(values)) for values in product_scores.values() if len(values) >= 2]
        entropies = [_entropy(values, bins) for values in product_scores.values() if len(values) >= 2]
        product_histogram = Counter(str(min(bins, key=lambda item: abs(item - value))) for value in product_means.values())
        pole_counts = {
            str(axis["negative_pole"]): directions.get(str(axis["negative_pole"]), 0),
            str(axis["positive_pole"]): directions.get(str(axis["positive_pole"]), 0),
        }
        pole_products = {
            pole: len({row["family_id"] for row in axis_rows if row["direction"] == pole})
            for pole in pole_counts
        }
        review_length, mention_flags, ratings, extreme_flags = [], [], [], []
        mentions = review_mentions[axis_id]
        extreme_threshold = max(abs(value) for value in bins)
        extreme_review_ids = {
            str(row["review_id"])
            for row in axis_rows
            if abs(symbolic_score(row, taxonomy)) >= extreme_threshold
        }
        years = Counter()
        for review in reviews:
            review_id = str(review["review_id"])
            review_length.append(float(review.get("text_chars") or len(str(review.get("text", "")))))
            mention_flags.append(float(review_id in mentions))
            ratings.append(float(review.get("rating") or 0.0))
            extreme_flags.append(float(review_id in extreme_review_ids))
            if review_id in mentions and review.get("timestamp"):
                years[str(datetime.fromtimestamp(float(review["timestamp"]) / 1000.0, tz=timezone.utc).year)] += 1
        category_target = [(product_categories[key], value) for key, value in product_means.items()]
        top_category_fraction = max(category_counts.values(), default=0) / max(sum(category_counts.values()), 1)
        mean_mapping_confidence = float(np.mean([float(row["confidence"]) for row in axis_rows])) if axis_rows else None
        pass_checks = {
            "mapped_spans": len(axis_rows) >= int(criteria["min_mapped_spans"]),
            "unique_products": len(product_scores) >= int(criteria["min_unique_products"]),
            "both_poles": min(pole_products.values(), default=0) >= int(criteria["min_products_per_pole"]),
            "multi_reviewer_products": sum(len(value) >= 2 for value in reviewers_by_product.values()) >= int(criteria["min_multi_reviewer_products"]),
            "category_concentration": top_category_fraction <= float(criteria["max_top_category_fraction"]),
            "semantic_mapping_confidence": mean_mapping_confidence is not None and mean_mapping_confidence >= float(criteria["min_mean_mapping_confidence"]),
            "external_validation_available": bool(set(axis["external_sources"]) & set(criteria["accessible_external_sources"])),
        }
        required_checks = dict(pass_checks)
        if not bool(criteria.get("external_validation_required_for_selection", False)):
            required_checks.pop("external_validation_available", None)
        selected = all(required_checks.values())
        if selected:
            active_axes.append(axis_id)
        stat = {
            "axis_id": axis_id,
            "mapped_spans": len(axis_rows),
            "reviews": len({row["review_id"] for row in axis_rows}),
            "unique_products": len(product_scores),
            "unique_reviewers": len({row["reviewer_key"] for row in axis_rows}),
            "products_ge_2_reviewers": sum(len(value) >= 2 for value in reviewers_by_product.values()),
            "products_ge_3_reviewers": sum(len(value) >= 3 for value in reviewers_by_product.values()),
            "review_unobserved_rate": 1.0 - len(product_scores) / len(products),
            "direction_distribution": dict(directions),
            "pole_product_distribution": pole_products,
            "intensity_distribution": dict(intensities),
            "product_target_histogram": dict(sorted(product_histogram.items())),
            "mean_product_dispersion": float(np.mean(dispersions)) if dispersions else None,
            "mean_reviewer_entropy": float(np.mean(entropies)) if entropies else None,
            "category_distribution": dict(category_counts),
            "material_composition_distribution": "unavailable_not_present_in_product_master",
            "top_category_fraction": top_category_fraction,
            "mean_mapping_confidence": mean_mapping_confidence,
            "category_target_eta_squared": _category_dependence(category_target),
            "review_length_mention_correlation": _safe_corr(review_length, mention_flags),
            "rating_mention_correlation": _safe_corr(ratings, mention_flags),
            "rating_extreme_correlation": _safe_corr(ratings, extreme_flags),
            "temporal_distribution": dict(sorted(years.items())),
            "selection_checks": pass_checks,
            "selection_required_checks": required_checks,
            "selected": selected,
        }
        stats.append(stat)
        _plot_axis(axis_id, axis_rows, reviewer_values)
        strata: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
        for row in axis_rows:
            strata[(str(row["direction"]), str(row["intensity"]))].append(row)
        for (direction, intensity), values in sorted(strata.items()):
            chosen = min(values, key=lambda row: hashlib.sha256(str(row["span_id"]).encode()).hexdigest())
            examples.append(
                {
                    "axis_id": axis_id,
                    "direction": direction,
                    "intensity": intensity,
                    "span_id": chosen["span_id"],
                    "quote": chosen["quote"],
                    "claim": chosen.get("claim", ""),
                    "reason": chosen.get("reason", ""),
                }
            )

    PATHS.artifacts.mkdir(parents=True, exist_ok=True)
    csv_path = PATHS.artifacts / "tactile_axis_stats.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        fields = [
            "axis_id", "mapped_spans", "reviews", "unique_products", "unique_reviewers",
            "products_ge_2_reviewers", "products_ge_3_reviewers", "review_unobserved_rate",
            "top_category_fraction", "mean_mapping_confidence", "category_target_eta_squared", "review_length_mention_correlation",
            "rating_mention_correlation", "rating_extreme_correlation", "selected",
        ]
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in stats:
            writer.writerow({key: row.get(key) for key in fields})
    write_json(PATHS.artifacts / "tactile_axis_stats.json", stats)
    write_jsonl(PATHS.artifacts / "axis_examples.jsonl", examples)
    decision = {
        "status": "complete",
        "phase": 3,
        "generated_at": utc_now(),
        "taxonomy_version": taxonomy["version"],
        "selection_splits": config["diagnostics"]["selection_splits"],
        "selection_seed_policy": config["diagnostics"]["selection_seed_policy"],
        "selection_product_count": len(allowed_families),
        "selection_family_count": len(allowed_parent_families),
        "test_reviews_used_for_axis_selection": False,
        "selection_criteria": criteria,
        "active_axes": active_axes,
        "inactive_axes": [axis_id for axis_id in axes if axis_id not in active_axes],
        "gate_passed": bool(active_axes),
        "unmappable_fraction_within_qwen_accepted": sum(not bool(row.get("mappable")) for row in successful) / max(len(successful), 1),
        "warning": "Selection is based on review-derived Qwen pseudo-label coverage, not physical tactile ground truth.",
        "semantic_separability_limitation": "Mean Qwen mapping confidence is only a proxy. Human axis-confusion validation was explicitly skipped and remains pending.",
        "human_validation_status": "skipped_by_user_pending",
    }
    write_json(PATHS.artifacts / "active_axes.json", decision)
    manifest = {
        **decision,
        "outputs": {
            "stats_csv": str(csv_path),
            "stats_csv_sha256": sha256_file(csv_path),
            "stats_json": str(PATHS.artifacts / "tactile_axis_stats.json"),
            "examples": str(PATHS.artifacts / "axis_examples.jsonl"),
            "plots": [str(PATHS.plots / f"{axis_id}_diagnostics.png") for axis_id in axes],
        },
    }
    _write_reports(stats, decision, taxonomy)
    report_path = PATHS.reports / "tactile_axis_diagnostics.md"
    notion_path = PATHS.notion / "PHASE_3_TACTILE_AXIS_FEASIBILITY.md"
    manifest["outputs"].update(
        {
            "report": str(report_path), "report_sha256": sha256_file(report_path),
            "notion_axis_explanation": str(notion_path),
            "notion_axis_explanation_sha256": sha256_file(notion_path),
        }
    )
    write_json(PATHS.manifests / "phase3_diagnostics.json", manifest)
    return manifest


def _format_number(value: Any, digits: int = 3) -> str:
    return "—" if value is None else f"{float(value):.{digits}f}"


def _write_reports(stats: list[dict[str, Any]], decision: dict[str, Any], taxonomy: dict[str, Any]) -> None:
    scope_policy = (
        "intersection across all evaluated seeds"
        if decision["selection_seed_policy"] == "intersection_across_all_evaluated_seeds"
        else "primary seed only"
    )
    rows = [
        "| Axis | Spans | Products | ≥2 reviewers | Missing | Pole products | Top category | Selected |",
        "|---|---:|---:|---:|---:|---|---:|:---:|",
    ]
    for stat in stats:
        poles = ", ".join(f"{key}={value}" for key, value in stat["pole_product_distribution"].items())
        rows.append(
            f"| {stat['axis_id']} | {stat['mapped_spans']} | {stat['unique_products']} | "
            f"{stat['products_ge_2_reviewers']} | {stat['review_unobserved_rate']:.1%} | {poles} | "
            f"{stat['top_category_fraction']:.1%} | {'Y' if stat['selected'] else 'N'} |"
        )
    report = "\n".join(
        [
            "# Phase 3 — Tactile Axis Feasibility Report",
            "",
            f"Active axes: `{', '.join(decision['active_axes']) or 'none'}`",
            f"Selection scope: `{', '.join(decision['selection_splits'])}` ({scope_policy}; "
            f"{decision['selection_product_count']} products / {decision['selection_family_count']} parent families); "
            "every evaluated test split remains hidden.",
            f"Unmappable among upstream Qwen-accepted claims: {decision['unmappable_fraction_within_qwen_accepted']:.1%}",
            "",
            *rows,
            "",
            "## Interpretation boundary",
            "",
            "No mention is REVIEW_UNOBSERVED, not neutral. Counts and distributions are based on Qwen pseudo-labels. "
            "Reviewer disagreement remains supervision and is not converted into UNKNOWN.",
            "Material composition diagnostics are unavailable because the frozen product master has no composition field.",
            decision["semantic_separability_limitation"],
        ]
    )
    (PATHS.reports / "tactile_axis_diagnostics.md").write_text(report + "\n", encoding="utf-8")

    by_axis = {row["axis_id"]: row for row in stats}
    sections = []
    for axis in taxonomy["axes"]:
        stat = by_axis[axis["id"]]
        failed = [key for key, passed in stat.get("selection_required_checks", stat["selection_checks"]).items() if not passed]
        sections.extend(
            [
                f"## {axis['display_name']} (`{axis['id']}`)",
                "",
                f"- 구성: `{axis['negative_pole']}` ↔ `{axis['positive_pole']}` bipolar ordinal axis",
                f"- 의미: {axis['definition']}",
                f"- 외부 검증 후보: {', '.join(axis['external_sources']) or '없음'}",
                f"- 관측 결과: span {stat['mapped_spans']:,}, 상품 {stat['unique_products']:,}, "
                f"독립 reviewer 2명 이상 상품 {stat['products_ge_2_reviewers']:,}",
                f"- REVIEW_UNOBSERVED: {stat['review_unobserved_rate']:.1%}",
                f"- pole별 상품: {stat['pole_product_distribution']}",
                f"- category-target 의존도(eta²): {_format_number(stat['category_target_eta_squared'])}",
                f"- 평균 Qwen mapping confidence: {_format_number(stat['mean_mapping_confidence'])}",
                f"- 결정: {'ACTIVE' if stat['selected'] else 'INACTIVE'}"
                + (f" — 미충족 기준: {', '.join(failed)}" if failed else " — 모든 사전 기준 충족"),
                "",
            ]
        )
    notion = "\n".join(
        [
            "# Review-Cold-Start 실험 Phase 3 — 촉감 축 구성 및 타당성",
            "",
            "> 이 문서는 Notion에 그대로 옮길 수 있는 Markdown 결과 문서다.",
            "",
            "## 축 구성 원칙",
            "",
            "각 축은 두 극을 가진 ordinal axis이며 UNKNOWN은 축의 class가 아니다. "
            "Qwen은 symbolic axis/pole/intensity만 출력하고 숫자값은 config가 결정한다. "
            "원문 exact span은 모든 레코드에 보존된다.",
            "",
            f"최종 active axes: `{', '.join(decision['active_axes']) or '없음'}`",
            "",
            *sections,
            "## 선택 결론",
            "",
            "축 선택은 review coverage, pole balance, 독립 reviewer 지원, category 집중도를 모두 통과한 경우에만 이뤄졌다. "
            "통계와 선택에는 모든 평가 seed에서 공통으로 train+development에 속한 family만 사용하며 어떤 seed의 test review도 사용하지 않았다. "
            "이 결정은 물리적 촉감 진실성이 아니라 이후 이미지 feasibility 실험을 수행할 최소 데이터 조건을 뜻한다.",
        ]
    )
    (PATHS.notion / "PHASE_3_TACTILE_AXIS_FEASIBILITY.md").write_text(notion + "\n", encoding="utf-8")
