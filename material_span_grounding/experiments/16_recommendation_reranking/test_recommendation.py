from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from common import ARTIFACTS, percentile_rank, read_json
from recommender_core import load_cases, load_events
from recommend import RecommendationService


class RecommendationExperimentTests(unittest.TestCase):
    def test_percentile_average_ties(self):
        np.testing.assert_allclose(percentile_rank(np.array([1., 2., 2., 4.])), [0., .5, .5, 1.])

    def test_target_not_in_history(self):
        events = load_events(); cases = load_cases("test")
        history = events[events.split.isin(["train", "validation"])]
        pairs = set(zip(history.user_id, history.item_id))
        self.assertFalse(any((r.user_id, r.target_item) in pairs for r in cases.itertuples()))

    def test_alpha_zero_identity(self):
        selection = read_json(ARTIFACTS / "selection.json")
        self.assertTrue(selection["alpha_zero_equals_category"])
        result = read_json(ARTIFACTS / "recommendation_results.json")
        if selection["alpha_star"] == 0:
            self.assertEqual(result["test_metrics"]["category_aware"], result["test_metrics"]["proposed"])

    def test_checkpoint_unchanged(self):
        self.assertTrue(read_json(ARTIFACTS / "tactile_profile_manifest.json")["checkpoint_unchanged"])

    def test_service_smoke(self):
        service = RecommendationService("cpu")
        result = service.recommend(service.known_users[0], ["soft", "smooth"], top_k=5)
        self.assertEqual(set(result["methods"]), {"vanilla", "category_aware", "proposed"})
        self.assertTrue(all(len(items) == 5 for items in result["methods"].values()))


if __name__ == "__main__":
    unittest.main()
