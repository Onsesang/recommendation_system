#!/usr/bin/env python3
"""PART D - external evaluation of the retrained model on FabricVST.

The retrained model predicts FabricVST attribute names directly, so the mapping
is the identity on whatever attributes it was trained for. Its thresholds come
from our own development split and are used unchanged. The head-to-head table
against ``last2`` is restricted to the eight attributes that last2 could express
at all, so both models are scored on identical fabrics and identical labels.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

import numpy as np
import torch
from torch.utils.data import DataLoader
from transformers import AutoProcessor

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (  # noqa: E402
    ROOT,
    ImageListDataset,
    binary_metrics,
    build_model_from_checkpoint,
    fabric_split,
    load_config,
    predict_probabilities,
    summarise,
)

RESULTS = ROOT / "results" / "fabricvst_newmodel_external"


def write_table(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def evaluate(fabric_scores, values, mask, attributes, model_classes, thresholds, keep, names):
    per_attribute: dict[str, dict] = {}
    for name in names:
        if name not in model_classes or name not in attributes:
            continue
        a_index = attributes.index(name)
        c_index = model_classes.index(name)
        observed = mask[:, a_index] & keep
        if observed.sum() == 0:
            continue
        truth = values[observed, a_index] >= 0.5
        probability = fabric_scores[observed, c_index]
        row = binary_metrics(truth, probability, float(thresholds[c_index]))
        row["threshold"] = float(thresholds[c_index])
        row["_truth"] = truth.tolist()
        row["_prediction"] = (probability >= thresholds[c_index]).tolist()
        per_attribute[name] = row
    overall = summarise(per_attribute)
    overall["n_fabrics"] = int(keep.sum())
    return overall, per_attribute


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkpoint", default=str(ROOT / "checkpoints" / "fabricvst_taxonomy" / "best.pt"))
    args = parser.parse_args()

    config = load_config()
    RESULTS.mkdir(parents=True, exist_ok=True)
    device = torch.device("cuda")

    data = np.load(ROOT / "artifacts" / "fabricvst_attributes.npz", allow_pickle=False)
    fabric_ids = data["fabric_ids"].astype(str)
    attributes = data["attributes"].astype(str).tolist()
    values = data["values"].astype(np.float32)
    mask = data["mask"].astype(bool)

    cfg = config["fashionclip"]
    model, model_classes, thresholds, saved = build_model_from_checkpoint(
        Path(args.checkpoint), cfg["model_id"], cfg["revision"], device
    )
    processor = AutoProcessor.from_pretrained(cfg["model_id"], revision=cfg["revision"], local_files_only=True)

    root = Path(config["fabricvst"]["root"]) / config["fabricvst"]["image_dir"]
    paths: list[Path] = []
    owner: list[int] = []
    for f_index, fabric in enumerate(fabric_ids):
        files = sorted(
            (p for p in (root / fabric).iterdir() if p.suffix.lower() in {".png", ".jpg", ".jpeg"}),
            key=lambda p: int(p.stem) if p.stem.isdigit() else 0,
        )
        paths.extend(files)
        owner.extend([f_index] * len(files))
    owner_array = np.asarray(owner)
    print(f"images={len(paths)} classes={len(model_classes)}", flush=True)

    loader = DataLoader(
        ImageListDataset(paths, processor), batch_size=int(cfg["batch_size"]),
        shuffle=False, num_workers=8, pin_memory=True,
    )
    probabilities = predict_probabilities(model, loader, device, len(model_classes))
    fabric_scores = np.zeros((len(fabric_ids), len(model_classes)), dtype=np.float32)
    for f_index in range(len(fabric_ids)):
        fabric_scores[f_index] = probabilities[owner_array == f_index].mean(axis=0)

    prediction_rows = []
    for f_index, fabric in enumerate(fabric_ids):
        row = {"fabric_id": fabric, "n_images": int((owner_array == f_index).sum())}
        for c_index, name in enumerate(model_classes):
            row[f"prob_{name}"] = round(float(fabric_scores[f_index, c_index]), 6)
        for a_index, name in enumerate(attributes):
            row[f"true_{name}"] = int(values[f_index, a_index]) if mask[f_index, a_index] else ""
        prediction_rows.append(row)
    write_table(RESULTS / "predictions.csv", prediction_rows)

    split = fabric_split(list(fabric_ids), int(config["seed"]))
    all_keep = np.ones(len(fabric_ids), bool)
    test_keep = np.array([fid in set(split["test"]) for fid in fabric_ids])
    comparable = list(config["mapping"]["exact"].keys())

    report = {"checkpoint": args.checkpoint, "group": saved.get("group"), "best_epoch": int(saved.get("best_epoch", -1))}
    tables = {}
    for label, names, keep in [
        ("comparable_all_fabrics", comparable, all_keep),
        ("comparable_paper_test_fabrics", comparable, test_keep),
        ("full_coverage_all_fabrics", model_classes, all_keep),
    ]:
        overall, per_attribute = evaluate(
            fabric_scores, values, mask, attributes, model_classes, thresholds, keep, names
        )
        report[label] = overall
        tables[label] = [{"attribute": name, **row} for name, row in per_attribute.items()]
        print(f"\n--- {label}: n_fabrics={overall['n_fabrics']} attrs={overall['n_attributes']} ---", flush=True)
        print(f"  macro_f1={overall['macro_f1']:.4f} micro_f1={overall['micro_f1']:.4f} "
              f"macro_auroc={None if overall['macro_auroc'] is None else round(overall['macro_auroc'],4)} "
              f"mAP={None if overall['macro_average_precision'] is None else round(overall['macro_average_precision'],4)}", flush=True)
        for row in tables[label]:
            print(f"    {row['attribute']:>16} F1={row['f1']:.3f} P={row['precision']:.3f} R={row['recall']:.3f} "
                  f"AUROC={None if row['auroc'] is None else round(row['auroc'],3)} pos={row['positive']}/{row['support']}", flush=True)

    for label, rows in tables.items():
        write_table(RESULTS / f"per_attribute_metrics_{label}.csv", rows)

    # ---- head-to-head against last2 --------------------------------------
    old_path = ROOT / "results" / "fabricvst_last2_external" / "overall_metrics.json"
    comparison_rows = []
    if old_path.is_file():
        old = json.loads(old_path.read_text())
        old_per = {
            row["attribute"]: row
            for row in csv.DictReader(
                (ROOT / "results" / "fabricvst_last2_external" / "per_attribute_metrics_exact_all_fabrics.csv").open()
            )
        }
        new_per = {row["attribute"]: row for row in tables["comparable_all_fabrics"]}
        for name in comparable:
            if name not in old_per or name not in new_per:
                continue
            old_f1 = float(old_per[name]["f1"])
            new_f1 = float(new_per[name]["f1"])
            old_auroc = old_per[name]["auroc"]
            new_auroc = new_per[name]["auroc"]
            comparison_rows.append({
                "attribute": name,
                "old_last2_f1": round(old_f1, 4),
                "new_model_f1": round(new_f1, 4),
                "f1_difference": round(new_f1 - old_f1, 4),
                "old_last2_auroc": None if not old_auroc else round(float(old_auroc), 4),
                "new_model_auroc": None if new_auroc is None else round(float(new_auroc), 4),
                "auroc_difference": (
                    None if (not old_auroc or new_auroc is None)
                    else round(float(new_auroc) - float(old_auroc), 4)
                ),
                "support": new_per[name]["support"],
                "positive": new_per[name]["positive"],
            })
        report["model_comparison_overall"] = {
            "old_last2": {
                key: old["exact_all_fabrics"].get(key)
                for key in ("macro_f1", "micro_f1", "macro_auroc", "macro_average_precision", "macro_recall")
            },
            "new_model": {
                key: report["comparable_all_fabrics"].get(key)
                for key in ("macro_f1", "micro_f1", "macro_auroc", "macro_average_precision", "macro_recall")
            },
        }
        write_table(RESULTS / "model_comparison.csv", comparison_rows)
        print("\n--- old last2 vs new model (exact-mapped attributes, all 50 fabrics) ---")
        for row in comparison_rows:
            print(f"  {row['attribute']:>16} F1 {row['old_last2_f1']:.3f} -> {row['new_model_f1']:.3f} "
                  f"({row['f1_difference']:+.3f})   AUROC {row['old_last2_auroc']} -> {row['new_model_auroc']}")

    (RESULTS / "overall_metrics.json").write_text(json.dumps(report, indent=2) + "\n")
    (ROOT / "manifests" / "06_eval_newmodel_external.json").write_text(
        json.dumps({"status": "complete", "results": str(RESULTS)}, indent=2) + "\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
