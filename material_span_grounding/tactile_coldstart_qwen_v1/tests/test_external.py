from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tactile_coldstart.external import _pairwise_accuracy


class ExternalMetricTest(unittest.TestCase):
    def test_pairwise_accuracy_ignores_ties(self) -> None:
        accuracy, pairs = _pairwise_accuracy(
            np.asarray([-1.0, 0.0, 1.0]), np.asarray([-2.0, 0.0, 2.0])
        )
        self.assertEqual(pairs, 3)
        self.assertEqual(accuracy, 1.0)


if __name__ == "__main__":
    unittest.main()

