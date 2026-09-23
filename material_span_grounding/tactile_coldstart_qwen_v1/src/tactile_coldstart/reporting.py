from __future__ import annotations

import importlib.metadata
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import numpy as np

from .common import (
    PATHS, load_experiment, load_taxonomy, read_json, read_jsonl, sha256_file,
    utc_now, write_json,
)


def bootstrap_mean_ci(
    values: np.ndarray,
    samples: int,
    confidence: float,
    seed: int,
) -> tuple[float | None, float | None, float | None]:
    finite = np.asarray(values, dtype=float)
    finite = finite[np.isfinite(finite)]
    if not len(finite):
        return None, None, None
    rng = np.random.default_rng(seed)
    estimates = np.mean(rng.choice(finite, size=(samples, len(finite)), replace=True), axis=1)
    tail = (1.0 - confidence) / 2.0
    return float(np.mean(finite)), float(np.quantile(estimates, tail)), float(np.quantile(estimates, 1.0 - tail))


def _number(value: Any, digits: int = 3) -> str:
    return "—" if value is None else f"{float(value):.{digits}f}"


def _model_metric(models: dict[str, Any], axis: str, method: str) -> float | None:
    return models.get("summary", {}).get(axis, {}).get(method, {}).get("spearman_mean")


def _retrieval_metric(retrieval: dict[str, Any], method: str, metric: str = "ndcg@10") -> float | None:
    return retrieval.get("methods", {}).get(method, {}).get("overall", {}).get(metric)


def _hypotheses(
    models: dict[str, Any], external: dict[str, Any], selective: dict[str, Any], retrieval: dict[str, Any],
) -> list[dict[str, Any]]:
    margin = float(load_experiment()["reporting"]["hypothesis_margin"])
    axes = list(models.get("axes", []))
    structured = [value for axis in axes if (value := _model_metric(models, axis, "fashionclip_ridge")) is not None]
    category = [value for axis in axes if (value := _model_metric(models, axis, "category_only")) is not None]
    open_ndcg = _retrieval_metric(retrieval, "open_384d_current_split")
    structured_ndcg = _retrieval_metric(retrieval, "structured_no_abstention")
    h1_supported = (
        bool(structured) and bool(category)
        and float(np.mean(structured)) > float(np.mean(category)) + margin
        and open_ndcg is not None and structured_ndcg is not None and structured_ndcg > open_ndcg + margin
    )
    h1_available = bool(structured) and bool(category) and open_ndcg is not None and structured_ndcg is not None
    pairwise = [
        row.get("pairwise_accuracy")
        for row in external.get("mllm_fabric", {}).get("results", {}).values()
        if row.get("status") == "complete" and row.get("pairwise_accuracy") is not None
    ]
    h2_supported = bool(pairwise) and float(np.mean(pairwise)) > 0.5 + margin
    confidence_aurc = selective.get("methods", {}).get("confidence_only", {}).get("aurc")
    learned_aurc = selective.get("methods", {}).get("learned_calibrator", {}).get("aurc")
    h3_supported = confidence_aurc is not None and learned_aurc is not None and learned_aurc < confidence_aurc - margin
    learned_fixed = selective.get("methods", {}).get("learned_calibrator", {}).get("fixed_coverage", {})
    full_risk = learned_fixed.get("1.0", {}).get("test_risk_mae")
    selective_risk = learned_fixed.get("0.8", {}).get("test_risk_mae")
    selective_coverage = learned_fixed.get("0.8", {}).get("test_coverage", 0.0)
    h4_supported = (
        full_risk is not None and selective_risk is not None
        and selective_risk < full_risk - margin and float(selective_coverage) > 0.0
    )
    proposed_ndcg = _retrieval_metric(retrieval, "proposed_unknown_coverage_u2")
    h5_supported = (
        proposed_ndcg is not None and structured_ndcg is not None
        and proposed_ndcg > structured_ndcg + margin
    )
    return [
        {
            "id": "H1", "status": "supported" if h1_supported else ("falsified" if h1_available else "inconclusive"),
            "criterion": "structured FashionCLIP Ridge beats category-only on mean axis Spearman and current-split open-vector on retrieval NDCG@10",
            "evidence": {"structured_axis_mean": float(np.mean(structured)) if structured else None, "category_axis_mean": float(np.mean(category)) if category else None, "structured_ndcg@10": structured_ndcg, "open_vector_ndcg@10": open_ndcg},
        },
        {
            "id": "H2", "status": "supported" if h2_supported else ("falsified" if pairwise else "inconclusive"),
            "criterion": "mean compatible external pairwise accuracy exceeds random 0.5",
            "evidence": {"external_pairwise_mean": float(np.mean(pairwise)) if pairwise else None, "axes": len(pairwise)},
        },
        {
            "id": "H3", "status": "supported" if h3_supported else "falsified",
            "criterion": "generic recoverability+confidence calibrator has lower AURC than confidence-only",
            "evidence": {"confidence_only_aurc": confidence_aurc, "learned_calibrator_aurc": learned_aurc},
        },
        {
            "id": "H4", "status": "supported" if h4_supported else "falsified",
            "criterion": "validation-calibrated selective predictor reduces test MAE risk at nominal 80% coverage versus 100%",
            "evidence": {"full_risk": full_risk, "selective_risk": selective_risk, "actual_coverage": selective_coverage},
        },
        {
            "id": "H5", "status": "supported" if h5_supported else "falsified",
            "criterion": "UNKNOWN-aware proposed ranking beats forced structured prediction on cold-start NDCG@10",
            "evidence": {"forced_structured_ndcg@10": structured_ndcg, "proposed_ndcg@10": proposed_ndcg},
        },
    ]


