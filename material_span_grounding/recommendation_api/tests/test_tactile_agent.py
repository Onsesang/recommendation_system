from __future__ import annotations

import unittest

from recommendation_api.tactile_agent import (
    TactileAgentService,
    intent_from_mapping,
    parse_tactile_intent,
)
from recommendation_api.tactile_store import TactileStore


class TactileAgentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.store = TactileStore()
        cls.agent = TactileAgentService(cls.store)

    def test_korean_intent_preserves_thin_and_avoids_sheer(self) -> None:
        intent = parse_tactile_intent("여름에 입을 바지인데 얇은 건 괜찮지만 비치는 건 싫어")
        self.assertEqual(intent.category, "pants")
        self.assertIn("thinness", intent.desired_more)
        self.assertIn("sheerness", intent.avoid)

    def test_compound_more_lightweight_and_not_sheer_are_scoped(self) -> None:
        intent = parse_tactile_intent("더 가볍고 안 비치는 드레스")
        self.assertIn("weight_lightness", intent.desired_more)
        self.assertNotIn("weight_lightness", intent.avoid)
        self.assertIn("sheerness", intent.avoid)

    def test_follow_up_replaces_thin_with_thick(self) -> None:
        previous = parse_tactile_intent("얇은 바지를 찾아줘")
        updated = parse_tactile_intent("조금 더 두꺼운 걸로 보여줘", previous=previous)
        self.assertNotIn("thinness", updated.desired_more)
        self.assertIn("thickness", updated.desired_more)
        self.assertEqual(updated.category, "pants")

    def test_missing_category_requests_clarification(self) -> None:
        result = self.agent.handle({"message": "부드러운 걸 원해"})
        self.assertEqual(result["status"], "needs_clarification")
        self.assertEqual(result["results"], [])

    def test_agent_returns_only_real_catalog_products(self) -> None:
        result = self.agent.handle(
            {"message": "부드럽고 비치지 않는 바지를 찾아줘", "top_k": 5}
        )
        self.assertEqual(result["status"], "complete")
        self.assertTrue(result["results"])
        self.assertTrue(
            all(row["product_id"] in self.store.product_metadata for row in result["results"])
        )
        self.assertFalse(result["retrieval"]["invented_product_allowed"])
        for row in result["results"]:
            if row["reason"]["matched_constraints"]:
                self.assertTrue(row["reason"]["evidence"])

    def test_anchor_supplies_category_and_unknown_anchor_is_rejected(self) -> None:
        anchor = self.store.target_asins[0]
        result = self.agent.handle(
            {"message": "조금 더 가벼운 걸로", "current_product_id": anchor, "top_k": 2}
        )
        self.assertEqual(
            result["intent"]["category"], self.store.product_metadata[anchor]["category"]
        )
        with self.assertRaises(KeyError):
            self.agent.handle(
                {"message": "더 부드러운 것", "current_product_id": "B000000000"}
            )

    def test_cross_category_anchor_is_not_used(self) -> None:
        anchor = next(
            asin
            for asin in self.store.target_asins
            if self.store.product_metadata[asin]["category"] != "pants"
        )
        result = self.agent.handle(
            {"message": "부드러운 바지를 찾아줘", "current_product_id": anchor, "top_k": 2}
        )
        self.assertFalse(result["retrieval"]["anchor_used"])
        self.assertTrue(all(row["category"] == "pants" for row in result["results"]))

    def test_previous_intent_contract_validation(self) -> None:
        previous = intent_from_mapping(
            {"category": "pants", "avoid": ["sheer"], "source": "explicit_structured"}
        )
        self.assertEqual(previous.avoid, ("sheerness",))
        with self.assertRaises(ValueError):
            intent_from_mapping({"avoid": "sheer"})


if __name__ == "__main__":
    unittest.main()
