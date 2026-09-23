#!/usr/bin/env python3
"""PART A - external evaluation of the preserved ``last2`` checkpoint on FabricVST.

The checkpoint is loaded read-only and its stored per-class thresholds, chosen
on our own development split, are used unchanged.  Nothing in this script reads
a FabricVST label before producing a prediction.
"""
from __future__ import annotations

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

RESULTS = ROOT / "results" / "fabricvst_last2_external"


def evaluate(
    fabric_ids: np.ndarray,
    fabric_scores: np.ndarray,
    values: np.ndarray,
    mask: np.ndarray,
    attributes: list[str],
    mapping: dict[str, str],
    last2_classes: list[str],
    thresholds: np.ndarray,
    selected: list[str] | None = None,
) -> tuple[dict, dict]:
    keep = np.array([fid in set(selected) for fid in fabric_ids]) if selected else np.ones(len(fabric_ids), bool)
    per_attribute: dict[str, dict] = {}
    for attribute, source_class in mapping.items():
        a_index = attributes.index(attribute)
        c_index = last2_classes.index(source_class)
        observed = mask[:, a_index] & keep
        if observed.sum() == 0:
            continue
        truth = values[observed, a_index] >= 0.5
        probability = fabric_scores[observed, c_index]
        row = binary_metrics(truth, probability, float(thresholds[c_index]))
        row["last2_class"] = source_class
        row["threshold"] = float(thresholds[c_index])
        row["_truth"] = truth.tolist()
        row["_prediction"] = (probability >= thresholds[c_index]).tolist()
        per_attribute[attribute] = row
    overall = summarise(per_attribute)
    overall["n_fabrics"] = int(keep.sum())
    return overall, per_attribute


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


def main() -> int:
    config = load_config()
    RESULTS.mkdir(parents=True, exist_ok=True)
    device = torch.device("cuda")

    data = np.load(ROOT / "artifacts" / "fabricvst_attributes.npz", allow_pickle=False)
    fabric_ids = data["fabric_ids"].astype(str)
    attributes = data["attributes"].astype(str).tolist()
    values = data["values"].astype(np.float32)
    mask = data["mask"].astype(bool)

    last2_cfg = config["last2"]
    model, last2_classes, thresholds, saved = build_model_from_checkpoint(
        Path(last2_cfg["checkpoint"]), last2_cfg["base_model_id"], last2_cfg["base_revision"], device
    )
    if last2_classes != last2_cfg["classes"]:
        raise RuntimeError("checkpoint class order differs from config")
    processor = AutoProcessor.from_pretrained(
        last2_cfg["base_model_id"], revision=last2_cfg["base_revision"], local_files_only=True
    )

    # ---- collect images ---------------------------------------------------
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
    print(f"images={len(paths)} fabrics={len(fabric_ids)}", flush=True)

    loader = DataLoader(
        ImageListDataset(paths, processor),
        batch_size=int(config["fashionclip"]["batch_size"]),
        shuffle=False,
        num_workers=8,
        pin_memory=True,
    )
    probabilities = predict_probabilities(model, loader, device, len(last2_classes))

    # ---- aggregate crops to fabric level ---------------------------------
    fabric_scores = np.zeros((len(fabric_ids), len(last2_classes)), dtype=np.float32)
    for f_index in range(len(fabric_ids)):
        fabric_scores[f_index] = probabilities[owner_array == f_index].mean(axis=0)

    np.savez(
        ROOT / "artifacts" / "last2_fabricvst_probabilities.npz",
        fabric_ids=fabric_ids,
        classes=np.asarray(last2_classes),
        image_probabilities=probabilities,
        image_owner=owner_array,
        fabric_scores=fabric_scores,
        thresholds=thresholds,
    )

    prediction_rows = []
    for f_index, fabric in enumerate(fabric_ids):
        row = {"fabric_id": fabric, "n_images": int((owner_array == f_index).sum())}
        for c_index, name in enumerate(last2_classes):
            row[f"prob_{name}"] = round(float(fabric_scores[f_index, c_index]), 6)
        for a_index, attribute in enumerate(attributes):
            row[f"true_{attribute}"] = int(values[f_index, a_index]) if mask[f_index, a_index] else ""
        prediction_rows.append(row)
    write_table(RESULTS / "predictions.csv", prediction_rows)

    # ---- mapping table ----------------------------------------------------
    mapping_rows = []
    for attribute, source in config["mapping"]["exact"].items():
        mapping_rows.append({
            "fabricvst_attribute": attribute, "last2_output": source, "mapping": "exact",
            "reason": config["mapping"]["notes"].get(attribute, "identical surface form and meaning"),
        })
    for attribute, source in config["mapping"]["approximate"].items():
        mapping_rows.append({
            "fabricvst_attribute": attribute, "last2_output": source, "mapping": "approximate",
            "reason": config["mapping"]["notes"].get(attribute, "related but not identical"),
        })
    for attribute in config["mapping"]["unavailable_fabricvst_attributes"]:
        mapping_rows.append({
            "fabricvst_attribute": attribute, "last2_output": "", "mapping": "unavailable",
            "reason": "no semantically corresponding class in the last2 taxonomy",
        })
    write_table(RESULTS / "mapping.csv", mapping_rows)

    # ---- evaluations ------------------------------------------------------
    exact = config["mapping"]["exact"]
    approximate = config["mapping"]["approximate"]
    split = fabric_split(list(fabric_ids), int(config["seed"]))
    (ROOT / "splits" / "fabricvst_fabric_split.json").write_text(
        json.dumps({"seed": config["seed"], "note": "our own deterministic stand-in; dataset ships no split file", **split}, indent=2) + "\n"
    )

    report: dict = {"checkpoint": last2_cfg["checkpoint"], "best_epoch": int(saved.get("best_epoch", -1))}
    tables: dict[str, list[dict]] = {}

    for label, mapping_set, subset in [
        ("exact_all_fabrics", exact, None),
        ("exact_paper_test_fabrics", exact, split["test"]),
        ("approximate_all_fabrics", approximate, None),
    ]:
        overall, per_attribute = evaluate(
            fabric_ids, fabric_scores, values, mask, attributes,
            mapping_set, last2_classes, thresholds, subset,
        )
        report[label] = overall
        tables[label] = [{"attribute": name, **row} for name, row in per_attribute.items()]
        print(f"\n--- {label}: n_fabrics={overall['n_fabrics']} ---", flush=True)
        print(f"  macro_f1={overall['macro_f1']:.4f} micro_f1={overall['micro_f1']:.4f} "
              f"macro_auroc={overall['macro_auroc'] if overall['macro_auroc'] is None else round(overall['macro_auroc'],4)} "
              f"macro_ap={overall['macro_average_precision'] if overall['macro_average_precision'] is None else round(overall['macro_average_precision'],4)}", flush=True)
        for row in tables[label]:
            print(f"    {row['attribute']:>12} <- {row['last2_class']:<12} "
                  f"F1={row['f1']:.3f} P={row['precision']:.3f} R={row['recall']:.3f} "
                  f"AUROC={row['auroc'] if row['auroc'] is None else round(row['auroc'],3)} "
                  f"pos={row['positive']}/{row['support']}", flush=True)

    for label, rows in tables.items():
        write_table(RESULTS / f"per_attribute_metrics_{label}.csv", rows)
    (RESULTS / "overall_metrics.json").write_text(json.dumps(report, indent=2) + "\n")
    (ROOT / "manifests" / "02_eval_last2_external.json").write_text(
        json.dumps({"status": "complete", "results": str(RESULTS)}, indent=2) + "\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
