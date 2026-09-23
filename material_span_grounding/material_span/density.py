from __future__ import annotations

import heapq
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from .common import (
    ROOT,
    load_config,
    load_json,
    save_json,
    sha256_file,
    sha256_text,
    write_jsonl,
)


def _plain(value: Any) -> Any:
    if value is None:
        return None
    if hasattr(value, "item"):
        return value.item()
    return value


def _threshold_counts(values: list[int], thresholds: tuple[int, ...]) -> dict[str, int]:
    return {str(threshold): sum(value >= threshold for value in values) for threshold in thresholds}


def build_product_dense_sample(
    *,
    min_users: int = 5,
    max_reviews_per_product: int = 10,
    max_products: int = 500,
    output_root: Path | None = None,
) -> dict[str, Any]:
    """Scan train-only reviews and create a deterministic product-dense corpus."""
    if min_users < 1 or max_reviews_per_product < min_users or max_products < 1:
        raise ValueError("Require min_users >= 1, max_reviews >= min_users, max_products >= 1")

    cfg = load_config()
    split_path = Path(cfg["product_split"])
    split_rows = load_json(split_path)
    train_asins = {str(row["asin"]) for row in split_rows}
    image_root = Path("/home/user/onsesang/texture_project/images_train")
    image_asins = {path.stem for path in image_root.glob("*.jpg")}
    eligible_asins = train_asins & image_asins

    from datasets import load_from_disk

    dataset = load_from_disk(cfg["review_dataset"])["full"]
    columns = dataset.select_columns(
        ["asin", "user_id", "text", "rating", "timestamp", "verified_purchase"]
    )
    min_chars = int(cfg["min_review_chars"])
    max_chars = int(cfg["max_review_chars"])
    # Keep the deterministic minimum-hash review for each product/user pair.
    per_product_user: dict[str, dict[str, tuple[int, dict[str, Any]]]] = defaultdict(dict)
    eligible_review_counts: Counter[str] = Counter()
    scanned = 0
    eligible = 0
    for batch_i, batch in enumerate(columns.to_pandas(batched=True, batch_size=200_000), 1):
        for asin, user_id, text, rating, timestamp, verified in zip(
            batch["asin"],
            batch["user_id"],
            batch["text"],
            batch["rating"],
            batch["timestamp"],
            batch["verified_purchase"],
        ):
            scanned += 1
            asin = str(asin)
            if asin not in eligible_asins or text is None:
                continue
            text = str(text).strip()
            if not (min_chars <= len(text) <= max_chars):
                continue
            eligible += 1
            eligible_review_counts[asin] += 1
            user = "" if user_id is None else str(user_id).strip()
            stamp = "" if timestamp is None else str(_plain(timestamp))
            review_key = f"{asin}\x1f{user}\x1f{stamp}\x1f{text}"
            review_id = sha256_text(review_key)[:20]
            user_key = user or f"missing:{review_id}"
            score = int(sha256_text(f"{cfg['seed']}\x1f{review_key}")[:16], 16)
            row = {
                "review_id": review_id,
                "asin": asin,
                "user_id": user,
                "rating": _plain(rating),
                "timestamp": _plain(timestamp),
                "verified_purchase": bool(verified) if verified is not None else None,
                "text": text,
                "text_chars": len(text),
                "selection_hash": f"{score:016x}",
            }
            previous = per_product_user[asin].get(user_key)
            if previous is None or score < previous[0]:
                per_product_user[asin][user_key] = (score, row)
        print(
            f"[density] batch={batch_i} scanned={scanned:,} eligible={eligible:,}",
            flush=True,
        )

    unique_user_counts = {asin: len(rows) for asin, rows in per_product_user.items()}
    dense_pool = [asin for asin, count in unique_user_counts.items() if count >= min_users]
    dense_pool.sort(key=lambda asin: (sha256_text(f"{cfg['seed']}\x1fproduct\x1f{asin}"), asin))
    selected_asins = dense_pool[:max_products]

    selected_reviews: list[dict[str, Any]] = []
    selected_product_counts: dict[str, int] = {}
    for asin in selected_asins:
        candidates = [entry[1] for entry in per_product_user[asin].values()]
        chosen = heapq.nsmallest(
            max_reviews_per_product,
            candidates,
            key=lambda row: (row["selection_hash"], row["review_id"]),
        )
        selected_reviews.extend(chosen)
        selected_product_counts[asin] = len(chosen)
    selected_reviews.sort(key=lambda row: (row["asin"], row["selection_hash"], row["review_id"]))

    output_root = output_root or ROOT / "data" / "dense"
    reviews_path = output_root / "reviews_product_dense.jsonl"
    write_jsonl(reviews_path, selected_reviews)
    thresholds = (1, 2, 3, 5, 10, 20)
    all_user_values = list(unique_user_counts.values())
    all_review_values = [eligible_review_counts[asin] for asin in unique_user_counts]
    manifest = {
        "status": "complete",
        "source_dataset": cfg["review_dataset"],
        "source_split": str(split_path),
        "source_split_sha256": sha256_file(split_path),
        "protected_test_used": False,
        "scanned_dataset_rows": scanned,
        "eligible_train_reviews_with_image": eligible,
        "train_products": len(train_asins),
        "train_products_with_local_image": len(eligible_asins),
        "products_with_eligible_reviews": len(unique_user_counts),
        "products_by_min_unique_users": _threshold_counts(all_user_values, thresholds),
        "products_by_min_eligible_reviews": _threshold_counts(all_review_values, thresholds),
        "selection": {
            "min_unique_users": min_users,
            "max_reviews_per_product": max_reviews_per_product,
            "max_products": max_products,
            "selected_products": len(selected_asins),
            "selected_reviews": len(selected_reviews),
            "reviews_per_product": dict(Counter(selected_product_counts.values())),
            "one_review_per_user": True,
            "image_required": True,
            "seed": cfg["seed"],
        },
        "output": str(reviews_path),
        "output_sha256": sha256_file(reviews_path),
    }
    save_json(output_root / "density_manifest.json", manifest)
    return manifest
