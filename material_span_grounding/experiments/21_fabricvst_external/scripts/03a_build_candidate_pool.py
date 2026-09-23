#!/usr/bin/env python3
"""Select which reviews are sent to Qwen for FabricVST-taxonomy labelling.

The existing project already pre-filters reviews lexically before Qwen; that
filter was written for the old 14-class vocabulary, so it would systematically
miss evidence for FabricVST-only attributes such as fluffy, absorbent or holey.
This builds a FabricVST-oriented lexicon instead.

A review that matches nothing is treated as all-unknown, which is the same
supervision it would contribute if Qwen read it and found no evidence. The
filter is applied identically to train, development and test products, so it
cannot leak evaluation information.
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import ROOT, load_config  # noqa: E402

# Surface forms grouped by the FabricVST attribute they could bear on. Recall is
# deliberately favoured over precision: Qwen still makes the final judgement, and
# a term appearing here does not force a label.
LEXICON: dict[str, list[str]] = {
    "stiff": ["stiff", "rigid", "starchy", "boardy", "unyielding", "structured"],
    "soft": ["soft", "softer", "softest", "plush", "cushy", "velvety", "silky", "buttery", "cosy", "cozy", "gentle"],
    "rough": ["rough", "scratchy", "scratches", "itchy", "itch", "abrasive", "coarse", "prickly", "harsh"],
    "smooth": ["smooth", "sleek", "slick", "satiny", "glassy"],
    "thick": ["thick", "thicker", "heavyweight", "chunky", "dense", "substantial", "bulky"],
    "thin": ["thin", "thinner", "flimsy", "sheer", "lightweight", "see through", "see-through", "papery"],
    "cool": ["cool", "cooling", "breathable", "breathes", "airy", "chilly", "cold"],
    "warm": ["warm", "warmth", "toasty", "insulating", "insulated", "hot", "sweaty", "heat"],
    "fluffy": ["fluffy", "fuzzy", "furry", "downy", "lofty", "puffy"],
    "heavy": ["heavy", "weighty", "hefty", "lightweight", "light weight", "feather light"],
    "delicate": ["delicate", "fragile", "tore", "torn", "rip", "ripped", "snag", "snagged", "fell apart", "unravel"],
    "durable": ["durable", "sturdy", "tough", "rugged", "long lasting", "long-lasting", "holds up", "wears well"],
    "stretchable": ["stretch", "stretchy", "stretches", "elastic", "elasticity", "spandex", "give", "cling"],
    "absorbent": ["absorbent", "absorbs", "absorbed", "wicking", "wicks", "moisture", "sweat", "dries", "quick dry", "quick-dry"],
    "holey": ["holey", "hole", "holes", "mesh", "perforated", "open weave", "eyelet", "netting"],
    "flat": ["flat", "even surface", "smooth surface"],
    "bumpy": ["bumpy", "textured", "ribbed", "waffle", "nubby", "raised texture", "cable knit"],
    "patterned": ["pattern", "patterned", "print", "printed", "floral", "plaid", "checkered", "graphic"],
    "striped": ["stripe", "striped", "stripes", "pinstripe"],
    "shinny": ["shiny", "shine", "glossy", "lustrous", "sheen", "metallic", "sparkle"],
    "hairy": ["hairy", "fuzz", "lint", "pills", "pilling", "pilled", "shed", "shedding", "fibers", "fibres"],
    "embroidered": ["embroidered", "embroidery", "stitched design", "needlework"],
    "jacquard": ["jacquard", "brocade", "damask", "woven pattern"],
    "pigment printed": ["pigment print", "screen print", "screen-print", "printed on", "print peeled", "print cracked"],
}

GENERIC = [
    "fabric", "material", "cloth", "texture", "feel", "feels", "felt",
    "weave", "knit", "woven", "quality",
]


def build_pattern() -> re.Pattern:
    terms = {term for values in LEXICON.values() for term in values} | set(GENERIC)
    ordered = sorted(terms, key=len, reverse=True)
    escaped = [re.escape(term).replace(r"\ ", r"\s+") for term in ordered]
    return re.compile(r"(?<![a-z])(" + "|".join(escaped) + r")(?![a-z])", re.IGNORECASE)


def iter_jsonl(path: Path):
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                yield json.loads(line)


def main() -> int:
    config = load_config()
    pattern = build_pattern()
    reviews = list(iter_jsonl(Path(config["retraining"]["review_pool"])))

    selected, skipped = [], []
    hits = Counter()
    for row in reviews:
        text = str(row.get("text", ""))
        found = {match.group(0).lower() for match in pattern.finditer(text)}
        if found:
            hits.update(found)
            selected.append(row["review_id"])
        else:
            skipped.append(row["review_id"])

    products_selected = {row["asin"] for row in reviews if row["review_id"] in set(selected)}
    summary = {
        "total_reviews": len(reviews),
        "selected": len(selected),
        "skipped": len(skipped),
        "selected_fraction": round(len(selected) / len(reviews), 4),
        "products_with_at_least_one_selected_review": len(products_selected),
        "lexicon_terms": sum(len(v) for v in LEXICON.values()) + len(GENERIC),
        "top_terms": hits.most_common(25),
    }
    (ROOT / "artifacts" / "qwen_candidate_pool.json").write_text(
        json.dumps({"summary": summary, "selected_review_ids": selected, "skipped_review_ids": skipped}, indent=2) + "\n"
    )
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
