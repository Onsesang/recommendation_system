#!/usr/bin/env python3
"""Assemble FINAL_REPORT.md from the artifacts each stage wrote."""
from __future__ import annotations

import csv
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import ROOT, load_config  # noqa: E402


def read_json(path: Path):
    return json.loads(path.read_text()) if path.is_file() else None


def read_csv(path: Path) -> list[dict]:
    return list(csv.DictReader(path.open())) if path.is_file() else []


def fmt(value, digits: int = 4) -> str:
    if value is None or value == "":
        return "n/a"
    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return str(value)


def main() -> int:
    config = load_config()
    audit = read_json(ROOT / "artifacts" / "fabricvst_audit.json") or {}
    old = read_json(ROOT / "results" / "fabricvst_last2_external" / "overall_metrics.json") or {}
    new = read_json(ROOT / "results" / "fabricvst_newmodel_external" / "overall_metrics.json") or {}
    quality = read_json(ROOT / "results" / "fabricvst_taxonomy_retraining" / "label_quality_summary.json") or {}
    internal_b = read_json(ROOT / "results" / "fabricvst_taxonomy_retraining" / "internal_test_metrics_B_tactile_subset.json") or {}
    internal_a = read_json(ROOT / "results" / "fabricvst_taxonomy_retraining" / "internal_test_metrics_A_fabricvst_24.json") or {}
    distribution = read_csv(ROOT / "results" / "fabricvst_taxonomy_retraining" / "qwen_label_distribution.csv")
    comparison = read_csv(ROOT / "results" / "fabricvst_newmodel_external" / "model_comparison.csv")
    old_per = read_csv(ROOT / "results" / "fabricvst_last2_external" / "per_attribute_metrics_exact_all_fabrics.csv")
    mapping = read_csv(ROOT / "results" / "fabricvst_last2_external" / "mapping.csv")

    try:
        packages = subprocess.run(
            ["/home/user/onsesang/miniconda3/envs/texture/bin/pip", "freeze"],
            capture_output=True, text=True, timeout=120,
        ).stdout.splitlines()
        versions = [line for line in packages if line.split("==")[0].lower() in {
            "torch", "transformers", "numpy", "scikit-learn", "pillow", "accelerate", "bitsandbytes"
        }]
    except Exception:  # noqa: BLE001
        versions = []

    lines: list[str] = []
    add = lines.append

    add("# FabricVST external validation and taxonomy retraining")
    add("")
    add(f"Generated {datetime.now().isoformat(timespec='seconds')}.")
    add("")
    add("All numbers below are fabric-level unless stated otherwise. FabricVST was")
    add("never used to train, fine-tune, threshold or calibrate any model.")
    add("")

    # ---- 1 ---------------------------------------------------------------
    add("## 1. FabricVST")
    add("")
    add(f"- Source: {config['fabricvst']['source_page']}")
    add(f"- Paper: {config['fabricvst']['paper']}")
    add(f"- Archive: `RAS_dataset.zip`, {config['fabricvst']['archive_bytes']:,} bytes")
    add(f"- Downloaded path: `{config['fabricvst']['root']}`")
    inventory = audit.get("image_inventory", {})
    for kind, info in inventory.items():
        add(f"- `{kind}/`: {info['n_fabrics']} fabrics, {info['total_images']} images "
            f"({info['min_per_fabric']}-{info['max_per_fabric']} per fabric)")
    add(f"- Fabrics: {audit.get('n_materials_in_annotations')}")
    add(f"- Attributes: {len(audit.get('attribute_vocabulary', []))} "
        f"({', '.join(audit.get('attribute_vocabulary', [])[:8])}, ...)")
    add(f"- Annotators: {len(audit.get('annotator_files', {}))}, all voting on every cell; "
        f"unanimous on {fmt(audit.get('annotator_unanimous_fraction'), 4)} of cells")
    add(f"- Aggregation: {audit.get('aggregation_rule')}")
    add(f"- Official split file present: {audit.get('split_files_found') != [] }")
    add("")
    add("The dataset ships no train/validation/test split file, so the paper's 40/5/5")
    add("fabric split could not be loaded. Because no model here is trained on")
    add("FabricVST, every fabric is held out, and all 50 fabrics form the primary")
    add("evaluation set. A deterministic 40/5/5 stand-in is recorded in")
    add("`splits/fabricvst_fabric_split.json` and reported only as a secondary view;")
    add("with 5 fabrics its per-attribute metrics rest on 5 labels and are noise.")
    add("")

    # ---- 2 ---------------------------------------------------------------
    add("## 2. Existing last2")
    add("")
    add(f"- Checkpoint: `{config['last2']['checkpoint']}`")
    add("- Architecture: FashionCLIP vision encoder -> visual projection -> L2 normalise")
    add("  -> single linear head, sigmoid multi-label over 14 classes; last 2 transformer")
    add("  blocks plus post-layernorm and projection fine-tuned.")
    add(f"- Original taxonomy: {', '.join(config['last2']['classes'])}")
    add("- Thresholds: taken from the checkpoint, selected on our own development")
    add("  split, reused unchanged on FabricVST.")
    add("")
    add("### Mapping to FabricVST")
    add("")
    add("| FabricVST attribute | last2 output | mapping | reason |")
    add("| --- | --- | --- | --- |")
    for row in mapping:
        if row["mapping"] == "unavailable":
            continue
        add(f"| {row['fabricvst_attribute']} | {row['last2_output']} | {row['mapping']} | {row['reason']} |")
    unavailable = [row["fabricvst_attribute"] for row in mapping if row["mapping"] == "unavailable"]
    add("")
    add(f"Unavailable ({len(unavailable)}): {', '.join(unavailable)}.")
    add("")
    add("`firm` was deliberately not mapped onto FabricVST `stiff`: in the last2")
    add("taxonomy `firm` is the exclusive antonym of `soft`, a different axis from")
    add("`stiff`/`flexible`. `flexible` was likewise not mapped onto `stretchable`.")
    add("")

    # ---- 3 ---------------------------------------------------------------
    add("### External evaluation of last2")
    add("")
    if old:
        exact = old.get("exact_all_fabrics", {})
        add(f"Exact mappings, all 50 fabrics (n_attributes={exact.get('n_attributes')}):")
        add("")
        add("| metric | value |")
        add("| --- | ---: |")
        for key in ("macro_f1", "micro_f1", "macro_precision", "macro_recall",
                    "macro_balanced_accuracy", "macro_auroc", "macro_average_precision"):
            add(f"| {key} | {fmt(exact.get(key))} |")
        add("")
        add("| attribute | last2 class | F1 | precision | recall | AUROC | positives/50 |")
        add("| --- | --- | ---: | ---: | ---: | ---: | ---: |")
        for row in old_per:
            add(f"| {row['attribute']} | {row['last2_class']} | {fmt(row['f1'],3)} | "
                f"{fmt(row['precision'],3)} | {fmt(row['recall'],3)} | {fmt(row.get('auroc'),3)} | "
                f"{row['positive']}/{row['support']} |")
        add("")
        add("The F1 column overstates the model. Recall reaches 1.000 on several")
        add("attributes because the transferred thresholds place nearly every fabric")
        add("above the positive boundary, so F1 collapses onto the base rate, while")
        add("`cool` shows the mirror failure. Threshold-free AUROC is the honest")
        add("signal and sits near chance.")
    add("")

    # ---- 4 ---------------------------------------------------------------
    add("## 3. Qwen pseudo-label rebuilding")
    add("")
    qcfg = config["retraining"]["qwen"]
    add(f"- Model: {qcfg['model_id']} revision `{qcfg['revision']}`, {qcfg['quantization']}, greedy decoding")
    add(f"- Prompt: `prompts/fabricvst_tactile_pseudolabel.md` (version `fabricvst_tactile_pseudolabel_v1`)")
    add(f"- Reviews labelled: {quality.get('review_rows')}")
    add(f"- Reviews yielding no attribute: {quality.get('reviews_with_no_attribute')}")
    add(f"- Parse errors: {quality.get('parse_errors')}")
    add(f"- Evidence spans verbatim in the review: {fmt(quality.get('evidence_verbatim_fraction'), 4)}")
    add(f"- Products: {quality.get('products')} ({quality.get('products_with_image')} with an image)")
    add(f"- Aggregation rule: {json.dumps(quality.get('aggregation_rule', {}))}")
    add("")
    add("Labelling ran from raw review text against the 24 FabricVST attributes with")
    add("positive / negative / unknown states; the old 14-class pseudo-labels were not")
    add("converted. Reviews containing no material vocabulary at all were not sent to")
    add("Qwen and are treated as all-unknown, which is the supervision they would have")
    add("contributed anyway; the filter is applied identically across all splits.")
    add("")
    if distribution:
        add("| attribute | known ratio | positive ratio (known) | product P | product N | product U |")
        add("| --- | ---: | ---: | ---: | ---: | ---: |")
        for row in distribution:
            add(f"| {row['attribute']} | {fmt(row['known_ratio'],3)} | "
                f"{fmt(row['positive_ratio_among_known'],3)} | {row['product_positive']} | "
                f"{row['product_negative']} | {row['product_unknown']} |")
        add("")
    sparse = quality.get("sparse_attributes_known_ratio_below_5pct") or []
    skewed = quality.get("severely_skewed_attributes") or []
    if sparse:
        add(f"Sparse attributes (known on under 5 % of products): {', '.join(sparse)}.")
    if skewed:
        add(f"Severely skewed attributes: {', '.join(skewed)}.")
    add("")

    # ---- 5 ---------------------------------------------------------------
    add("## 4. New image model")
    add("")
    if internal_b:
        add(f"- Encoder: {config['fashionclip']['model_id']} revision `{config['fashionclip']['revision']}`")
        add(f"- Regime: {internal_b.get('regime')} (identical to last2)")
        add("- Head: single linear layer, independent sigmoid per attribute")
        add("- Loss: BCEWithLogits with per-attribute `pos_weight` from the training split,")
        add("  masked so `unknown` contributes no gradient")
        add(f"- Attribute group B (tactile subset): {len(internal_b.get('attributes', []))} attributes")
        add(f"- Split (product-level, family-disjoint): {json.dumps(internal_b.get('split_counts', {}))}")
        add(f"- Best epoch: {internal_b.get('best_epoch')}, seed {internal_b.get('seed')}")
        add("")
        test = internal_b.get("test", {})
        add("Internal held-out test (our own review-image data):")
        add("")
        add("| metric | group B | group A |")
        add("| --- | ---: | ---: |")
        for key in ("macro_f1", "micro_f1", "macro_precision", "macro_recall", "macro_auroc", "mean_average_precision"):
            add(f"| {key} | {fmt(test.get(key))} | {fmt((internal_a.get('test') or {}).get(key))} |")
        add("")

    # ---- 6 ---------------------------------------------------------------
    add("## 5. FabricVST external evaluation: old vs new")
    add("")
    if new and old:
        overall = new.get("model_comparison_overall", {})
        add("| Model | Macro F1 | Micro F1 | mAP | Macro Recall | Macro AUROC |")
        add("| --- | ---: | ---: | ---: | ---: | ---: |")
        for label, key in (("old last2", "old_last2"), ("FabricVST-taxonomy retrained", "new_model")):
            row = overall.get(key, {})
            add(f"| {label} | {fmt(row.get('macro_f1'))} | {fmt(row.get('micro_f1'))} | "
                f"{fmt(row.get('macro_average_precision'))} | {fmt(row.get('macro_recall'))} | "
                f"{fmt(row.get('macro_auroc'))} |")
        add("")
        full = new.get("full_coverage_all_fabrics", {})
        add(f"The retrained model additionally covers {full.get('n_attributes')} FabricVST")
        add(f"attributes directly (macro F1 {fmt(full.get('macro_f1'))}, macro AUROC "
            f"{fmt(full.get('macro_auroc'))}), which last2 could not express at all.")
        add("")
    if comparison:
        add("## 6. Attribute-level analysis")
        add("")
        add("| Attribute | old last2 F1 | new model F1 | difference | old AUROC | new AUROC | AUROC difference |")
        add("| --- | ---: | ---: | ---: | ---: | ---: | ---: |")
        for row in comparison:
            add(f"| {row['attribute']} | {fmt(row['old_last2_f1'],3)} | {fmt(row['new_model_f1'],3)} | "
                f"{fmt(row['f1_difference'],3)} | {fmt(row['old_last2_auroc'],3)} | "
                f"{fmt(row['new_model_auroc'],3)} | {fmt(row['auroc_difference'],3)} |")
        add("")

    # ---- 7 ---------------------------------------------------------------
    add("## 7. Conclusion")
    add("")
    exact = old.get("exact_all_fabrics", {}) if old else {}
    new_cmp = new.get("comparable_all_fabrics", {}) if new else {}
    old_auroc = exact.get("macro_auroc")
    new_auroc = new_cmp.get("macro_auroc")
    add(f"1. **Does last2 generalise to external fabrics?** Macro AUROC "
        f"{fmt(old_auroc)} across the eight exactly-mapped attributes, against 0.5 for")
    add("   chance. It does not generalise in any usable sense: the decision thresholds")
    add("   do not transfer, and the ranking signal is close to chance.")
    if new_auroc is not None and old_auroc is not None:
        direction = "improved" if new_auroc > old_auroc else "did not improve"
        add(f"2. **Did FabricVST-aligned retraining help?** Macro AUROC moved from "
            f"{fmt(old_auroc)} to {fmt(new_auroc)}, so retraining {direction} external")
        add("   ranking quality on the same fabrics and the same labels.")
    add("3. **Can this be presented as external validation?** Yes as a negative or")
    add("   partial result, stated carefully. The honest claim is about whether")
    add("   review-grounded tactile supervision transfers to an independent fabric")
    add("   dataset, not about achieving competitive FabricVST numbers. Fabric-level")
    add("   n is 50, the label source is 5 human annotators, and the image domain")
    add("   differs sharply from catalogue photography; conclusions should be framed")
    add("   as evidence about transfer, not as a benchmark result.")
    add("")
    add("### Claims that are NOT supported")
    add("")
    add("- That either model predicts tactile attributes reliably on external fabrics.")
    add("- That high F1 on `soft`, `rough` or `warm` reflects skill; those values track")
    add("  the base rate under saturated predictions.")
    add("- Any per-attribute conclusion from the 5-fabric paper-style test subset.")
    add("")

    # ---- 8 ---------------------------------------------------------------
    add("## 8. Reproducibility")
    add("")
    add("```bash")
    add("export HF_HOME=/home/user/onsesang/.cache/huggingface")
    add("cd /home/user/onsesang/material_span_grounding/experiments/21_fabricvst_external")
    add("PY=/home/user/onsesang/miniconda3/envs/texture/bin/python")
    add("$PY scripts/01_analyze_fabricvst.py")
    add("$PY scripts/02_eval_last2_external.py")
    add("$PY scripts/03a_build_candidate_pool.py")
    add("$PY scripts/03_qwen_pseudolabel.py --pool selected --batch-size 96")
    add("$PY scripts/07_run_pipeline.py   # aggregation, training, external eval, report")
    add("```")
    add("")
    add(f"- Seed: {config['seed']}")
    add(f"- Split IDs: `splits/` (product split inherited from `{config['retraining']['split_manifest']}`)")
    add(f"- FabricVST source: {config['fabricvst']['source_page']}")
    add(f"- Qwen prompt: `prompts/fabricvst_tactile_pseudolabel.md`")
    add(f"- Best checkpoint: `checkpoints/fabricvst_taxonomy/B_best.pt`")
    if versions:
        add("- Packages:")
        for line in versions:
            add(f"  - {line}")
    add("")
    add("The Discord webhook is read from `DISCORD_WEBHOOK_URL` and is never printed")
    add("or stored in this repository.")
    add("")

    (ROOT / "FINAL_REPORT.md").write_text("\n".join(lines) + "\n")
    print(f"wrote {ROOT / 'FINAL_REPORT.md'} ({len(lines)} lines)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
