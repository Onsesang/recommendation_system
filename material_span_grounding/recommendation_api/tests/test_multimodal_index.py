from __future__ import annotations

import unittest

from recommendation_api.multimodal_index import MultimodalProductIndex
from recommendation_api.tactile_catalog import TactileCatalogService
from recommendation_api.tactile_store import TactileStore


class MultimodalProductIndexTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.store = TactileStore()
        cls.index = MultimodalProductIndex()
        cls.catalog = TactileCatalogService(cls.store)

    def test_product_master_is_independent_of_review_target_availability(self) -> None:
        self.assertEqual(len(self.index.product_ids), 465)
        predicted_only = [
            product_id
            for product_id in self.index.product_ids
            if self.index.target_info(product_id)["tactile_target_source"] == "image_predicted"
        ]
        self.assertEqual(len(predicted_only), 4)
        for product_id in predicted_only:
            self.assertEqual(self.catalog._public_product(product_id)["tactile_status"], "insufficient_evidence")
            self.assertEqual(
                self.catalog._public_product(product_id)["tactile_target_source"],
                "image_predicted",
            )

    def test_every_catalog_product_has_image_and_tactile_vectors(self) -> None:
        for product_id in self.index.product_ids:
            self.assertEqual(self.index.image_vector(product_id).shape, (512,))
            self.assertEqual(self.index.tactile_vector(product_id).shape, (384,))

    def test_predicted_only_product_can_retrieve_tactile_neighbors(self) -> None:
        anchor = next(
            product_id
            for product_id in self.index.product_ids
            if self.index.target_info(product_id)["tactile_target_source"] == "image_predicted"
        )
        result = self.catalog.related(anchor, limit=5)
        self.assertTrue(result["tactile_similar"])
        self.assertTrue(
            all(row["method"] == "same_category_hybrid_tactile_cosine" for row in result["tactile_similar"])
        )


if __name__ == "__main__":
    unittest.main()
