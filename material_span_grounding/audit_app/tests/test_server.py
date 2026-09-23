from __future__ import annotations

import json
import csv
import tempfile
import unittest
from pathlib import Path

from audit_app.server import ALLOWED_ACTION, ASIN_PATTERN, AuditStore, atomic_json_write


class ServerUtilityTests(unittest.TestCase):
    def test_asin_validation_blocks_traversal(self) -> None:
        self.assertTrue(ASIN_PATTERN.fullmatch("B07WLL13CV"))
        self.assertFalse(ASIN_PATTERN.fullmatch("../../passwd"))
        self.assertFalse(ASIN_PATTERN.fullmatch("B07WLL13CV.jpg"))

    def test_expected_actions(self) -> None:
        self.assertEqual(ALLOWED_ACTION, {"good", "bad", "edit"})

    def test_atomic_json_write(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            atomic_json_write(path, {"revision": 3, "value": "한글"})
            self.assertEqual(
                json.loads(path.read_text(encoding="utf-8")),
                {"revision": 3, "value": "한글"},
            )

    def test_next_control_saves_good_before_navigation(self) -> None:
        app_js = (Path(__file__).resolve().parents[1] / "static" / "app.js").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            'elements.nextButton.addEventListener("click", markGoodAndNext)', app_js
        )
        self.assertIn(
            '["ArrowRight", "ArrowDown"].includes(event.key)', app_js
        )
        self.assertIn("markGood({ forceAdvance: true })", app_js)


class MissingSpanStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        self.span_id = "a" * 20
        self.review_id = "b" * 20
        review = "The fabric is unusually thick. It shrank after washing."
        item = {
            "span_id": self.span_id,
            "review_id": self.review_id,
            "asin": "B07WLL13CV",
            "review": review,
            "quote": "It shrank after washing.",
            "qwen": {
                "accepted": True,
                "claim": "The fabric shrank after washing.",
                "scope": "main_fabric",
                "property_status": "present",
                "visual_observability": "low",
            },
        }
        items_path = root / "items.json"
        items_path.write_text(
            json.dumps({"image_root": str(root), "items": [item]}),
            encoding="utf-8",
        )
        source_path = root / "source.csv"
        fields = [
            "span_id",
            "review_id",
            "human_accepted",
            "human_claim",
            "human_scope",
            "human_property_status",
            "human_visual_observability",
            "annotator_id",
            "comment",
        ]
        with source_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerow({"span_id": self.span_id, "review_id": self.review_id})
        self.store = AuditStore(
            items_path=items_path,
            annotations_path=root / "annotations.json",
            missing_spans_path=root / "missing_spans.json",
            source_csv_path=source_path,
            live_csv_path=root / "live.csv",
            missing_csv_path=root / "missing.csv",
            recall_checks_csv_path=root / "checks.csv",
            update_quality=False,
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def payload(self) -> dict:
        return {
            "source_span_id": self.span_id,
            "quote": "The fabric is unusually thick.",
            "claim": "The fabric is unusually thick.",
            "scope": "main_fabric",
            "property_status": "present",
            "intensity": "strong",
            "sentiment": "neutral",
            "evidence_basis": "direct_touch",
            "visual_observability": "medium",
            "annotator_id": "tester",
            "comment": "missed thickness",
        }

    def test_missing_span_create_update_delete_and_exports(self) -> None:
        created = self.store.save_missing(self.payload())["missing_span"]
        self.assertEqual(len(created["missing_span_id"]), 20)
        self.assertEqual(len(self.store.snapshot()["missing_spans"]), 1)
        updated_payload = self.payload()
        updated_payload["claim"] = "The main fabric is very thick."
        updated = self.store.save_missing(
            updated_payload, created["missing_span_id"]
        )["missing_span"]
        self.assertEqual(updated["claim"], "The main fabric is very thick.")
        self.assertEqual(updated["created_at"], created["created_at"])
        self.assertTrue(self.store.missing_csv_path.read_text(encoding="utf-8"))
        self.assertTrue(self.store.delete_missing(created["missing_span_id"])["deleted"])
        self.assertFalse(self.store.snapshot()["missing_spans"])

    def test_missing_span_requires_exact_new_quote(self) -> None:
        paraphrase = self.payload()
        paraphrase["quote"] = "This cloth is thick."
        with self.assertRaisesRegex(ValueError, "exact"):
            self.store.save_missing(paraphrase)
        already_extracted = self.payload()
        already_extracted["quote"] = "It shrank after washing."
        with self.assertRaisesRegex(ValueError, "already extracted"):
            self.store.save_missing(already_extracted)

    def test_review_check_is_stored_separately(self) -> None:
        result = self.store.save_review_check(
            self.review_id, {"annotator_id": "tester"}
        )
        self.assertTrue(result["review_check"]["checked"])
        self.assertIn(self.review_id, self.store.snapshot()["review_checks"])
        self.assertTrue(self.store.delete_review_check(self.review_id)["deleted"])


if __name__ == "__main__":
    unittest.main()
