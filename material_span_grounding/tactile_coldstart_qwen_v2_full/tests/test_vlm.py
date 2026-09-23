from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tactile_coldstart.common import load_taxonomy
from tactile_coldstart.vlm import parse_vlm_output, render_vlm_prompt


class VlmSchemaTest(unittest.TestCase):
    def test_prompt_and_parser_adapt_to_axis_list(self) -> None:
        taxonomy = load_taxonomy()
        axes = taxonomy["axes"][:2]
        active = [row["id"] for row in axes]
        prompt = render_vlm_prompt("p1", taxonomy, active)
        for axis_id in active:
            self.assertIn(axis_id, prompt)
        raw = json.dumps(
            {
                "product_id": "p1",
                "predictions": [
                    {
                        "axis_id": axis["id"], "visually_assessable": True,
                        "direction": axis["negative_pole"], "intensity": "moderate",
                        "confidence": 0.7,
                    }
                    for axis in axes
                ],
            }
        )
        parsed = parse_vlm_output(raw, "p1", taxonomy, active)
        self.assertEqual(parsed["status"], "success")
        self.assertEqual(len(parsed["predictions"]), len(active))

    def test_missing_axes_and_false_fields_fail_closed_to_abstention(self) -> None:
        taxonomy = load_taxonomy()
        active = [row["id"] for row in taxonomy["axes"][:4]]
        raw = json.dumps({
            "product_id": "p1",
            "predictions": [
                {"axis_id": active[0], "visually_assessable": False}
            ],
        })
        parsed = parse_vlm_output(raw, "p1", taxonomy, active)
        self.assertEqual(parsed["status"], "success")
        self.assertEqual(len(parsed["predictions"]), len(active))
        self.assertTrue(all(not row["visually_assessable"] for row in parsed["predictions"]))
        self.assertTrue(all(row["score"] is None for row in parsed["predictions"]))
        self.assertEqual(len(parsed["normalizations"]), len(active) - 1)


if __name__ == "__main__":
    unittest.main()
