from __future__ import annotations

import unittest

from recommendation_api.tactile_models import TactileIntent
from recommendation_api.tactile_ranking import TactileRankingService
from recommendation_api.tactile_store import TactileStore


class TactileRankingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.store = TactileStore()
        cls.service = TactileRankingService(cls.store)

    def _alternative_case(self):
        for anchor in self.store.source_asins:
            anchor_signal = self.service.concept_signal(anchor, "scratchy")
            if not anchor_signal:
                continue
            result = self.service.alternatives(
                anchor_product_id=anchor,
                direction="less",
                tactile_concept="scratchy",
                top_k=5,
            )
            if result["results"]:
                return anchor, anchor_signal, result
        self.fail("Fixture catalog has no less-scratchy alternative case")

    def test_less_scratchy_alternative_is_same_category_and_directional(self) -> None:
        anchor, anchor_signal, result = self._alternative_case()
        category = self.store.product_metadata[anchor]["category"]
        self.assertTrue(result["comparison_claim_allowed"])
        for row in result["results"]:
            self.assertEqual(row["category"], category)
            candidate = self.service.concept_signal(row["product_id"], "scratchy")
            self.assertLess(candidate["score"], anchor_signal["score"])
            self.assertIn("tactile_improvement", row["score_breakdown"])
            self.assertTrue(row["reason"]["evidence"])

    def test_invalid_or_unsupported_alternative_request(self) -> None:
        asin = self.store.source_asins[0]
        with self.assertRaises(ValueError):
            self.service.alternatives(
                anchor_product_id=asin,
                direction="sideways",
                tactile_concept="soft",
            )
        with self.assertRaises(ValueError):
            self.service.alternatives(
                anchor_product_id=asin,
                direction="more",
                tactile_concept="papery hand feel",
            )

    def test_baseline_preserves_base_order_and_gate_is_off(self) -> None:
        candidates = [
            {"product_id": asin, "base_score": score}
            for asin, score in zip(self.store.target_asins[:4], [0.9, 0.7, 0.2, 0.1])
        ]
        result = self.service.rerank(candidates=candidates, strategy="baseline", top_k=4)
        self.assertEqual(
            [row["product_id"] for row in result["results"]],
            [row["product_id"] for row in candidates],
        )
        self.assertTrue(
            all(row["score_breakdown"]["tactile_gate"] == 0 for row in result["results"])
        )

    def test_context_gate_is_explicit_and_cross_category_is_weak(self) -> None:
        categories = {}
        for asin in self.store.target_asins:
            categories.setdefault(self.store.product_metadata[asin]["category"], asin)
        self.assertGreaterEqual(len(categories), 2)
        category, same_asin = next(iter(categories.items()))
        other_asin = next(asin for cat, asin in categories.items() if cat != category)
        intent = TactileIntent(
            category=category,
            desired_more=("soft",),
            source="explicit_structured",
        )
        result = self.service.rerank(
            candidates=[
                {"product_id": same_asin, "base_score": 0.5},
                {"product_id": other_asin, "base_score": 0.5},
            ],
            strategy="context_gated",
            intent=intent,
            top_k=2,
        )
        by_id = {row["product_id"]: row for row in result["results"]}
        self.assertEqual(by_id[same_asin]["score_breakdown"]["tactile_gate"], 1.0)
        self.assertLessEqual(by_id[other_asin]["score_breakdown"]["tactile_gate"], 0.02)

    def test_rerank_rejects_duplicate_and_unknown_candidates(self) -> None:
        asin = self.store.target_asins[0]
        with self.assertRaises(ValueError):
            self.service.rerank(
                candidates=[
                    {"product_id": asin, "base_score": 1.0},
                    {"product_id": asin, "base_score": 0.0},
                ]
            )
        with self.assertRaises(KeyError):
            self.service.rerank(
                candidates=[{"product_id": "B000000000", "base_score": 1.0}]
            )


if __name__ == "__main__":
    unittest.main()

