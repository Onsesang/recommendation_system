from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tactile_coldstart.common import PATHS, load_experiment, read_json
from tactile_coldstart.diagnostics import diagnostic_family_ids


class ProtocolLeakageTest(unittest.TestCase):
    def test_family_splits_are_disjoint(self) -> None:
        config = load_experiment()
        for seed in config["experiment"]["split_seeds"]:
            split = read_json(PATHS.manifests / f"family_split_{seed}.json")["splits"]
            train, development, test = map(set, (split["train"], split["development"], split["test"]))
            self.assertFalse(train & development)
            self.assertFalse(train & test)
            self.assertFalse(development & test)

    def test_axis_selection_excludes_every_evaluated_test(self) -> None:
        config = load_experiment()
        selection = diagnostic_family_ids(config)
        for seed in config["experiment"]["split_seeds"]:
            test = set(read_json(PATHS.manifests / f"family_split_{seed}.json")["splits"]["test"])
            self.assertFalse(selection & test)

    def test_parent_families_are_disjoint_and_v1_seen_is_train_only(self) -> None:
        config = load_experiment()
        payload = read_json(PATHS.manifests / f"family_split_{config['experiment']['seed']}.json")
        train, development, test = map(set, (payload["families"]["train"], payload["families"]["development"], payload["families"]["test"]))
        self.assertFalse(train & development)
        self.assertFalse(train & test)
        self.assertFalse(development & test)
        self.assertTrue(payload["previous_v1_families_forced_train"])
        self.assertTrue(payload["locked_final_test"])


if __name__ == "__main__":
    unittest.main()
