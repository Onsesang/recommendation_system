from __future__ import annotations

import unittest

import numpy as np

from material_span.product_targets import aggregate_product_targets


class ProductTargetTests(unittest.TestCase):
    def test_one_user_one_vote_and_within_user_deduplication(self) -> None:
        claims = [
            {"asin": "A", "user_id": "U1", "review_id": "R1", "claim": "soft"},
            {"asin": "A", "user_id": "U1", "review_id": "R1", "claim": "SOFT"},
            {"asin": "A", "user_id": "U1", "review_id": "R1", "claim": "thin"},
            {"asin": "A", "user_id": "U2", "review_id": "R2", "claim": "warm"},
        ]
        vectors = np.asarray(
            [[1.0, 0.0], [1.0, 0.0], [0.0, 1.0], [-1.0, 0.0]],
            dtype=np.float32,
        )
        targets, stats = aggregate_product_targets(claims, vectors)
        user_one = np.asarray([0.5, 0.5])
        user_one /= np.linalg.norm(user_one)
        expected = user_one + np.asarray([-1.0, 0.0])
        expected /= np.linalg.norm(expected)
        np.testing.assert_allclose(targets["A"], expected, atol=1e-6)
        self.assertEqual(stats["A"]["raw_claims"], 4)
        self.assertEqual(stats["A"]["deduplicated_user_claims"], 3)
        self.assertEqual(stats["A"]["users"], 2)


if __name__ == "__main__":
    unittest.main()