def _run_tests() -> dict[str, Any]:
    environment = dict(os.environ)
    source_path = str(PATHS.root / "src")
    environment["PYTHONPATH"] = source_path + os.pathsep + environment.get("PYTHONPATH", "")
    command = [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"]
    completed = subprocess.run(
        command, cwd=PATHS.root, env=environment, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False,
    )
    log_path = PATHS.artifacts / "unit_test_log.txt"
    log_path.write_text(completed.stdout, encoding="utf-8")
    result = {
        "status": "passed" if completed.returncode == 0 else "failed",
        "return_code": completed.returncode,
        "command": command,
        "log": str(log_path),
        "log_sha256": sha256_file(log_path),
    }
    write_json(PATHS.artifacts / "unit_test_results.json", result)
    return result


def _git_commit() -> str | None:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=PATHS.root,
        text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=False,
    )
    return completed.stdout.strip() if completed.returncode == 0 else None


def _phase_inventory() -> list[dict[str, Any]]:
    inventory = []
    for path in sorted(PATHS.manifests.glob("phase*.json")):
        if path.name == "phase11_final.json":
            continue
        row = read_json(path)
        inventory.append(
            {
                "phase": row.get("phase"), "status": row.get("status"),
                "manifest": str(path), "sha256": sha256_file(path),
            }
        )
    def order(row: dict[str, Any]) -> tuple[float, str]:
        phase = row["phase"]
        if isinstance(phase, (int, float)):
            return float(phase), row["manifest"]
        if str(phase) == "6-7":
            return 6.5, row["manifest"]
        return 99.0, row["manifest"]
    return sorted(inventory, key=order)


def _bootstrap_retrieval(config: dict[str, Any]) -> dict[str, Any]:
    rows = read_jsonl(PATHS.artifacts / "coldstart_retrieval_per_query.jsonl")
    grouped: dict[str, list[float]] = {}
    for method in sorted({row["method"] for row in rows}):
        grouped[method] = [
            float(row["ndcg@10"]) for row in rows
            if row["method"] == method and row.get("ndcg@10") is not None
        ]
    output = {}
    for offset, (method, values) in enumerate(grouped.items()):
        mean, low, high = bootstrap_mean_ci(
            np.asarray(values), int(config["reporting"]["bootstrap_samples"]),
            float(config["reporting"]["confidence_level"]),
            int(config["experiment"]["seed"]) + offset,
        )
        output[method] = {"mean": mean, "ci_low": low, "ci_high": high, "queries": len(values)}
    return output


