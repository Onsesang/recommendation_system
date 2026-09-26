from __future__ import annotations

import unittest

from shopping_agent.v1 import tactile_phrases
from demo_agent.models import TACTILE_CLASSES


class TactilePhraseTests(unittest.TestCase):
    def test_every_class_has_three_levels_without_numbers_or_grades(self) -> None:
        self.assertEqual(set(tactile_phrases.PHRASES), set(TACTILE_CLASSES))
        for name in TACTILE_CLASSES:
            levels = [tactile_phrases.phrase(name, value) for value in (0.9, 0.5, 0.1)]
            self.assertEqual(len(set(levels)), 3, name)
            for text in levels:
                self.assertNotRegex(text, r"\d|높음|보통|낮음")

    def test_thresholds(self) -> None:
        self.assertEqual(tactile_phrases.phrase("thin", 0.7), "얇다")
        self.assertEqual(tactile_phrases.phrase("thin", 0.69), "조금 얇다")
        self.assertEqual(tactile_phrases.phrase("rough", 0.33), "까끌하지 않다")
        self.assertEqual(tactile_phrases.phrases({"thin": 0.83, "soft": 0.5}, ["thin", "cool"]), {"thin": "얇다"})
        self.assertEqual(tactile_phrases.strongest({"thin": 0.2, "soft": 0.9, "warm": 0.5}, limit=2),
                         ["부드럽다", "조금 따뜻하다"])

    def test_split_common_moves_shared_phrases_out_of_the_top_three(self) -> None:
        rows = [{"soft": "부드럽다", "thin": "얇다"}, {"soft": "부드럽다", "thin": "조금 얇다"},
                {"soft": "부드럽다", "thin": "얇다"}, {"soft": "부드럽다"}]
        common, rest = tactile_phrases.split_common(rows)
        self.assertEqual(common, {"soft": "부드럽다"})
        self.assertEqual(rest[:3], [{"thin": "얇다"}, {"thin": "조금 얇다"}, {"thin": "얇다"}])
        self.assertEqual(rest[3], {"soft": "부드럽다"})  # beyond the top three keeps everything
        self.assertEqual(tactile_phrases.split_common([{"soft": "부드럽다"}]), ({}, [{"soft": "부드럽다"}]))

    def test_compare_marks_the_larger_one_and_how_clear_the_gap_is(self) -> None:
        result = tactile_phrases.compare([
            {"product_id": "A", "title": "a", "last2_predictions": {"soft": 0.80, "thin": 0.72, "warm": 0.10}},
            {"product_id": "B", "title": "b", "last2_predictions": {"soft": 0.62, "thin": 0.70, "warm": 0.20}},
        ])
        comparison = result["comparison"]
        self.assertEqual(comparison["soft"]["more"], "A")
        self.assertEqual(comparison["soft"]["difference"], "뚜렷하게 차이 남")
        self.assertIsNone(comparison["thin"]["more"])
        self.assertEqual(comparison["thin"]["difference"], "비슷함")
        self.assertNotIn("warm", comparison)  # nobody is warm; not worth saying
        self.assertEqual(comparison["soft"]["phrases"], {"A": "부드럽다", "B": "조금 부드럽다"})


if __name__ == "__main__":
    unittest.main()
