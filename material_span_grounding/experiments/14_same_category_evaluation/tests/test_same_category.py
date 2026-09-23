from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np
from sklearn.metrics import average_precision_score


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from common import aggregate_cells, average_precision_tie_safe, cell_metrics, pairwise_accuracy


class SameCategoryMetricTests(unittest.TestCase):
    def test_constant_predictor_has_chance_auc_and_zero_ap_lift(self):
        truth = np.asarray([1, 1, 0, 0], dtype=bool)
        scores = np.full(4, 0.7)
        row = cell_metrics(truth, scores, 0.5, 2, 2)
        self.assertEqual(row["auroc"], 0.5)
        self.assertEqual(row["pairwise_accuracy"], 0.5)
        self.assertAlmostEqual(row["average_precision"], 0.5)
        self.assertAlmostEqual(row["ap_lift"], 0.0)
        self.assertTrue(row["reliable_support"])

    def test_pairwise_ties_receive_half_credit(self):
        positive = np.asarray([0.9, 0.5])
        negative = np.asarray([0.5, 0.1])
        self.assertAlmostEqual(pairwise_accuracy(positive, negative), 0.875)

    def test_single_class_cells_are_skipped_with_reason(self):
        row = cell_metrics(np.asarray([1, 1], dtype=bool), np.asarray([0.2, 0.8]), 0.5, 10, 10)
        self.assertFalse(row["valid"])
        self.assertEqual(row["skip_reason"], "positive_only")
        self.assertIsNone(row["auroc"])

    def test_pair_weighted_aggregate(self):
        first = cell_metrics(np.asarray([1, 0]), np.asarray([0.9, 0.1]), 0.5, 1, 1)
        second = cell_metrics(np.asarray([1, 1, 0]), np.asarray([0.1, 0.2, 0.9]), 0.5, 1, 1)
        aggregate = aggregate_cells([first, second])
        self.assertAlmostEqual(aggregate["macro_cell_auroc"], 0.5)
        self.assertAlmostEqual(aggregate["pair_weighted_auroc"], 1.0 / 3.0)

    def test_tie_safe_average_precision_constant_equals_prevalence(self):
        truth = np.asarray([1, 0, 0, 1, 0], dtype=bool)
        self.assertAlmostEqual(average_precision_tie_safe(truth, np.ones(5)), 0.4)

    def test_tie_safe_average_precision_matches_sklearn_with_ties(self):
        truth = np.asarray([1, 0, 1, 0, 0, 1, 0], dtype=bool)
        scores = np.asarray([0.8, 0.8, 0.6, 0.4, 0.4, 0.4, 0.1])
        self.assertAlmostEqual(
            average_precision_tie_safe(truth, scores),
            average_precision_score(truth, scores),
            places=12,
        )


if __name__ == "__main__":
    unittest.main()
