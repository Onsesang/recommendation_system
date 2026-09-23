from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tactile_coldstart.reporting import bootstrap_mean_ci


class ReportingTest(unittest.TestCase):
    def test_bootstrap_is_deterministic_and_contains_mean(self) -> None:
        values = np.asarray([0.2, 0.4, 0.6, 0.8])
        first = bootstrap_mean_ci(values, 200, 0.95, 7)
        second = bootstrap_mean_ci(values, 200, 0.95, 7)
        self.assertEqual(first, second)
        self.assertLessEqual(first[1], first[0])
        self.assertGreaterEqual(first[2], first[0])


if __name__ == "__main__":
    unittest.main()
