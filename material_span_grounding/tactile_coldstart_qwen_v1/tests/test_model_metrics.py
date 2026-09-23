from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tactile_coldstart.modeling import _metrics, _weights


class ModelMetricTest(unittest.TestCase):
    def test_perfect_order(self) -> None:
        values = np.asarray([-2.0, -1.0, 1.0, 2.0])
        result = _metrics(values, values.copy(), np.asarray(["a", "a", "a", "a"]))
        self.assertAlmostEqual(result["spearman"], 1.0)
        self.assertAlmostEqual(result["pairwise_accuracy"], 1.0)

    def test_weights_are_generic_and_normalized(self) -> None:
        support = np.asarray([1.0, 2.0, 4.0])
        agreement = np.asarray([0.5, 0.8, 1.0])
        for name in ("W0", "W1", "W2", "W3"):
            self.assertAlmostEqual(float(_weights(name, support, agreement).mean()), 1.0)


if __name__ == "__main__":
    unittest.main()