def _paired_retrieval_differences(config: dict[str, Any]) -> dict[str, Any]:
    rows = read_jsonl(PATHS.artifacts / "coldstart_retrieval_per_query.jsonl")
    by_method = {
        method: {row["query_id"]: row.get("ndcg@10") for row in rows if row["method"] == method}
        for method in {row["method"] for row in rows}
    }
    comparisons = [
        ("proposed_unknown_coverage_u2", "structured_no_abstention"),
        ("proposed_unknown_coverage_u2", "confidence_selective_u0"),
        ("structured_no_abstention", "open_384d_current_split"),
    ]
    output = {}
    for offset, (left, right) in enumerate(comparisons):
        common = sorted(set(by_method.get(left, {})) & set(by_method.get(right, {})))
        differences = np.asarray(
            [float(by_method[left][key]) - float(by_method[right][key]) for key in common if by_method[left][key] is not None and by_method[right][key] is not None],
            dtype=float,
        )
        mean, low, high = bootstrap_mean_ci(
            differences, int(config["reporting"]["bootstrap_samples"]),
            float(config["reporting"]["confidence_level"]),
            int(config["experiment"]["seed"]) + 100 + offset,
        )
        output[f"{left}_minus_{right}"] = {
            "mean_difference": mean, "ci_low": low, "ci_high": high,
            "paired_queries": int(len(differences)),
            "win_rate": float(np.mean(differences > 0)) if len(differences) else None,
        }
    return output


