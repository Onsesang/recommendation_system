from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tactile_coldstart.retrieval import constraint_relevance, ranking_metrics
from tactile_coldstart.selective import risk_coverage_curve, score_threshold


class SelectiveAndRetrievalTest(unittest.TestCase):
    def test_risk_coverage_rewards_correct_confidence_order(self) -> None:
        curve = risk_coverage_curve(
            np.asarray([0.1, 0.3, 0.8]), np.asarray([0.9, 0.6, 0.1])
        )
        self.assertLess(curve["risk"][0], curve["risk"][-1])
        self.assertGreater(curve["aurc"], 0.0)

    def test_threshold_is_fit_to_requested_coverage(self) -> None:
        scores = np.asarray([0.1, 0.2, 0.3, 0.4, 0.5])
        threshold = score_threshold(scores, 0.4)
        self.assertEqual(int(np.sum(scores >= threshold)), 2)

    def test_relevance_uses_direction_and_strength_generically(self) -> None:
        self.assertEqual(constraint_relevance(-2.0, -1, 2.0, 3.0), 3.0)
        self.assertEqual(constraint_relevance(2.0, -1, 2.0, 3.0), 0.0)
        self.assertEqual(constraint_relevance(1.0, 1, 2.0, 3.0), 1.5)

    def test_perfect_ranking(self) -> None:
        relevance = np.asarray([0.0, 1.0, 3.0])
        metrics = ranking_metrics(relevance, relevance.copy(), [2])
        self.assertAlmostEqual(metrics["ndcg@2"], 1.0)
        self.assertAlmostEqual(metrics["pairwise_accuracy"], 1.0)


if __name__ == "__main__":
    unittest.main()
