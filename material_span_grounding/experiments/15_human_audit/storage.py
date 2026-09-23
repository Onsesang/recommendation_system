from __future__ import annotations

import csv
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any


ANNOTATION_COLUMNS = [
    "item_id",
    "asin",
    "family_id",
    "category",
    "tactile_class",
    "image_path",
    "image_missing",
    "raw_target",
    "binary_target",
    "is_fractional_target",
    "image_observability",
    "human_label",
    "confidence",
    "note",
    "review_human_label",
    "review_confidence",
    "completed",
    "first_saved_timestamp",
    "last_updated_timestamp",
]


def ensure_annotation_csv(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        return
    _atomic_write(path, [])


def read_annotations(path: Path) -> dict[str, dict[str, str]]:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    output: dict[str, dict[str, str]] = {}
    for row in rows:
        item_id = row.get("item_id", "")
        if not item_id:
            continue
        if item_id in output:
            raise ValueError(f"duplicate annotation item_id: {item_id}")
        output[item_id] = {column: row.get(column, "") for column in ANNOTATION_COLUMNS}
    return output


def _atomic_write(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=ANNOTATION_COLUMNS, extrasaction="ignore")
            writer.writeheader()
            for row in rows:
                writer.writerow({column: row.get(column, "") for column in ANNOTATION_COLUMNS})
        os.replace(temporary_name, path)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)


def upsert_annotation(path: Path, row: dict[str, Any], manifest_order: list[str]) -> dict[str, str]:
    ensure_annotation_csv(path)
    rows = read_annotations(path)
    item_id = str(row["item_id"])
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    previous = rows.get(item_id, {})
    normalized = {column: str(row.get(column, previous.get(column, ""))) for column in ANNOTATION_COLUMNS}
    normalized["item_id"] = item_id
    normalized["first_saved_timestamp"] = previous.get("first_saved_timestamp") or now
    normalized["last_updated_timestamp"] = now
    rows[item_id] = normalized
    order = {value: number for number, value in enumerate(manifest_order)}
    ordered_rows = sorted(rows.values(), key=lambda value: order.get(value["item_id"], len(order)))
    _atomic_write(path, ordered_rows)
    return normalized
