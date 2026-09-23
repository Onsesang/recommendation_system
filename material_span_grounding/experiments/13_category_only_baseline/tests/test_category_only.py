from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

import numpy as np
import torch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from common import CategoryClassifier, calculate_metrics, choose_thresholds, masked_bce


class CategoryOnlyTests(unittest.TestCase):
    def test_model_accepts_only_category_ids_and_has_expected_shape(self):
        model = CategoryClassifier(12, 64, 14)
        output = model(torch.tensor([0, 1, 11]))
        self.assertEqual(tuple(output.shape), (3, 14))
        self.assertEqual(
            set(model.state_dict()),
            {"category_embedding.weight", "classifier.weight", "classifier.bias"},
        )

    def test_masked_bce_ignores_unobserved_values(self):
        logits = torch.tensor([[0.2, -0.5], [1.0, 0.3]])
        first_values = torch.tensor([[1.0, 0.0], [0.0, 1.0]])
        second_values = torch.tensor([[1.0, 1.0], [0.0, 0.0]])
        mask = torch.tensor([[1.0, 0.0], [1.0, 0.0]])
        weight = torch.ones(2)
        self.assertAlmostEqual(
            masked_bce(logits, first_values, mask, weight).item(),
            masked_bce(logits, second_values, mask, weight).item(),
            places=7,
        )

    def test_threshold_grid_and_metric_mask(self):
        logits = np.asarray([[3.0], [-3.0], [100.0]], dtype=np.float32)
        values = np.asarray([[1.0], [0.0], [0.0]], dtype=np.float32)
        masks = np.asarray([[1], [1], [0]], dtype=np.uint8)
        thresholds = choose_thresholds(logits, values, masks, 0.1, 0.9, 0.05)
        self.assertAlmostEqual(float(thresholds[0]), 0.1, places=6)
        result = calculate_metrics(logits, values, masks, thresholds, ["soft"])
        self.assertEqual(result["observed_pairs"], 2)
        self.assertEqual(result["per_class"]["soft"]["observed"], 2)
        self.assertEqual(result["per_class"]["soft"]["negative"], 1)
        self.assertAlmostEqual(result["per_class"]["soft"]["f1"], 1.0)


if __name__ == "__main__":
    unittest.main()
