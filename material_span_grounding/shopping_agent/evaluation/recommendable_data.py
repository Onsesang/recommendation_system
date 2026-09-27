"""Recommendation evaluation data restricted to products the agent can recommend.

Every validation, test and tuning run for recommendation (ranking weights, reranking
logic, personalization) must use this data, not the full Amazon_Fashion split. A
product is recommendable when all three hold:

  garment     its category (item_metadata.parquet, title-keyword heuristic) is one
              the agent's garment categories map to: `CATEGORY_SPECS` broad
              categories of every supported category except `accessory`;
  photo       its image URL is a real photo, not Amazon's placeholder GIF
              (`retrieval.placeholder_image_pattern` in configs/full_catalog.json,
              the same rule the agent's catalog uses);
  tactile     it has a Last2 image-predicted tactile profile.

The source is the official Amazon Reviews'23 `0core/last_out` split used by exp16,
exp17 and exp24, pinned by revision and sha256. The split labels are kept: an event
whose product is not recommendable is dropped, nothing is re-split. Kept targets are
therefore exactly the original targets that are recommendable, and results from earlier
experiments can be re-aggregated on the same users (`source_uid`, `source_iid`).

    python -m shopping_agent.evaluation.recommendable_data            # build
    python -m shopping_agent.evaluation.recommendable_data --check    # verify files

    from shopping_agent.evaluation.recommendable_data import load
    data = load()   # {"items", "events", "validation_targets", "test_targets", "manifest"}
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from demo_agent.models import SUPPORTED_CATEGORIES
from demo_agent.recommender import CATEGORY_SPECS

from shopping_agent.v1.config import PROJECT_ROOT
from shopping_agent.v1.full_catalog import DEFAULT_CONFIG, TACTILE_CLASSES


VERSION = "recommendable_fashion_v1"
OUT_DIR = PROJECT_ROOT / "data" / VERSION
SPLIT_DIR = PROJECT_ROOT / "data/amazon_fashion_0core_last_out"
EXP16 = PROJECT_ROOT / "experiments/16_strong_recommender_tactile"
ITEM_METADATA = EXP16 / "data/item_metadata.parquet"
TACTILE_PROFILES = EXP16 / "artifacts/product_tactile_profiles.parquet"

REVISION = "2aa726ef444e72c6a1364c4baa0bcdfb1de55db6"
SPLIT_URL = (
    "https://huggingface.co/datasets/McAuley-Lab/Amazon-Reviews-2023/resolve/"
    f"{REVISION}/benchmark/0core/last_out/Amazon_Fashion.{{name}}.csv?download=true"
)
# name in the file → split label used by exp16, with the sha256 exp16 verified.
SPLIT_FILES = {
    "train": ("train", "bb685d5b1f166a3bd213a12488714b86e4c927f09b8114e2fd097bb37857dc3c"),
    "valid": ("validation", "5ef546f40fa40ff8bae755924f481eab3062458b23465e1db1aba2efff966ede"),
    "test": ("test", "91bbeaa067e0b1fcab4f8077d51aec2d2860c787d35862a9eff937becea63698"),
}
# exp17's evaluation cohorts: at least this many earlier events before the target.
MIN_HISTORY = 3


def garment_categories() -> list[str]:
    """Metadata categories the agent's garment searches draw candidates from."""
    return sorted({
        broad
        for category in SUPPORTED_CATEGORIES
        if category != "accessory" and category in CATEGORY_SPECS
        for broad in CATEGORY_SPECS[category].broad_categories
    } - {"accessory"})


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _split_file(name: str) -> Path:
    path = SPLIT_DIR / f"Amazon_Fashion.{name}.csv"
    expected = SPLIT_FILES[name][1]
    if not path.exists():
        SPLIT_DIR.mkdir(parents=True, exist_ok=True)
        print(f"downloading {path.name}", flush=True)
        urllib.request.urlretrieve(SPLIT_URL.format(name=name), path)
    actual = _sha256(path)
    if actual != expected:
        raise ValueError(f"{path} sha256 {actual} != pinned {expected}")
    return path


def _history_counts(events: pd.DataFrame, uid_column: str) -> pd.DataFrame:
    return events.groupby([uid_column, "split"]).size().unstack(fill_value=0).reindex(
        columns=["train", "validation", "test"], fill_value=0
    )


def _targets(events: pd.DataFrame, counts: pd.DataFrame, split: str, train_counts: np.ndarray) -> pd.DataFrame:
    target = events[events.split == split].copy()
    history = counts.loc[target.uid]
    target["train_history_length"] = history["train"].to_numpy()
    target["history_length"] = (
        history["train"] + (history["validation"] if split == "test" else 0)
    ).to_numpy()
    target["target_train_count"] = train_counts[target.iid.to_numpy()]
    target[f"in_cohort_history{MIN_HISTORY}"] = target.history_length >= MIN_HISTORY
    return target.drop(columns=["split"]).reset_index(drop=True)