def run_final_reporting() -> dict[str, Any]:
    config = load_experiment()
    taxonomy = load_taxonomy()
    diagnostics = read_json(PATHS.artifacts / "active_axes.json")
    stats = read_json(PATHS.artifacts / "tactile_axis_stats.json")
    models = read_json(PATHS.artifacts / "phase6_7_model_results.json")
    external = read_json(PATHS.artifacts / "external_transfer_results.json")
    selective = read_json(PATHS.artifacts / "phase9_selective_results.json")
    retrieval = read_json(PATHS.artifacts / "phase10_retrieval_results.json")
    hypotheses = _hypotheses(models, external, selective, retrieval)
    bootstrap = _bootstrap_retrieval(config)
    paired_retrieval = _paired_retrieval_differences(config)
    tests = _run_tests()
    package_versions = {}
    for package in ("numpy", "scipy", "scikit-learn", "torch", "transformers", "sentence-transformers", "joblib", "PyYAML"):
        try:
            package_versions[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            package_versions[package] = None
    environment = {
        "python": sys.version,
        "packages": package_versions,
    }
    result_path = PATHS.artifacts / "phase11_paper_results.json"
    result = {
        "status": "complete" if tests["status"] == "passed" else "complete_with_test_failure",
        "phase": 11, "generated_at": utc_now(),
        "hypotheses": hypotheses,
        "bootstrap_ndcg@10": bootstrap,
        "paired_retrieval_ndcg@10": paired_retrieval,
        "active_axes": diagnostics["active_axes"],
        "axis_stats": stats,
        "model_summary": models["summary"],
        "vlm_zero_shot_summary": models.get("vlm_zero_shot"),
        "external_summary": external,
        "selective_summary": {method: {key: value for key, value in row.items() if key != "risk_coverage_curve"} for method, row in selective["methods"].items()},
        "retrieval_summary": retrieval,
        "test_results": tests,
        "environment": environment,
        "git_commit": _git_commit(),
        "protocol_limitations": [
            "The current Amazon family splits are feasibility splits and not a never-inspected final test set.",
            "Human-audit rows were exported, but human annotation was not fabricated; pseudo-label quality metrics remain pending.",
            "Leeds raw image-plus-rating access/licensing was not verified, so Leeds was reported unavailable.",
            "Qwen VLM zero-shot uses symbolic image-only axis scores with explicit abstention; it is not a direct prompt-to-ranked-list evaluator.",
            "Held-out reviews are subjective selective evidence, never described as physical tactile ground truth.",
        ],
    }
    write_json(result_path, result)
    _write_paper_report(result, taxonomy)
    _write_notion_report(result, taxonomy)
    paper_path = PATHS.reports / "phase11_full_ablation.md"
    notion_path = PATHS.notion / "TACTILE_COLDSTART_PHASE_0_TO_11.md"
    manifest = {
        "status": result["status"], "phase": 11, "generated_at": utc_now(),
        "git_commit": result["git_commit"],
        "config": config, "taxonomy_version": taxonomy["version"],
        "config_sha256": sha256_file(PATHS.configs / "experiment.yaml"),
        "taxonomy_sha256": sha256_file(PATHS.configs / "tactile_axes.yaml"),
        "tests": tests,
        "prior_phase_manifests": _phase_inventory(),
        "outputs": {
            "machine_results": str(result_path), "machine_results_sha256": sha256_file(result_path),
            "paper_report": str(paper_path), "paper_report_sha256": sha256_file(paper_path),
            "notion_report": str(notion_path), "notion_report_sha256": sha256_file(notion_path),
        },
    }
    write_json(PATHS.manifests / "phase11_final.json", manifest)
    return manifest


def _write_paper_report(result: dict[str, Any], taxonomy: dict[str, Any]) -> None:
    axes = result["active_axes"]
    method_rows = [
        "category_only", "dino_ridge", "fashionclip_linear", "fashionclip_ridge",
        "image_category_ridge", "ordinal", "pairwise", "tiny_mlp",
    ]
    lines = [
        "# Phase 11 — Full Ablations and Paper Tables", "",
        "## Image prediction (Spearman mean over family splits)", "",
        "| Method | " + " | ".join(axes) + " |",
        "|---|" + "---:|" * len(axes),
    ]
    for method in method_rows:
        values = [_model_metric({"summary": result["model_summary"]}, axis, method) for axis in axes]
        lines.append("| " + method + " | " + " | ".join(_number(value) for value in values) + " |")
    vlm = (result.get("vlm_zero_shot_summary") or {}).get("results", {})
    lines.extend([
        "", "## Qwen VLM image-only zero-shot (visually assessable pairs only)", "",
        "| Axis | Samples | Spearman | MAE | Direction accuracy |",
        "|---|---:|---:|---:|---:|",
    ])
    for axis in axes:
        values = vlm.get(axis, {})
        lines.append(
            f"| {axis} | {values.get('samples', 0)} | {_number(values.get('spearman'))} | "
            f"{_number(values.get('mae'))} | {_number(values.get('direction_accuracy'))} |"
        )
    lines.extend(["", "## Selective prediction", "", "| Method | AURC ↓ |", "|---|---:|"])
    for method, values in result["selective_summary"].items():
        lines.append(f"| {method} | {_number(values.get('aurc'))} |")
    lines.extend(["", "## Cold-start retrieval", "", "| Method | NDCG@10 | 95% bootstrap CI |", "|---|---:|---:|"])
    for method, values in result["bootstrap_ndcg@10"].items():
        interval = "—" if values["ci_low"] is None else f"[{values['ci_low']:.3f}, {values['ci_high']:.3f}]"
        lines.append(f"| {method} | {_number(values['mean'])} | {interval} |")
    lines.extend(["", "## Paired query bootstrap differences (NDCG@10)", "", "| Comparison | Mean difference | 95% CI | Win rate |", "|---|---:|---:|---:|"])
    for comparison, values in result["paired_retrieval_ndcg@10"].items():
        interval = "—" if values["ci_low"] is None else f"[{values['ci_low']:.3f}, {values['ci_high']:.3f}]"
        lines.append(f"| {comparison} | {_number(values['mean_difference'])} | {interval} | {_number(values['win_rate'])} |")
    lines.extend(["", "## Falsifiable hypotheses", "", "| Hypothesis | Status | Evidence |", "|---|---|---|"])
    for row in result["hypotheses"]:
        lines.append(f"| {row['id']} | {row['status']} | `{json.dumps(row['evidence'], ensure_ascii=False)}` |")
    lines.extend(["", "## Limitations", ""] + [f"- {value}" for value in result["protocol_limitations"]])
    (PATHS.reports / "phase11_full_ablation.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_notion_report(result: dict[str, Any], taxonomy: dict[str, Any]) -> None:
    by_stats = {row["axis_id"]: row for row in result["axis_stats"]}
    by_axis = {row["id"]: row for row in taxonomy["axes"]}
    lines = [
        "# Review-Cold-Start Tactile Retrieval — Phase 0~11 실행 문서", "",
        "## 실행 결론", "",
        "이 문서는 buyer review의 선택적·주관적 tactile evidence를 구조화한 뒤, review가 없는 상품 이미지에 선택적으로 전이하는 feasibility 실험의 전체 기록이다. REVIEW_UNOBSERVED, reviewer disagreement, VISUAL_ABSTAIN은 서로 다른 상태로 유지했다.", "",
        "## Phase 3 축 구성과 실제 관측 결과", "",
        "축은 아래의 두 pole을 가진 bipolar ordinal 구조다. Qwen은 pole과 강도만 기호로 출력하고 수치는 설정의 결정론적 변환과 reviewer-first aggregation 뒤에 생성된다. 축은 문헌만 보고 고정하지 않고 Phase 3의 span/product/pole/reviewer/category 기준을 모두 통과한 경우에만 active로 선택했다.", "",
    ]
    for axis_id, axis in by_axis.items():
        stat = by_stats[axis_id]
        failed = [key for key, value in stat["selection_checks"].items() if not value]
        lines.extend(
            [
                f"### {axis['display_name']} (`{axis_id}`)", "",
                f"- 축: `{axis['negative_pole']}` ↔ `{axis['positive_pole']}`",
                f"- 의미: {axis['definition']}",
                f"- 결과: mapped span {stat['mapped_spans']:,}, product {stat['unique_products']:,}, ≥2 reviewers product {stat['products_ge_2_reviewers']:,}, REVIEW_UNOBSERVED {stat['review_unobserved_rate']:.1%}",
                f"- pole별 product: `{stat['pole_product_distribution']}`",
                f"- category 집중도: {stat['top_category_fraction']:.1%}",
                f"- 선택: **{'ACTIVE' if stat['selected'] else 'INACTIVE'}**" + (f" (미통과: {', '.join(failed)})" if failed else " (모든 정량 기준 통과)"),
                "",
            ]
        )
    lines.extend(["## Phase별 수행 내용", ""])
    phases = [
        (0, "저장소·schema·Qwen checkpoint·embedding·family split을 감사하고 누수 경계를 동결"),
        (1, "7개 후보 축과 ordinal coding을 YAML로 선언하고 source code의 축별 분기를 제거"),
        (2, "기존 Qwen3-VL-8B-Instruct로 4,527 accepted span을 단일 taxonomy prompt에 grounding"),
        (3, "coverage/MNAR/extreme/category/reviewer diagnostics 후 active axis 자동 선택"),
        (4, "600개 stratified human audit sheet 생성; 사람 label은 비워 두고 미완료를 명시"),
        (5, "reviewer-first product target, 분포·support·agreement·mask 생성"),
        (6, "category/FashionCLIP/image+category/MLP/open-vector baseline 평가"),
        (7, "masked regression·ordinal·pairwise 및 W0~W3/강도·support robustness 비교"),
        (8, "MLLM-Fabric 220 RGB 외부 전이 평가; Leeds 접근 불가를 그대로 보고"),
        (9, "bootstrap instance uncertainty와 external property recoverability를 분리해 risk-coverage calibration"),
        (10, "hidden test-review relevance로 same-category cold-start retrieval과 UNKNOWN 정책 평가"),
        (11, "seed 평균·bootstrap CI·가설 기각 기준·재현 manifest·전체 테스트를 통합"),
    ]
    for phase, description in phases:
        lines.append(f"- **Phase {phase}:** {description}")
    lines.extend(["", "## 가설 판정", ""])
    for row in result["hypotheses"]:
        lines.append(f"- **{row['id']} — {row['status']}**: {row['criterion']}. Evidence: `{json.dumps(row['evidence'], ensure_ascii=False)}`")
    lines.extend(["", "## 해석 제한", ""] + [f"- {value}" for value in result["protocol_limitations"]])
    (PATHS.notion / "TACTILE_COLDSTART_PHASE_0_TO_11.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
