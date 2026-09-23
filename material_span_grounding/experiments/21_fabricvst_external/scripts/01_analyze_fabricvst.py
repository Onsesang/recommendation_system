#!/usr/bin/env python3
"""Validate FabricVST structure and build the authoritative attribute table.

Reads RAS_dataset as downloaded from the official project page and writes a
fabric-level multi-label attribute matrix plus a structural audit.  Nothing here
is tuned on any evaluation outcome; the annotator aggregation rule is fixed
before any model is run.
"""
from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
DATASET = Path("/home/user/onsesang/material_span_grounding/data/external/FabricVST/RAS_dataset")
ARTIFACTS = ROOT / "artifacts"


def split_definition(cell: str) -> tuple[str, str | None]:
    """Annotator files 4 and 5 append a parenthetical gloss to some names."""
    if "(" not in cell:
        return cell.strip(), None
    name, _, rest = cell.partition("(")
    return name.strip(), rest.rstrip(") ").strip() or None


def read_attribute_csv(path: Path) -> tuple[list[str], dict[str, list[str]]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.reader(handle))
    header = [cell.strip() for cell in rows[0]]
    attributes = [split_definition(cell)[0] for cell in header[1:] if cell]
    table: dict[str, list[str]] = {}
    for row in rows[1:]:
        if not row or not row[0].strip():
            continue
        name = row[0].strip()
        # Each file repeats its header row at the end of the table.
        if not name.lower().startswith("material_"):
            continue
        values = [cell.strip().upper() for cell in row[1:]]
        table[name] = values[: len(attributes)]
    return attributes, table


