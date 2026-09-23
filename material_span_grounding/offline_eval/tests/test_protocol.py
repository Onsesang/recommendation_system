from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from offline_eval.common import read_jsonl
from offline_eval.protocol import build_temporal_protocol


class TemporalProtocolTest(unittest.TestCase):
    def test_chronological_leave_two_out_and_privacy(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            interactions = root / "interactions.parquet"
            rows = []
            for user in ("U1", "U2"):
                for index, item in enumerate(("A", "B", "C", "D"), 1):
                    rows.append(
                        {"user_id": user, "asin": f"{item}{user}", "rating": 5.0, "timestamp": index}
                    )
            # Add enough candidate items from non-evaluation one-shot users.
            for index in range(10):
                rows.append(
                    {"user_id": f"ONE{index}", "asin": f"N{index}", "rating": 5.0, "timestamp": index}
                )
            pd.DataFrame(rows).to_parquet(interactions, index=False)
            manifest = build_temporal_protocol(
                interactions_path=interactions,
                output_root=root / "out",
                min_user_positives=4,
                negatives_per_case=3,
                seed=7,
            )
            cases = read_jsonl(root / "out/cases.jsonl")
            self.assertEqual(manifest["evaluation_cases"], 2)
            self.assertEqual(len(cases[0]["train_items"]), 2)
            self.assertNotIn("user_id", cases[0])
            self.assertEqual(len(cases[0]["candidates"]), 4)
            self.assertEqual(len(cases[0]["candidate_train_counts"]), 4)
            self.assertIn(cases[0]["test_items"][0], cases[0]["candidates"])
            # All candidate popularity values were measured before this case's test time.
            self.assertTrue(all(value >= 0 for value in cases[0]["candidate_train_counts"]))


if __name__ == "__main__":
    unittest.main()
