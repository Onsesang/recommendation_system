import unittest

from audit_app.build_v2_manifest import select_review_complete_sample


class ReviewCompleteSampleTest(unittest.TestCase):
    def setUp(self):
        self.rows = []
        self.input_by_id = {}
        for review_id, size in (("r1", 3), ("r2", 2), ("r3", 2), ("r4", 1)):
            for index in range(size):
                span_id = f"{review_id}-{index}"
                self.rows.append(
                    {
                        "review_id": review_id,
                        "span_id": span_id,
                        "accepted": index % 2 == 0,
                    }
                )
                self.input_by_id[span_id] = {
                    "extraction_sources": ["surface_use"]
                    if index == 0
                    else ["v1"]
                }

    def test_exact_size_keeps_whole_reviews_and_is_deterministic(self):
        first, summary = select_review_complete_sample(
            self.rows, 5, {"r3"}, self.input_by_id, seed=17, trials=500
        )
        second, _ = select_review_complete_sample(
            self.rows, 5, {"r3"}, self.input_by_id, seed=17, trials=500
        )
        self.assertEqual(5, len(first))
        self.assertEqual(
            [row["span_id"] for row in first], [row["span_id"] for row in second]
        )
        selected_reviews = {row["review_id"] for row in first}
        for review_id in selected_reviews:
            self.assertEqual(
                sum(row["review_id"] == review_id for row in self.rows),
                sum(row["review_id"] == review_id for row in first),
            )
        self.assertEqual(5, summary["target_items"])

    def test_rejects_impossible_target(self):
        with self.assertRaises(ValueError):
            select_review_complete_sample(
                self.rows, 9, set(), self.input_by_id, seed=17, trials=10
            )


if __name__ == "__main__":
    unittest.main()
