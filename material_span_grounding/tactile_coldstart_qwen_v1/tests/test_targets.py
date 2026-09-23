from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tactile_coldstart.targets import _agreement, _distribution


class TargetAggregationTest(unittest.TestCase):
    def test_distribution_preserves_disagreement(self) -> None:
        distribution = _distribution([-2.0, -2.0, 2.0], [-2, -1, 0, 1, 2])
        self.assertAlmostEqual(sum(distribution), 1.0)
        self.assertGreater(distribution[0], distribution[-1])
        agreement, entropy = _agreement(distribution)
        self.assertGreater(entropy, 0.0)
        self.assertLess(agreement, 1.0)

    def test_unanimous_is_full_agreement(self) -> None:
        agreement, entropy = _agreement([1.0, 0.0, 0.0, 0.0, 0.0])
        self.assertEqual(entropy, 0.0)
        self.assertEqual(agreement, 1.0)


if __name__ == "__main__":
    unittest.main()

