from __future__ import annotations

import csv
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from analyze_human_audit import _classification_metrics  # noqa: E402
from storage import ANNOTATION_COLUMNS, read_annotations, upsert_annotation  # noqa: E402


class StorageTests(unittest.TestCase):
    def test_upsert_is_unique_and_preserves_first_timestamp(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "audit.csv"
            base = {"item_id": "audit-0001", "human_label": "present", "completed": "true"}
            first = upsert_annotation(path, base, ["audit-0001"])
            second = upsert_annotation(path, {**base, "human_label": "absent"}, ["audit-0001"])
            rows = read_annotations(path)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows["audit-0001"]["human_label"], "absent")
            self.assertEqual(first["first_saved_timestamp"], second["first_saved_timestamp"])
            with path.open(encoding="utf-8", newline="") as handle:
                self.assertEqual(next(csv.reader(handle)), ANNOTATION_COLUMNS)


class MetricTests(unittest.TestCase):
    def test_empty_metrics_are_safe(self) -> None:
        result = _classification_metrics([], [], [])
        self.assertEqual(result["support"], 0)
        self.assertIsNone(result["accuracy"])
        self.assertIsNone(result["auroc"])

    def test_perfect_binary_metrics(self) -> None:
        result = _classification_metrics([0, 1], [0, 1], [0.1, 0.9])
        self.assertEqual(result["accuracy"], 1.0)
        self.assertEqual(result["f1"], 1.0)
        self.assertEqual(result["auroc"], 1.0)


if __name__ == "__main__":
    unittest.main()
