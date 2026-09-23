from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tactile_coldstart.common import load_taxonomy, symbolic_score, validate_taxonomy
from tactile_coldstart.grounding import parse_mapping, render_prompt


class TaxonomyAndGroundingTest(unittest.TestCase):
    def setUp(self) -> None:
        self.taxonomy = load_taxonomy()
        self.source = {
            "span_id": "s1",
            "quote": "extremely soft",
            "claim": "the material is extremely soft",
            "review_text": "The material is extremely soft.",
        }

    def test_taxonomy_is_valid_and_dynamic(self) -> None:
        validate_taxonomy(self.taxonomy)
        self.assertGreater(len(self.taxonomy["axes"]), 1)

    def test_generic_prompt_contains_dynamic_taxonomy(self) -> None:
        prompt = render_prompt(self.source, self.taxonomy)
        for axis in self.taxonomy["axes"]:
            self.assertIn(axis["id"], prompt)

    def test_parse_and_numeric_conversion_are_separate(self) -> None:
        raw = json.dumps({
            "span_id": "s1", "mappable": True, "axis_id": "softness",
            "direction": "soft", "intensity": "strong", "scope": "main_fabric",
            "confidence": 0.93, "reason": "explicit",
        })
        parsed = parse_mapping(raw, self.source, self.taxonomy)
        self.assertEqual(parsed["status"], "success")
        self.assertEqual(symbolic_score(parsed, self.taxonomy), -2.0)

    def test_unmappable_is_preserved(self) -> None:
        raw = json.dumps({
            "span_id": "s1", "mappable": False, "axis_id": None,
            "direction": None, "intensity": None, "scope": None,
            "confidence": 0.7, "reason": "outside taxonomy",
        })
        parsed = parse_mapping(raw, self.source, self.taxonomy)
        self.assertFalse(parsed["mappable"])
        self.assertIsNone(parsed["axis_id"])

    def test_bounded_model_aliases_are_normalized_with_provenance(self) -> None:
        raw = json.dumps({
            "span_id": "s1-typo", "mappable": True, "axis_id": "surface_texture",
            "direction": "soft", "intensity": "strong", "scope": "inner_surface",
            "confidence": 0.9, "reason": "explicit softness on the inside",
        })
        parsed = parse_mapping(raw, self.source, self.taxonomy)
        self.assertEqual(parsed["status"], "success")
        self.assertEqual(parsed["axis_id"], "softness")
        self.assertEqual(parsed["direction"], "soft")
        self.assertEqual(parsed["scope"], "lining")
        self.assertEqual(
            {item["field"] for item in parsed["normalizations"]},
            {"span_id", "axis_id", "scope"},
        )

    def test_medium_direction_is_neutral(self) -> None:
        raw = json.dumps({
            "span_id": "s1", "mappable": True, "axis_id": "thickness",
            "direction": "medium", "intensity": "none", "scope": "main_fabric",
            "confidence": 0.95, "reason": "medium weight",
        })
        parsed = parse_mapping(raw, self.source, self.taxonomy)
        self.assertEqual(parsed["status"], "success")
        self.assertEqual(parsed["direction"], "neutral")
        self.assertEqual(parsed["normalizations"][0]["rule"], "direction_alias")


if __name__ == "__main__":
    unittest.main()
