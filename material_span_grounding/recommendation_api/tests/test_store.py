from __future__ import annotations

import unittest

from recommendation_api.store import RecommendationStore


class RecommendationStoreTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.store = RecommendationStore()

    def test_health_and_shapes(self) -> None:
        health = self.store.health()
        self.assertEqual(health["status"], "ok")
        self.assertEqual(health["catalog_products"], 438)
        self.assertEqual(health["image_feature_dim"], 1152)

    def test_product_includes_grounded_evidence(self) -> None:
        asin = next(iter(self.store.evidence_by_asin))
        product = self.store.product(asin)
        self.assertEqual(product["asin"], asin)
        self.assertTrue(product["evidence"])
        self.assertIn("claim", product["evidence"][0])
        self.assertNotIn("users", product["evidence"][0])

    def test_m0_and_m1_search_exclude_query(self) -> None:
        asin = self.store.asins[0]
        for method in ("m0", "m1"):
            result = self.store.search_by_asin(asin, method=method, k=5)
            self.assertEqual(result["count"], 5)
            self.assertNotIn(asin, [row["asin"] for row in result["results"]])
            self.assertEqual([row["rank"] for row in result["results"]], [1, 2, 3, 4, 5])

    def test_same_category_filter(self) -> None:
        asin = self.store.asins[0]
        category = self.store.product(asin)["category"]
        result = self.store.search_by_asin(
            asin, method="m1", k=10, same_category=True
        )
        self.assertTrue(result["results"])
        self.assertTrue(all(row["category"] == category for row in result["results"]))

    def test_invalid_vector_and_method(self) -> None:
        with self.assertRaises(ValueError):
            self.store.search_by_vector([0.0] * 10)
        with self.assertRaises(ValueError):
            self.store.search_by_asin(self.store.asins[0], method="gnn")

    def test_offline_evaluation_is_exposed(self) -> None:
        result = self.store.evaluation()
        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["k"], 10)
        self.assertGreater(result["cases"], 0)


if __name__ == "__main__":
    unittest.main()
