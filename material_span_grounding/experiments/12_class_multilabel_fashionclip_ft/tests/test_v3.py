import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("ground_classes", ROOT / "scripts" / "ground_classes.py")
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(MODULE)


class GroundingParserTest(unittest.TestCase):
    def test_valid_atomic_classes(self):
        labels, unmappable, error = MODULE.parse_json(
            '{"classes":[{"id":"soft","polarity":"present","confidence":0.9}],"unmappable":false}',
            {"soft", "firm"},
        )
        self.assertEqual(labels[0]["id"], "soft")
        self.assertFalse(unmappable)
        self.assertIsNone(error)

    def test_unknown_class_fails_closed(self):
        labels, _, _ = MODULE.parse_json(
            '{"classes":[{"id":"comfortable","polarity":"present","confidence":1.0}],"unmappable":false}',
            {"soft"},
        )
        self.assertEqual(labels, [])

    def test_compact_schema(self):
        labels, unmappable, error = MODULE.parse_json(
            '{"c":[["rough","p",0.8],["soft","a",0.7]],"u":false}',
            {"rough", "soft"},
        )
        self.assertEqual([item["polarity"] for item in labels], ["present", "absent"])
        self.assertFalse(unmappable)
        self.assertIsNone(error)


if __name__ == "__main__":
    unittest.main()
