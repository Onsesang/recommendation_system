from __future__ import annotations

import heapq
from collections import defaultdict
from pathlib import Path
from typing import Any

from .common import ROOT, load_config, load_json, save_json, sha256_file, sha256_text, write_jsonl


def _plain(value: Any) -> Any:
    if value is None:
        return None
    if hasattr(value, "item"):
        return value.item()
    return value


def build_sample(limit: int | None = None) -> dict[str, Any]:
    cfg = load_config()
    requested = int(limit or cfg["pilot_reviews"])
    max_per_product = int(cfg["max_reviews_per_product"])
    min_chars = int(cfg["min_review_chars"])
    max_chars = int(cfg["max_review_chars"])
    split_path = Path(cfg["product_split"])
    split_rows = load_json(split_path)
    train_asins = {str(row["asin"]) for row in split_rows}

    from datasets import load_from_disk

    dataset = load_from_disk(cfg["review_dataset"])["full"]
    columns = dataset.select_columns(
        ["asin", "user_id", "text", "rating", "timestamp", "verified_purchase"]
    )
    per_product: dict[str, list[tuple[int, str, dict[str, Any]]]] = defaultdict(list)
    scanned = 0
    eligible = 0
    for batch_i, batch in enumerate(
        columns.to_pandas(batched=True, batch_size=200_000), 1
    ):
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
            if asin not in train_asins or text is None:
                continue
            text = str(text).strip()
            if not (min_chars <= len(text) <= max_chars):
                continue
            eligible += 1
            user = "" if user_id is None else str(user_id)
            stamp = "" if timestamp is None else str(_plain(timestamp))
            review_key = f"{asin}\x1f{user}\x1f{stamp}\x1f{text}"
            review_id = sha256_text(review_key)[:20]
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
            heap = per_product[asin]
            entry = (-score, review_id, row)
            if len(heap) < max_per_product:
                heapq.heappush(heap, entry)
            elif score < -heap[0][0]:
                heapq.heapreplace(heap, entry)
        print(
            f"[sample] batch={batch_i} scanned={scanned:,} eligible={eligible:,}",
            flush=True,
        )

    candidates = [entry[2] for heap in per_product.values() for entry in heap]
    # The source dataset can contain byte-identical duplicate review rows.
    # Keep one copy so every pilot review has a unique provenance key.
    candidates = list({row["review_id"]: row for row in candidates}.values())
    candidates.sort(key=lambda row: (row["selection_hash"], row["review_id"]))
    selected = candidates[:requested]
    output = ROOT / "data" / "input" / "reviews_pilot.jsonl"
    write_jsonl(output, selected)
    manifest = {
        "requested_reviews": requested,
        "selected_reviews": len(selected),
        "selected_products": len({row["asin"] for row in selected}),
        "selected_users": len({row["user_id"] for row in selected if row["user_id"]}),
        "scanned_dataset_rows": scanned,
        "eligible_train_rows": eligible,
        "selection": "minimum deterministic SHA-256 hashes, at most two reviews per product",
        "seed": cfg["seed"],
        "product_split": str(split_path),
        "product_split_sha256": sha256_file(split_path),
        "protected_test_used": False,
        "output": str(output),
        "output_sha256": sha256_file(output),
    }
    save_json(ROOT / "data" / "manifests" / "sample_manifest.json", manifest)
    return manifest
