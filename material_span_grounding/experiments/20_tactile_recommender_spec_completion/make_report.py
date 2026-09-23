"""Build the final Exp20 markdown report from locked artifacts."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from common import ART, CONFIG, ROOT, event, load_json, save_json, sha


VARIANT_ORDER = ["I", "I_T", "I_VX", "I_VX_T", "I_VX_T_SHUFFLE"]


def fmt(value, digits: int = 6) -> str:
    if value is None:
        return "N/A"
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def metric_row(label: str, variant: str, result: dict) -> str:
    m = result["results"][variant]["test"]["all_official_targets"]
    budget = result["results"][variant].get("candidate_budget") or {}
    return (
        f"| {label} | {fmt(result['results'][variant]['selected_learning_rate'])} | "
        f"{result['results'][variant]['selected_epoch']} | {fmt(m['ndcg_at_10'])} | "
        f"{fmt(m['hr_at_10'])} | {fmt(m['mrr_at_10'])} | {fmt(m['recall_at_30000'])} | "
        f"{budget.get('k', 'N/A')} / {budget.get('status', 'N/A')} |"
    )


def main() -> None:
    selection = load_json(ART / "validation_selection.json")
    tests = load_json(ART / "test_results.json")
    lock = load_json(ART / "implementation_lock.json")
    graph = load_json(ART / "tactile_graph_report.json")
    manifest = load_json(ART / "input_manifest.json")
    state = load_json(ART / "protocol_state.json")
    cfg = load_json(CONFIG / "model_variants.json")
    val_csv = pd.read_csv(ART / "validation_results.csv")

    variant_names = {v["id"]: v["display_name"] for v in cfg["variants"]}
    lines: list[str] = []
    lines.append("# Experiment 20 — Tactile Recommender Spec Completion Final Report")
    lines.append("")
    lines.append("Generated from locked Exp20 artifacts. This report is intentionally conservative: Track A reuses the Amazon_Fashion official test split that was already opened during Exp16, so the result is a locked post-hoc exploratory follow-up, not a fresh confirmatory test.")
    lines.append("")
    lines.append("## Bottom line")
    lines.append("")
    primary = tests["contrasts"]["primary_I_VX_T_minus_I_VX"]
    aligned = tests["contrasts"]["aligned_tactile_minus_shuffle"]
    base = tests["results"]["I_VX"]["test"]["all_official_targets"]["ndcg_at_10"]
    proposed = tests["results"]["I_VX_T"]["test"]["all_official_targets"]["ndcg_at_10"]
    shuffle = tests["results"]["I_VX_T_SHUFFLE"]["test"]["all_official_targets"]["ndcg_at_10"]
    direction = "improved" if proposed > base else "did not improve"
    lines.append(
        f"The proposed true-in-model tactile variant `I_VX_T` {direction} over the generic multimodal control `I_VX` on exploratory test NDCG@10: "
        f"`{fmt(proposed)}` vs `{fmt(base)}` (delta `{fmt(primary['mean_delta_ndcg_at_10'])}`). "
        f"The shuffled tactile control scored `{fmt(shuffle)}`, making the aligned-vs-shuffled delta `{fmt(aligned['mean_delta_ndcg_at_10'])}`."
    )
    lines.append("")
    lines.append("## Scientific status")
    lines.append("")
    lines.append("- Track A status: `locked_posthoc_exploratory_followup`; confirmatory claims are forbidden because the Exp16 official test was already opened before Exp20.")
    lines.append("- No Exp20 test metric was used for training, learning-rate selection, epoch selection, candidate budget selection, class selection, graph construction, or architecture selection.")
    lines.append("- The test/report orchestration scripts were added after validation work began, but they only call the frozen `evaluate_exact()` metric implementation and locked checkpoints; no metric core or training/selection code was changed.")
    lines.append("")
    lines.append("## Test metrics")
    lines.append("")
    lines.append("| Variant | selected LR | selected epoch | NDCG@10 | HR@10 | MRR@10 | Recall@30000 | selected candidate budget |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|---|")
    for variant in VARIANT_ORDER:
        lines.append(metric_row(f"`{variant}` — {variant_names.get(variant, variant)}", variant, tests))
    lines.append("")
    lines.append("## Paired exploratory contrasts")
    lines.append("")
    lines.append("| Contrast | ΔNDCG@10 | mean rank improvement | median rank improvement | improved / worse / unchanged users | top10 gains / losses |")
    lines.append("|---|---:|---:|---:|---:|---:|")
    for contrast in ["primary_I_VX_T_minus_I_VX", "aligned_tactile_minus_shuffle", "tactile_ablation_I_T_minus_I"]:
        c = tests["contrasts"][contrast]
        lines.append(
            f"| `{contrast}` | {fmt(c['mean_delta_ndcg_at_10'])} | {fmt(c['mean_rank_improvement'], 3)} | "
            f"{fmt(c['median_rank_improvement'], 3)} | {c['improved_rank_users']} / {c['worse_rank_users']} / {c['unchanged_rank_users']} | "
            f"{c['top10_gain_users']} / {c['top10_loss_users']} |"
        )
    lines.append("")
    lines.append("## Validation selection")
    lines.append("")
    lines.append("| Variant | selected LR | selected epoch | validation NDCG@10 | validation Recall@30000 | checkpoint sha256 |")
    lines.append("|---|---:|---:|---:|---:|---|")
    for variant in VARIANT_ORDER:
        s = selection["model_selections"][variant]
        m = s["selected_run"]["validation"]["all_official_targets"]
        lines.append(
            f"| `{variant}` | {fmt(s['selected_learning_rate'])} | {s['selected_epoch']} | {fmt(m['ndcg_at_10'])} | {fmt(m['recall_at_30000'])} | `{s['checkpoint_sha256'][:16]}...` |"
        )
    lines.append("")
    lines.append("Full validation run table: `artifacts/validation_results.csv`.")
    lines.append("")
    lines.append("## Protocol and lock evidence")
    lines.append("")
    lines.append(f"- Protocol state: `{state['state']}`")
    lines.append(f"- Implementation lock sha256: `{sha(ART / 'implementation_lock.json')}`")
    lines.append(f"- Validation selection sha256: `{sha(ART / 'validation_selection.json')}`")
    lines.append(f"- Test results sha256: `{sha(ART / 'test_results.json')}`")
    lines.append(f"- Frozen protocol sha256 in lock: `{lock['protocol_sha256']}`")
    lines.append(f"- Frozen model-variants sha256 in lock: `{lock['model_variants_sha256']}`")
    lines.append(f"- Frozen input manifest sha256 in lock: `{lock['input_manifest_sha256']}`")
    lines.append(f"- Frozen metric source hashes include `models_exp20.py`: `{lock['metric_source_sha256']['models_exp20.py']}`")
    lines.append("")
    lines.append("## Tactile feature and graph provenance")
    lines.append("")
    audit = graph.get("audit", [{}])[0] if graph.get("audit") else {}
    lines.append(f"- Frozen input manifest entries: `{len(manifest.get('inputs', []))}`")
    lines.append(f"- Tactile graph artifact sha256: `{graph.get('graph', {}).get('sha256', sha(ROOT / 'data/tactile_adj_40_True.pt'))}`")
    lines.append(f"- Tactile graph selected nprobe: `{graph.get('selected_nprobe', graph.get('graph', {}).get('nprobe'))}`")
    lines.append(f"- Tactile graph exact-recall audit mean/min: `{audit.get('mean_recall_at_40')}` / `{audit.get('min_recall_at_40')}`")
    lines.append("")
    lines.append("## Limitations")
    lines.append("")
    lines.append("- This is not an official SMORE reproduction; it is a local, pinned Amazon_Fashion adaptation.")
    lines.append("- Dedicated tactile signal is interpreted only as incremental Last2 tactile information beyond generic image/text; generic visual/text features may already encode tactile cues implicitly.")
    lines.append("- Candidate retrieval recall did not reach the preregistered threshold for these sparse Amazon_Fashion settings, so the fallback full reported budget is retained where applicable.")
    lines.append("- Human preference/provenance work remains separate unless a prospective annotation protocol is frozen and executed before labels are opened.")
    lines.append("")
    lines.append("## Artifact inventory")
    lines.append("")
    lines.append("- `artifacts/test_results.json` — final exploratory test metrics and paired contrasts.")
    lines.append("- `artifacts/test_*_per_user.parquet` — per-target exact ranks for each selected variant.")
    lines.append("- `artifacts/validation_selection.json` — locked learning-rate/epoch/candidate-budget choices.")
    lines.append("- `artifacts/checkpoints/*.complete.json` and `*.pt` — selected and completed validation checkpoints.")
    lines.append("- `artifacts/events.jsonl` / `artifacts/notifications.jsonl` — execution and Discord notification audit trail.")
    lines.append("")

    out = ROOT / "notion" / "EXP20_TACTILE_RECOMMENDER_SPEC_COMPLETION_REPORT.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n")
    save_json(
        ART / "report_manifest.json",
        {
            "report": str(out),
            "report_sha256": sha(out),
            "test_results_sha256": sha(ART / "test_results.json"),
            "validation_selection_sha256": sha(ART / "validation_selection.json"),
            "rows_in_validation_results": int(len(val_csv)),
        },
    )
    event("exp20_report", "complete", report=str(out), report_sha256=sha(out))


if __name__ == "__main__":
    main()
