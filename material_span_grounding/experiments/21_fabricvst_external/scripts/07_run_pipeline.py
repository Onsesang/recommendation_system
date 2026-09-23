#!/usr/bin/env python3
"""Driver for the remaining stages, with exactly one Discord notification.

Runs aggregation -> training -> external evaluation -> final report. Sends a
single notification at the very end, whether the run succeeded or stopped on an
unrecoverable error. No intermediate stage notifies.
"""
from __future__ import annotations

import json
import subprocess
import sys
import traceback
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import notify  # noqa: E402
from common import ROOT, load_config  # noqa: E402

PYTHON = "/home/user/onsesang/miniconda3/envs/texture/bin/python"
SCRIPTS = ROOT / "scripts"
ENV = {"HF_HOME": "/home/user/onsesang/.cache/huggingface"}


def run(stage: str, argv: list[str]) -> None:
    import os

    environment = dict(os.environ)
    environment.update(ENV)
    print(f"\n===== {stage} =====", flush=True)
    process = subprocess.run(argv, env=environment, cwd=str(ROOT))
    if process.returncode != 0:
        raise RuntimeError(f"{stage} exited with code {process.returncode}")


def main() -> int:
    config = load_config()
    completed: list[str] = []
    last_output = str(ROOT / "results" / "fabricvst_last2_external")
    stage = "startup"
    try:
        stage = "qwen_pseudolabel_check"
        labels = ROOT / "artifacts" / "qwen_fabricvst_labels.jsonl"
        if not labels.is_file():
            raise RuntimeError("qwen_fabricvst_labels.jsonl missing; run 03 first")
        completed.append("qwen_pseudolabel")

        stage = "aggregate_labels"
        run(stage, [PYTHON, str(SCRIPTS / "04_aggregate_labels.py")])
        completed.append(stage)
        last_output = str(ROOT / "results" / "fabricvst_taxonomy_retraining")

        quality = json.loads(
            (ROOT / "results" / "fabricvst_taxonomy_retraining" / "label_quality_summary.json").read_text()
        )
        notify.part_complete(
            "PART B",
            "Qwen FabricVST-taxonomy pseudo-labelling complete",
            [
                f"reviews labelled: {quality.get('review_rows')}",
                f"reviews yielding no attribute: {quality.get('reviews_with_no_attribute')}",
                f"parse errors: {quality.get('parse_errors')}",
                f"evidence verbatim: {quality.get('evidence_verbatim_fraction')}",
                f"products with labels: {quality.get('products')}",
                f"sparse attributes: {len(quality.get('sparse_attributes_known_ratio_below_5pct') or [])}",
                f"severely skewed: {len(quality.get('severely_skewed_attributes') or [])}",
            ],
            str(ROOT / "results" / "fabricvst_taxonomy_retraining"),
        )

        for group in ("B_tactile_subset", "A_fabricvst_24"):
            stage = f"train_{group}"
            run(stage, [PYTHON, str(SCRIPTS / "05_train_fabricvst_model.py"), "--group", group])
            completed.append(stage)
            if group == "B_tactile_subset":
                # Preserve the primary model before the second group overwrites it.
                primary = ROOT / "checkpoints" / "fabricvst_taxonomy"
                for name in ("best.pt", "last.pt"):
                    source = primary / name
                    if source.is_file():
                        source.replace(primary / f"B_{name}")
        last_output = str(ROOT / "checkpoints" / "fabricvst_taxonomy")

        training_facts = []
        for group in ("B_tactile_subset", "A_fabricvst_24"):
            path = ROOT / "results" / "fabricvst_taxonomy_retraining" / f"internal_test_metrics_{group}.json"
            if path.is_file():
                report = json.loads(path.read_text())
                test = report.get("test", {})
                training_facts.append(
                    f"{group}: {len(report.get('attributes', []))} attrs, best epoch "
                    f"{report.get('best_epoch')}, internal test macro F1 "
                    f"{None if test.get('macro_f1') is None else round(test['macro_f1'], 4)}, "
                    f"macro AUROC {None if test.get('macro_auroc') is None else round(test['macro_auroc'], 4)}"
                )
        notify.part_complete(
            "PART C",
            "New multi-label tactile model trained",
            training_facts or ["training finished; no metrics file found"],
            str(ROOT / "results" / "fabricvst_taxonomy_retraining"),
        )

        stage = "external_evaluation"
        run(stage, [
            PYTHON, str(SCRIPTS / "06_eval_newmodel_external.py"),
            "--checkpoint", str(ROOT / "checkpoints" / "fabricvst_taxonomy" / "B_best.pt"),
        ])
        completed.append(stage)
        last_output = str(ROOT / "results" / "fabricvst_newmodel_external")

        stage = "final_report"
        run(stage, [PYTHON, str(SCRIPTS / "08_final_report.py")])
        completed.append(stage)

        old = json.loads((ROOT / "results" / "fabricvst_last2_external" / "overall_metrics.json").read_text())
        new = json.loads((ROOT / "results" / "fabricvst_newmodel_external" / "overall_metrics.json").read_text())
        old_exact = old["exact_all_fabrics"]
        new_cmp = new["comparable_all_fabrics"]

        def rounded(value):
            return None if value is None else round(value, 4)

        notify.success(
            lines=[
                "FabricVST downloaded and verified",
                "old last2 external evaluation completed",
                "Qwen FabricVST-taxonomy pseudo-labeling completed",
                "new multi-label tactile model trained",
                "FabricVST external evaluation completed (PART D)",
                "old vs new comparison completed",
                f"macro AUROC (the threshold-free measure): "
                f"last2 {rounded(old_exact.get('macro_auroc'))} -> "
                f"new {rounded(new_cmp.get('macro_auroc'))}",
                f"new model also covers "
                f"{new.get('full_coverage_all_fabrics', {}).get('n_attributes')} FabricVST "
                f"attributes last2 could not express",
            ],
            checkpoint=str(ROOT / "checkpoints" / "fabricvst_taxonomy" / "B_best.pt"),
            old_macro_f1=round(old["exact_all_fabrics"]["macro_f1"], 4),
            new_macro_f1=round(new["comparable_all_fabrics"]["macro_f1"], 4),
            results_dir=str(ROOT / "results"),
        )
        print("\npipeline complete", datetime.now().isoformat(timespec="seconds"))
        return 0
    except Exception as exc:  # noqa: BLE001 - final handler reports and exits
        traceback.print_exc()
        notify.failure(
            stage=stage,
            reason=f"{type(exc).__name__}: {exc}",
            completed=completed,
            last_output=last_output,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
