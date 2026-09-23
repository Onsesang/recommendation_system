from __future__ import annotations

import unittest

from offline_eval.tactile_system_eval import _rank_case
from recommendation_api.tactile_store import TactileStore


class TactileSystemEvaluationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.store = TactileStore()

    def test_identical_candidates_and_context_gate_off_without_explicit_intent(self) -> None:
        items = self.store.target_asins[:4]
        case = {
            "candidates": items,
            "candidate_train_counts": [10, 3, 2, 0],
            "train_items": items[:2],
        }
        result = _rank_case(case, self.store)
        self.assertEqual(set(result), {"no_tactile", "global_tactile", "category_conditioned", "context_gated"})
        self.assertTrue(all(set(values) == set(items) for values in result.values()))
        self.assertEqual(result["context_gated"], result["no_tactile"])


if __name__ == "__main__":
    unittest.main()

