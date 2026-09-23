from __future__ import annotations

import unittest

from recommendation_api.tactile_agent import parse_tactile_intent
from recommendation_api.tactile_catalog import TactileCatalogService
from recommendation_api.tactile_store import TactileStore


class TactileCatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.store = TactileStore()
        cls.catalog = TactileCatalogService(cls.store)

    def test_catalog_has_thirty_unique_items_per_page(self) -> None:
        first = self.catalog.catalog()
        last = self.catalog.catalog(page=first["total_pages"])
        self.assertLess(first["total"], len(self.store.source_asins))
        self.assertEqual(first["page_size"], 30)
        self.assertEqual(len(first["items"]), 30)
        self.assertLessEqual(len(last["items"]), 30)
        self.assertTrue(all(item["image_url"] and item["title"] for item in first["items"]))
        all_items = []
        for page in range(1, first["total_pages"] + 1):
            all_items.extend(self.catalog.catalog(page=page)["items"])
        identities = [
            self.catalog._identity_by_asin[item["product_id"]] for item in all_items
        ]
        self.assertEqual(len(identities), len(set(identities)))
        self.assertEqual(len(all_items), first["total"])

    def test_washing_non_stretch_skirt_intent_and_search(self) -> None:
        text = "세탁 후 잘 늘어나지 않는 치마를 찾아줘."
        intent = parse_tactile_intent(text)
        self.assertEqual(intent.category, "skirt")
        self.assertIn("stretchiness", intent.desired_less)
        self.assertNotIn("stretchiness", intent.desired_more)
        result = self.catalog.search({"query_text": text, "page": 1})
        self.assertEqual(result["page_size"], 30)
        self.assertTrue(result["items"])
        self.assertTrue(all(item["category"] == "skirt" for item in result["items"]))
        identities = [
            self.catalog._identity_by_asin[item["product_id"]]
            for item in result["items"]
        ]
        self.assertEqual(len(identities), len(set(identities)))
        scores = [item["relevance_score"] for item in result["items"]]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_related_products_are_ranked_and_same_category(self) -> None:
        anchor = self.store.target_asins[0]
        result = self.catalog.related(anchor, limit=5)
        for group in ("design_similar", "tactile_similar"):
            self.assertTrue(result[group])
            self.assertTrue(all(item["product_id"] != anchor for item in result[group]))
            anchor_identity = self.catalog._identity_by_asin[anchor]
            identities = [
                self.catalog._identity_by_asin[item["product_id"]]
                for item in result[group]
            ]
            self.assertNotIn(anchor_identity, identities)
            self.assertEqual(len(identities), len(set(identities)))
            self.assertTrue(all(item["category"] == result["category"] for item in result[group]))
            scores = [item["relevance_score"] for item in result[group]]
            self.assertEqual(scores, sorted(scores, reverse=True))
        self.assertIn("method", result["design_similar"][0])
        self.assertIn("tactile_cosine", result["tactile_similar"][0])

    def test_pagination_validation(self) -> None:
        with self.assertRaises(ValueError):
            self.catalog.catalog(page=0)
        with self.assertRaises(ValueError):
            self.catalog.catalog(page=self.catalog.catalog()["total_pages"] + 1)
        with self.assertRaises(ValueError):
            self.catalog.search({"query_text": ""})


if __name__ == "__main__":
    unittest.main()