def main() -> int:
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    audit: dict = {"dataset_root": str(DATASET)}

    # ---- annotator files -------------------------------------------------
    annotator_files = sorted(DATASET.glob("attributes/attributes_*.csv"))
    per_annotator: dict[str, dict[str, list[str]]] = {}
    attribute_sets: dict[str, list[str]] = {}
    for path in annotator_files:
        attributes, table = read_attribute_csv(path)
        attribute_sets[path.name] = attributes
        per_annotator[path.name] = table

    definitions: dict[str, str] = {}
    for path in annotator_files:
        with path.open(newline="", encoding="utf-8-sig") as handle:
            header = next(csv.reader(handle))
        for cell in header[1:]:
            if not cell.strip():
                continue
            name, gloss = split_definition(cell)
            if gloss:
                definitions.setdefault(name, gloss)
    audit["attribute_definitions_from_dataset"] = definitions

    reference = attribute_sets[annotator_files[0].name]
    audit["annotator_files"] = {
        name: {"attributes": len(values), "materials": len(per_annotator[name])}
        for name, values in attribute_sets.items()
    }
    audit["attribute_vocabulary"] = reference
    audit["attribute_vocabulary_identical_across_annotators"] = all(
        values == reference for values in attribute_sets.values()
    )

    materials = sorted(
        {name for table in per_annotator.values() for name in table},
        key=lambda value: int(value.split("_")[1]),
    )
    audit["n_materials_in_annotations"] = len(materials)

    # ---- aggregate annotators by majority vote ---------------------------
    # Fixed rule, declared before evaluation: an attribute is positive when a
    # strict majority of annotators who labelled that fabric marked it T.
    n_attr = len(reference)
    values = np.zeros((len(materials), n_attr), dtype=np.float32)
    mask = np.zeros((len(materials), n_attr), dtype=bool)
    agreement_rows = []
    for m_index, material in enumerate(materials):
        for a_index, attribute in enumerate(reference):
            votes = []
            for name, table in per_annotator.items():
                row = table.get(material)
                if row is None or a_index >= len(row):
                    continue
                cell = row[a_index]
                if cell in {"T", "TRUE", "1"}:
                    votes.append(1)
                elif cell in {"F", "FALSE", "0"}:
                    votes.append(0)
            if not votes:
                continue
            mask[m_index, a_index] = True
            positive = sum(votes)
            values[m_index, a_index] = 1.0 if positive * 2 > len(votes) else 0.0
            agreement_rows.append(
                {
                    "material": material,
                    "attribute": attribute,
                    "n_votes": len(votes),
                    "n_positive": positive,
                    "majority": int(positive * 2 > len(votes)),
                    "unanimous": int(positive == 0 or positive == len(votes)),
                }
            )

    audit["aggregation_rule"] = (
        "strict majority of available annotator votes; ties resolved to negative"
    )
    unanimous = [row["unanimous"] for row in agreement_rows]
    audit["annotator_unanimous_fraction"] = float(np.mean(unanimous)) if unanimous else None
    vote_counts = Counter(row["n_votes"] for row in agreement_rows)
    audit["votes_per_cell_distribution"] = {str(k): v for k, v in sorted(vote_counts.items())}

    # ---- image inventory --------------------------------------------------
    inventory = {}
    for kind in ("visual", "visual_cropped", "tactile"):
        base = DATASET / kind
        if not base.is_dir():
            continue
        per_fabric = {}
        for fabric_dir in sorted(base.iterdir(), key=lambda p: int(p.name) if p.name.isdigit() else -1):
            if not fabric_dir.is_dir():
                continue
            files = [p for p in fabric_dir.iterdir() if p.suffix.lower() in {".png", ".jpg", ".jpeg"}]
            per_fabric[fabric_dir.name] = len(files)
        inventory[kind] = {
            "n_fabrics": len(per_fabric),
            "total_images": int(sum(per_fabric.values())),
            "min_per_fabric": int(min(per_fabric.values())) if per_fabric else 0,
            "max_per_fabric": int(max(per_fabric.values())) if per_fabric else 0,
            "per_fabric": per_fabric,
        }
    audit["image_inventory"] = {
        kind: {k: v for k, v in data.items() if k != "per_fabric"}
        for kind, data in inventory.items()
    }

    # ---- fabric id consistency -------------------------------------------
    visual_ids = set(inventory.get("visual_cropped", inventory.get("visual", {})).get("per_fabric", {}))
    annotation_ids = {material.split("_")[1] for material in materials}
    audit["fabric_ids_in_images"] = len(visual_ids)
    audit["fabric_ids_in_annotations"] = len(annotation_ids)
    audit["image_ids_without_annotation"] = sorted(visual_ids - annotation_ids, key=int)
    audit["annotation_ids_without_image"] = sorted(annotation_ids - visual_ids, key=int)

    # ---- no official split file? -----------------------------------------
    split_candidates = [
        p for p in DATASET.rglob("*")
        if p.is_file() and any(token in p.name.lower() for token in ("split", "train", "test", "val"))
    ]
    audit["split_files_found"] = [str(p.relative_to(DATASET)) for p in split_candidates]

    # ---- attribute statistics --------------------------------------------
    stats = []
    for a_index, attribute in enumerate(reference):
        observed = mask[:, a_index]
        positives = int(values[observed, a_index].sum())
        stats.append(
            {
                "attribute": attribute,
                "observed_fabrics": int(observed.sum()),
                "positive_fabrics": positives,
                "negative_fabrics": int(observed.sum()) - positives,
                "positive_ratio": float(positives / max(int(observed.sum()), 1)),
            }
        )
    audit["attribute_statistics"] = stats

    np.savez(
        ARTIFACTS / "fabricvst_attributes.npz",
        fabric_ids=np.asarray([m.split("_")[1] for m in materials]),
        materials=np.asarray(materials),
        attributes=np.asarray(reference),
        values=values,
        mask=mask,
    )
    with (ARTIFACTS / "fabricvst_attribute_stats.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(stats[0].keys()))
        writer.writeheader()
        writer.writerows(stats)
    with (ARTIFACTS / "fabricvst_annotator_agreement.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(agreement_rows[0].keys()))
        writer.writeheader()
        writer.writerows(agreement_rows)
    (ARTIFACTS / "fabricvst_audit.json").write_text(json.dumps(audit, indent=2) + "\n")

    print(json.dumps({k: v for k, v in audit.items() if k not in {"attribute_statistics"}}, indent=2))
    print("\nattribute statistics:")
    for row in stats:
        print(
            f"  {row['attribute']:>16}  observed={row['observed_fabrics']:3d}"
            f"  pos={row['positive_fabrics']:3d}  ratio={row['positive_ratio']:.3f}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