def build(out_dir: Path = OUT_DIR) -> dict[str, Any]:
    frames = []
    for name, (split, _) in SPLIT_FILES.items():
        frame = pd.read_csv(_split_file(name))
        frame["split"] = split
        frames.append(frame)
    events = pd.concat(frames, ignore_index=True)
    # exp16's ids: position in the sorted unique user / parent_asin lists.
    users = np.sort(events.user_id.unique())
    items = np.sort(events.parent_asin.unique())
    events["source_uid"] = pd.Index(users).get_indexer(events.user_id).astype("int32")
    events["source_iid"] = pd.Index(items).get_indexer(events.parent_asin).astype("int32")

    metadata = pd.read_parquet(
        ITEM_METADATA, columns=["iid", "parent_asin", "title", "category", "image_url"]
    ).sort_values("iid")
    if not np.array_equal(metadata.parent_asin.to_numpy(), items):
        raise ValueError("item_metadata.parquet ids do not match the official split's items")
    profiles = pd.read_parquet(TACTILE_PROFILES, columns=["parent_asin", *TACTILE_CLASSES])
    placeholder = json.loads(DEFAULT_CONFIG.read_text(encoding="utf-8"))["retrieval"]["placeholder_image_pattern"]

    catalog = metadata.rename(columns={"iid": "source_iid"}).merge(profiles, on="parent_asin", how="left")
    garments = garment_categories()
    catalog["is_garment"] = catalog.category.isin(garments)
    catalog["has_photo"] = ~catalog.image_url.fillna("").str.contains(placeholder, flags=re.I, regex=True)
    catalog["has_tactile"] = catalog[TACTILE_CLASSES[0]].notna()
    catalog["recommendable"] = catalog.is_garment & catalog.has_photo & catalog.has_tactile

    recommendable = catalog[catalog.recommendable].sort_values("source_iid").reset_index(drop=True)
    recommendable.insert(0, "iid", np.arange(len(recommendable), dtype="int32"))
    kept = events[events.parent_asin.isin(recommendable.parent_asin)].copy()
    kept["iid"] = pd.Index(recommendable.parent_asin).get_indexer(kept.parent_asin).astype("int32")
    kept_users = np.sort(kept.source_uid.unique())
    kept["uid"] = pd.Index(kept_users).get_indexer(kept.source_uid).astype("int32")
    kept = kept.sort_values(["uid", "timestamp", "iid"], kind="stable").reset_index(drop=True)
    kept = kept[["uid", "iid", "user_id", "parent_asin", "rating", "timestamp", "split", "source_uid", "source_iid"]]

    train_counts = np.bincount(kept.loc[kept.split == "train", "iid"], minlength=len(recommendable)).astype("int32")
    recommendable["train_count"] = train_counts
    columns = ["iid", "source_iid", "parent_asin", "category", "title", "image_url", "train_count", *TACTILE_CLASSES]
    recommendable = recommendable[columns]

    counts = _history_counts(kept, "uid")
    validation_targets = _targets(kept, counts, "validation", train_counts)
    test_targets = _targets(kept, counts, "test", train_counts)

    # The same users under the original (unfiltered) cohort rule, for re-aggregating old results.
    source_counts = _history_counts(events, "source_uid")
    for frame, split in ((validation_targets, "validation"), (test_targets, "test")):
        history = source_counts.loc[frame.source_uid]
        original = history["train"] + (history["validation"] if split == "test" else 0)
        frame[f"in_source_cohort_history{MIN_HISTORY}"] = (original >= MIN_HISTORY).to_numpy()

    # Temporal order must survive the filtering: train ≤ validation ≤ test per user.
    bounds = kept.groupby(["uid", "split"]).timestamp.agg(["min", "max"]).unstack()
    for earlier, later in (("train", "validation"), ("validation", "test"), ("train", "test")):
        mask = bounds["max"][earlier].notna() & bounds["min"][later].notna()
        if not (bounds["max"][earlier][mask] <= bounds["min"][later][mask]).all():
            raise ValueError(f"{earlier} events after {later} events after filtering")

    out_dir.mkdir(parents=True, exist_ok=True)
    recommendable.to_parquet(out_dir / "items.parquet", index=False)
    kept.to_parquet(out_dir / "events.parquet", index=False)
    validation_targets.to_parquet(out_dir / "validation_targets.parquet", index=False)
    test_targets.to_parquet(out_dir / "test_targets.parquet", index=False)

    removed = catalog[~catalog.recommendable]
    source_targets = {split: events[events.split == split] for split in ("validation", "test")}
    manifest = {
        "version": VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "rule": "추천 성능 검증, 가중치 조정, 추천 로직 비교는 이 데이터로만 한다.",
        "definition": {
            "garment_categories": garments,
            "placeholder_image_pattern": placeholder,
            "tactile": "Last2 image-predicted profile present",
            "split": "official 0core/last_out labels kept; events on non-recommendable products dropped; no re-split",
            "cohort": f"in_cohort_history{MIN_HISTORY}: at least {MIN_HISTORY} kept events before the target",
        },
        "sources": {
            "split": {"repository": "McAuley-Lab/Amazon-Reviews-2023", "revision": REVISION,
                      "sha256": {name: sha for name, (_, sha) in SPLIT_FILES.items()}},
            "item_metadata": {"path": str(ITEM_METADATA.relative_to(PROJECT_ROOT)), "sha256": _sha256(ITEM_METADATA)},
            "tactile_profiles": {"path": str(TACTILE_PROFILES.relative_to(PROJECT_ROOT)),
                                 "sha256": _sha256(TACTILE_PROFILES)},
        },
        "items": {
            "source": int(len(catalog)),
            "recommendable": int(len(recommendable)),
            "removed_not_garment": int((~removed.is_garment).sum()),
            "removed_garment_without_photo": int((removed.is_garment & ~removed.has_photo).sum()),
            "removed_garment_photo_without_tactile": int(
                (removed.is_garment & removed.has_photo & ~removed.has_tactile).sum()
            ),
            "by_category": {key: int(value) for key, value in recommendable.category.value_counts().items()},
        },
        "events": {
            "source": int(len(events)),
            "kept": int(len(kept)),
            "kept_by_split": {key: int(value) for key, value in kept.split.value_counts().items()},
            "users": int(len(kept_users)),
            "items_seen_in_train": int((train_counts > 0).sum()),
        },
        "targets": {
            split: {
                "source": int(len(source_targets[split])),
                "kept": int(len(frame)),
                f"cohort_history{MIN_HISTORY}": int(frame[f"in_cohort_history{MIN_HISTORY}"].sum()),
                f"source_cohort_history{MIN_HISTORY}": int(frame[f"in_source_cohort_history{MIN_HISTORY}"].sum()),
                f"cohort_history{MIN_HISTORY}_target_unseen_in_train": int(
                    (frame[f"in_cohort_history{MIN_HISTORY}"] & (frame.target_train_count == 0)).sum()
                ),
            }
            for split, frame in (("validation", validation_targets), ("test", test_targets))
        },
        "files": {},
    }
    for path in sorted(out_dir.glob("*.parquet")):
        manifest["files"][path.name] = _sha256(path)
    (out_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def load(data_dir: Path = OUT_DIR, *, verify: bool = True) -> dict[str, Any]:
    """The recommendable-only split. `verify` checks the files against the manifest hashes."""
    manifest = json.loads((data_dir / "manifest.json").read_text(encoding="utf-8"))
    if verify:
        for name, expected in manifest["files"].items():
            if _sha256(data_dir / name) != expected:
                raise ValueError(f"{data_dir / name} changed since it was built; rebuild it")
    return {
        "manifest": manifest,
        "items": pd.read_parquet(data_dir / "items.parquet"),
        "events": pd.read_parquet(data_dir / "events.parquet"),
        "validation_targets": pd.read_parquet(data_dir / "validation_targets.parquet"),
        "test_targets": pd.read_parquet(data_dir / "test_targets.parquet"),
    }


def check(data_dir: Path = OUT_DIR) -> list[str]:
    """Problems that would let a non-recommendable product into an evaluation."""
    data = load(data_dir)
    items, events = data["items"], data["events"]
    problems = []
    if not items.category.isin(garment_categories()).all():
        problems.append("items에 옷이 아닌 상품이 있다")
    if items[list(TACTILE_CLASSES)].isna().any().any():
        problems.append("items에 촉감 예측이 없는 상품이 있다")
    placeholder = data["manifest"]["definition"]["placeholder_image_pattern"]
    if items.image_url.fillna("").str.contains(placeholder, flags=re.I, regex=True).any():
        problems.append("items에 사진 없는 상품이 있다")
    if not events.parent_asin.isin(items.parent_asin).all():
        problems.append("events에 items 밖 상품이 있다")
    for split in ("validation_targets", "test_targets"):
        if not data[split].parent_asin.isin(items.parent_asin).all():
            problems.append(f"{split}에 items 밖 상품이 있다")
        if data[split].uid.duplicated().any():
            problems.append(f"{split}에 사용자당 정답이 2개 이상")
    return problems


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out-dir", type=Path, default=OUT_DIR)
    parser.add_argument("--check", action="store_true", help="저장된 파일만 검사한다")
    args = parser.parse_args()
    if not args.check:
        manifest = build(args.out_dir)
        print(json.dumps({key: manifest[key] for key in ("items", "events", "targets")}, ensure_ascii=False, indent=1))
    problems = check(args.out_dir)
    print("OK" if not problems else "\n".join(problems))
    if problems:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
