#!/usr/bin/env python3
"""Build the compact dataset consumed by the human semantic-audit web app."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_AUDIT_CSV = (
    PROJECT_ROOT
    / "experiments/02_semantic_verification/human_semantic_audit.csv"
)
DEFAULT_PRODUCT_METADATA = Path(
    "/home/user/onsesang/texture_project/data/product_images.json"
)
DEFAULT_IMAGE_ROOT = Path("/home/user/onsesang/texture_project/images_train")
DEFAULT_OUTPUT = PROJECT_ROOT / "audit_app/data/items.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--audit-csv", type=Path, default=DEFAULT_AUDIT_CSV)
    parser.add_argument(
        "--product-metadata", type=Path, default=DEFAULT_PRODUCT_METADATA
    )
    parser.add_argument("--image-root", type=Path, default=DEFAULT_IMAGE_ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def load_product_metadata(path: Path, wanted_asins: set[str]) -> dict[str, dict]:
    products = json.loads(path.read_text(encoding="utf-8"))
    return {
        product["asin"]: product
        for product in products
        if isinstance(product, dict) and product.get("asin") in wanted_asins
    }


def main() -> None:
    args = parse_args()
    with args.audit_csv.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))

    wanted_asins = {row["asin"] for row in rows}
    products = load_product_metadata(args.product_metadata, wanted_asins)
    items = []
    for index, row in enumerate(rows):
        product = products.get(row["asin"], {})
        local_image = args.image_root / f"{row['asin']}.jpg"
        images = product.get("images") or []
        remote_image = next(
            (image.get("url", "") for image in images if image.get("variant") == "MAIN"),
            images[0].get("url", "") if images else "",
        )
        items.append(
            {
                "index": index,
                "span_id": row["span_id"],
                "review_id": row["review_id"],
                "asin": row["asin"],
                "product_title": product.get("title", ""),
                "review": row["review"],
                "quote": row["quote"],
                "qwen": {
                    "accepted": row["qwen_accepted"].lower() == "true",
                    "claim": row["qwen_claim"],
                    "scope": row["qwen_scope"],
                    "property_status": row["qwen_property_status"],
                    "intensity": row["qwen_intensity"],
                    "sentiment": row["qwen_sentiment"],
                    "evidence_basis": row["qwen_evidence_basis"],
                    "visual_observability": row["qwen_visual_observability"],
                    "rejection_reason": row["qwen_rejection_reason"],
                },
                "image": {
                    "local": local_image.is_file(),
                    "remote_url": remote_image,
                    "api_url": f"/api/image/{row['asin']}",
                },
            }
        )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "source_csv": str(args.audit_csv),
        "image_root": str(args.image_root),
        "item_count": len(items),
        "unique_products": len(wanted_asins),
        "local_image_count": sum(item["image"]["local"] for item in items),
        "items": items,
    }
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "output": str(args.output),
                "items": len(items),
                "unique_products": len(wanted_asins),
                "local_images": payload["local_image_count"],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
