from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd

from shopping_agent.evaluation import recommendable_data as rd
from shopping_agent.v1.full_catalog import TACTILE_CLASSES


GARMENTS = ["dress", "outerwear", "pants", "skirt", "sleepwear", "sweater", "swimwear", "top", "underwear"]


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class RecommendableDataTests(unittest.TestCase):
    def test_garment_categories_follow_agent_category_specs(self) -> None:
        self.assertEqual(rd.garment_categories(), GARMENTS)

    def test_build_keeps_only_recommendable_products_and_split_labels(self) -> None:
        # Items sorted by parent_asin, as exp16 numbers them: A dress, B necklace, C dress without photo,
        # D pants without tactile, E top.
        metadata = pd.DataFrame({
            "iid": range(5), "parent_asin": list("ABCDE"),
            "title": ["dress", "necklace", "dress", "pants", "shirt"],
            "category": ["dress", "other", "dress", "pants", "top"],
            "image_url": ["a.jpg", "b.jpg", "blank.gif", "d.jpg", "e.jpg"],
        })
        profiles = pd.DataFrame({"parent_asin": ["A", "B", "C", "E"], **{name: 0.5 for name in TACTILE_CLASSES}})
        # u1: A, B, E in train, C validation, A... ; u2 ends on the necklace.
        rows = [
            ("u1", "A", 1, "train"), ("u1", "B", 2, "train"), ("u1", "E", 3, "train"), ("u1", "D", 4, "train"),
            ("u1", "C", 5, "validation"), ("u1", "E2", 6, "test"),
            ("u2", "A", 1, "train"), ("u2", "E", 2, "validation"), ("u2", "B", 3, "test"),
        ]
        events = pd.DataFrame(rows, columns=["user_id", "parent_asin", "timestamp", "split"]).assign(rating=5.0)
        events.loc[events.parent_asin == "E2", "parent_asin"] = "E"
        events = events.drop_duplicates(["user_id", "parent_asin"], keep="last")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            metadata.to_parquet(root / "meta.parquet")
            profiles.to_parquet(root / "profiles.parquet")
            split_dir = root / "split"
            split_dir.mkdir()
            hashes = {}
            for name, (split, _) in rd.SPLIT_FILES.items():
                path = split_dir / f"Amazon_Fashion.{name}.csv"
                events[events.split == split].drop(columns="split").to_csv(path, index=False)
                hashes[name] = (split, _sha(path))
            with mock.patch.multiple(
                rd, SPLIT_DIR=split_dir, SPLIT_FILES=hashes, ITEM_METADATA=root / "meta.parquet",
                TACTILE_PROFILES=root / "profiles.parquet", PROJECT_ROOT=root,
            ):
                manifest = rd.build(root / "out")
                self.assertEqual(rd.check(root / "out"), [])
                data = rd.load(root / "out")
        self.assertEqual(list(data["items"].parent_asin), ["A", "E"])
        self.assertEqual(manifest["items"]["removed_not_garment"], 1)
        self.assertEqual(manifest["items"]["removed_garment_without_photo"], 1)
        self.assertEqual(manifest["items"]["removed_garment_photo_without_tactile"], 1)
        kept = data["events"]
        self.assertTrue(set(kept.parent_asin) <= {"A", "E"})
        # u1's test target E is kept with its label; u2's necklace test target is dropped, not replaced.
        self.assertEqual(list(data["test_targets"].user_id), ["u1"])
        self.assertEqual(data["test_targets"].history_length.tolist(), [1])
        self.assertEqual(list(data["validation_targets"].user_id), ["u2"])
        self.assertEqual(json.loads(json.dumps(manifest))["version"], rd.VERSION)

    def test_check_flags_a_non_recommendable_product(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            items = pd.DataFrame({
                "iid": [0], "source_iid": [0], "parent_asin": ["X"], "category": ["other"], "title": ["ring"],
                "image_url": ["x.jpg"], "train_count": [1], **{name: [0.5] for name in TACTILE_CLASSES},
            })
            empty = pd.DataFrame({"uid": pd.Series(dtype="int32"), "parent_asin": pd.Series(dtype=str)})
            items.to_parquet(out / "items.parquet")
            for name in ("events", "validation_targets", "test_targets"):
                empty.to_parquet(out / f"{name}.parquet")
            files = {path.name: _sha(path) for path in out.glob("*.parquet")}
            manifest = {"files": files, "definition": {"placeholder_image_pattern": r"\.gif$"}}
            (out / "manifest.json").write_text(json.dumps(manifest))
            self.assertIn("items에 옷이 아닌 상품이 있다", rd.check(out))
            (out / "items.parquet").write_bytes(b"changed")
            with self.assertRaises(ValueError):
                rd.load(out)


if __name__ == "__main__":
    unittest.main()
