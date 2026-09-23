from __future__ import annotations

import math
import unittest

from offline_eval.metrics import aggregate_ranking_metrics, bootstrap_delta, ranking_metrics


class RankingMetricsTest(unittest.TestCase):
    def test_single_relevant_at_rank_three(self) -> None:
        values = ranking_metrics(["a", "b", "target", "c"], {"target"}, 3)
        self.assertAlmostEqual(values["recall"], 1.0)
        self.assertAlmostEqual(values["hit_rate"], 1.0)
        self.assertAlmostEqual(values["precision"], 1 / 3)
        self.assertAlmostEqual(values["ndcg"], 1 / math.log2(4))
        self.assertAlmostEqual(values["mrr"], 1 / 3)
        self.assertAlmostEqual(values["map"], 1 / 3)

    def test_miss(self) -> None:
        values = ranking_metrics(["a", "b", "c"], {"target"}, 3)
        for name in ("recall", "hit_rate", "precision", "ndcg", "mrr", "map"):
            self.assertEqual(values[name], 0.0)

    def test_multiple_relevant(self) -> None:
        values = ranking_metrics(["x", "a", "b", "z"], {"a", "b"}, 3)
        self.assertEqual(values["recall"], 1.0)
        self.assertAlmostEqual(values["precision"], 2 / 3)
        self.assertAlmostEqual(values["map"], ((1 / 2) + (2 / 3)) / 2)

    def test_aggregate(self) -> None:
        first = ranking_metrics(["x"], {"x"}, 1)
        second = ranking_metrics(["y"], {"x"}, 1)
        result = aggregate_ranking_metrics([first, second], 1)
        self.assertEqual(result["cases"], 2)
        self.assertEqual(result["recall@1"], 0.5)
        self.assertEqual(result["ndcg@1"], 0.5)

    def test_bootstrap_paired_delta(self) -> None:
        result = bootstrap_delta([0, 0, 0], [1, 1, 1], seed=1, samples=100)
        self.assertEqual(result["delta"], 1.0)
        self.assertEqual(result["ci95_low"], 1.0)
        self.assertEqual(result["probability_positive"], 1.0)


if __name__ == "__main__":
    unittest.main()
