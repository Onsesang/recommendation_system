from __future__ import annotations

import hashlib
import heapq
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from .common import PATHS, load_experiment, sha256_file, sha256_text, utc_now, write_json, write_jsonl


CATEGORY_RULES = [
    ("dress", ("dress", "gown")),
    ("top", ("shirt", "tee", "top", "blouse", "tank")),
    ("sweater", ("sweater", "cardigan", "pullover", "hoodie", "sweatshirt")),
    ("pants", ("pants", "legging", "jean", "trouser", "jogger")),
    ("skirt", ("skirt",)),
    ("outerwear", ("jacket", "coat", "vest")),
    ("sleepwear", ("pajama", "sleepwear", "robe", "nightgown")),
    ("underwear", ("bra", "underwear", "lingerie", "sock")),
    ("swimwear", ("swim", "bikini", "tankini")),
    ("accessory", ("scarf", "hat", "cap", "beanie", "mask", "belt")),
]

# These expressions are deliberately high recall. Qwen performs the semantic
# accept/reject and taxonomy mapping in Phase 2. Boundary checks keep obvious
# substring accidents (for example "stretch" in an identifier) out.
AXIS_PATTERNS = {
    "softness": re.compile(r"\b(?:soft(?:ness|er|est)?|plush|tender|firm(?:ness|er|est)?|hard\s+(?:fabric|material|texture|feel|hand))\b", re.I),
    "surface_texture": re.compile(r"\b(?:smooth(?:ness|er|est)?|silky|slick|rough(?:ness|er|est)?|scratchy|coarse|itchy)\b", re.I),
    "elasticity": re.compile(r"\b(?:stretch(?:y|ier|iest|able|es|ed|ing)?|elastic(?:ity)?|no\s+stretch|not\s+stretchy|inelastic)\b", re.I),
    "thickness": re.compile(r"\b(?:thin(?:ness|ner|nest)?|thick(?:ness|er|est)?)\b", re.I),
    "flexibility": re.compile(r"\b(?:flexib(?:le|ility)|floppy|bendable|drap(?:e|ey|es|ed|ing)|flowy|stiff(?:ness|er|est)?|rigid(?:ity)?)\b", re.I),
    "warmth": re.compile(r"\b(?:warm(?:th|er|est)?|thermal|insulat(?:e|ed|ing|ion)|cool(?:ing|er|est|ness)?)\b", re.I),
    "sponginess": re.compile(r"\b(?:spongy|squishy|cushion(?:y|ed)?|crisp(?:ness|er|est)?)\b", re.I),
}


def _category(title: str) -> str:
    text = (title or "").casefold()
    for category, words in CATEGORY_RULES:
        if any(word in text for word in words):
            return category
    return "other"


def _plain(value: Any) -> Any:
    return value.item() if hasattr(value, "item") else value


def _local_context(text: str, start: int, end: int) -> str:
    left = max(text.rfind(".", 0, start), text.rfind("!", 0, start), text.rfind("?", 0, start), text.rfind(";", 0, start))
    rights = [pos for pos in (text.find(".", end), text.find("!", end), text.find("?", end), text.find(";", end)) if pos >= 0]
    right = min(rights) + 1 if rights else len(text)
    clause = text[left + 1:right].strip()
    if len(clause) > 420:
        clause = text[max(0, start - 170):min(len(text), end + 170)].strip()
    return clause


def _lexical_candidates(reviews: list[dict[str, Any]], per_product_axis: int) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[tuple[str, dict[str, Any]]]] = defaultdict(list)
    for review in reviews:
        text = str(review["text"])
        for axis_id, pattern in AXIS_PATTERNS.items():
            match = pattern.search(text)
            if match is None:
                continue
            quote = _local_context(text, match.start(), match.end())
            fingerprint = sha256_text(f"{review['review_id']}\x1f{axis_id}\x1f{quote}")[:24]
            row = {
                "span_id": f"v2lex-{fingerprint}",
                "review_id": review["review_id"],
                "asin": review["asin"],
                "user_id": review["user_id"],
                "quote": quote,
                "claim": quote,
                "review_text": text,
                "scope": "unknown",
                "intensity": "unknown",
                "property_status": "lexical_candidate",
                "accepted": True,
                "candidate_axis_hint": axis_id,
                "candidate_match": match.group(0),
                "candidate_source": "high_recall_lexical_v2",
            }
            grouped[(str(review["asin"]), axis_id)].append((str(review["selection_hash"]), row))
    selected: list[dict[str, Any]] = []
    for key in sorted(grouped):
        values = sorted(grouped[key], key=lambda item: (item[0], item[1]["span_id"]))
        selected.extend(row for _, row in values[:per_product_axis])
    selected.sort(key=lambda row: (row["asin"], row["candidate_axis_hint"], row["span_id"]))
    return selected


def _representative_grounding_pool(candidates: list[dict[str, Any]], second_reviewer_products_per_axis: int) -> list[dict[str, Any]]:
    """Keep every candidate on disk but send a reviewer-first representative pool to Qwen.

    Each product contributes one deterministically selected candidate axis. When
    another independent reviewer mentions the same axis, that second row is
    retained so reviewer agreement remains measurable without making inference
    grow with every keyword hit.
    """
    by_product_axis: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    for row in candidates:
        by_product_axis[str(row["asin"])][str(row["candidate_axis_hint"])].append(row)
    selected = []
    paired_candidates: dict[str, list[tuple[str, list[dict[str, Any]]]]] = defaultdict(list)
    for asin, axes in sorted(by_product_axis.items()):
        chosen_axis = min(axes, key=lambda axis: (sha256_text(f"grounding-axis\x1f{asin}\x1f{axis}"), axis))
        values = axes[chosen_axis]
        selected.append(values[0])
        if len(values) >= 2:
            paired_candidates[chosen_axis].append((asin, values))
    for axis, values in sorted(paired_candidates.items()):
        ordered = sorted(values, key=lambda item: (sha256_text(f"second-reviewer\x1f{axis}\x1f{item[0]}"), item[0]))
        selected.extend(rows[1] for _, rows in ordered[:second_reviewer_products_per_axis])
    selected.sort(key=lambda row: (row["asin"], row["candidate_axis_hint"], row["span_id"]))
    return selected


def _build_splits(products: list[dict[str, Any]], previous_families: set[str], seed: int, ratios: dict[str, float]) -> dict[str, Any]:
    by_family: dict[str, list[str]] = defaultdict(list)
    family_categories: dict[str, Counter[str]] = defaultdict(Counter)
    for product in products:
        family = str(product["product_family_id"])
        by_family[family].append(str(product["product_id"]))
        family_categories[family][str(product["category"])] += 1
    splits = {"train": [], "development": [], "test": []}
    split_families = {"train": [], "development": [], "test": []}
    new_by_category: dict[str, list[str]] = defaultdict(list)
    for family in sorted(by_family):
        if family in previous_families:
            split_families["train"].append(family)
        else:
            category = sorted(family_categories[family].items(), key=lambda item: (-item[1], item[0]))[0][0]
            new_by_category[category].append(family)
    for category, families in sorted(new_by_category.items()):
        ordered = sorted(families, key=lambda family: (sha256_text(f"{seed}\x1f{category}\x1f{family}"), family))
        count = len(ordered)
        development_count = max(1, round(count * float(ratios["development"]))) if count >= 3 else 0
        test_count = max(1, round(count * float(ratios["test"]))) if count >= 3 else 0
        train_count = count - development_count - test_count
        split_families["train"].extend(ordered[:train_count])
        split_families["development"].extend(ordered[train_count:train_count + development_count])
        split_families["test"].extend(ordered[train_count + development_count:])
    for split, families in split_families.items():
        families.sort()
        splits[split] = sorted(product for family in families for product in by_family[family])
    all_families = sum(split_families.values(), [])
    if len(all_families) != len(set(all_families)) or set(all_families) != set(by_family):
        raise RuntimeError("Family leakage or missing family in v2 split")
    return {
        "seed": seed,
        "unit": "parent_product_family",
        "prediction_unit": "asin",
        "splits": splits,
        "families": split_families,
        "counts": {key: len(value) for key, value in splits.items()},
        "family_counts": {key: len(value) for key, value in split_families.items()},
        "previous_v1_family_count": len(set(split_families["train"]) & previous_families),
        "previous_v1_families_forced_train": True,
        "clean_development_and_test": True,
        "locked_final_test": True,
    }


def build_full_pool() -> dict[str, Any]:
    config = load_experiment()
    pool = config["full_pool"]
    source_products = json.loads(Path(config["inputs"]["source_product_split"]).read_text(encoding="utf-8"))
    metadata = {str(row["asin"]): row for row in source_products}
    image_root = Path(config["inputs"]["image_root"])
    image_asins = {path.stem for path in image_root.glob("*.jpg")}
    eligible_asins = set(metadata) & image_asins

    from datasets import load_from_disk

    dataset = load_from_disk(config["inputs"]["source_review_dataset"])["full"]
    columns = dataset.select_columns(["asin", "user_id", "text", "rating", "timestamp", "verified_purchase"])
    per_product_user: dict[str, dict[str, tuple[int, dict[str, Any]]]] = defaultdict(dict)
    eligible_review_counts: Counter[str] = Counter()
    scanned = eligible = 0
    min_chars, max_chars = int(pool["min_review_chars"]), int(pool["max_review_chars"])
    seed = int(config["experiment"]["seed"])
    for batch_number, batch in enumerate(columns.to_pandas(batched=True, batch_size=200_000), 1):
        for asin, user_id, text, rating, timestamp, verified in zip(
            batch["asin"], batch["user_id"], batch["text"], batch["rating"], batch["timestamp"], batch["verified_purchase"]
        ):
            scanned += 1
            asin = str(asin)
            if asin not in eligible_asins or text is None:
                continue
            text = str(text).strip()
            if not min_chars <= len(text) <= max_chars:
                continue
            eligible += 1
            eligible_review_counts[asin] += 1
            user = "" if user_id is None else str(user_id).strip()
            stamp = "" if timestamp is None else str(_plain(timestamp))
            review_key = f"{asin}\x1f{user}\x1f{stamp}\x1f{text}"
            review_id = sha256_text(review_key)[:20]
            user_key = user or f"missing:{review_id}"
            score = int(sha256_text(f"{seed}\x1f{review_key}")[:16], 16)
            row = {
                "review_id": review_id, "asin": asin, "user_id": user,
                "rating": _plain(rating), "timestamp": _plain(timestamp),
                "verified_purchase": bool(verified) if verified is not None else None,
                "text": text, "text_chars": len(text), "selection_hash": f"{score:016x}",
            }
            previous = per_product_user[asin].get(user_key)
            if previous is None or score < previous[0]:
                per_product_user[asin][user_key] = (score, row)
        print(f"[v2 full pool] batch={batch_number} scanned={scanned:,} eligible={eligible:,}", flush=True)

    min_users = int(pool["min_unique_reviewers"])
    selected_asins = sorted(asin for asin, users in per_product_user.items() if len(users) >= min_users)
    # Deliberately no max_products slice: this is the scientific change from v1.
    reviews: list[dict[str, Any]] = []
    review_counts: Counter[int] = Counter()
    for asin in selected_asins:
        candidates = [entry[1] for entry in per_product_user[asin].values()]
        chosen = heapq.nsmallest(int(pool["max_reviews_per_product"]), candidates, key=lambda row: (row["selection_hash"], row["review_id"]))
        reviews.extend(chosen)
        review_counts[len(chosen)] += 1
    reviews.sort(key=lambda row: (row["asin"], row["selection_hash"], row["review_id"]))

    products = []
    for asin in selected_asins:
        row = metadata[asin]
        parent = str(row.get("parent_asin") or asin)
        products.append({
            "product_id": asin, "product_family_id": parent, "parent_asin": parent,
            "alias_product_ids": [asin], "title": str(row.get("title") or ""),
            "category": _category(str(row.get("title") or "")),
            "image_filename": f"{asin}.jpg", "image_path": str(image_root / f"{asin}.jpg"),
            "eligible_unique_reviewers": len(per_product_user[asin]),
            "selected_reviewers": min(len(per_product_user[asin]), int(pool["max_reviews_per_product"])),
        })

    prior_asins = {json.loads(line)["asin"] for line in Path(config["inputs"]["previous_v1_reviews"]).read_text(encoding="utf-8").splitlines() if line.strip()}
    previous_families = {str(metadata[asin].get("parent_asin") or asin) for asin in prior_asins if asin in metadata}
    split = _build_splits(products, previous_families, seed, config["experiment"]["ratios"])
    split_path = PATHS.manifests / f"family_split_{seed}.json"
    write_json(split_path, split)
    all_candidates = _lexical_candidates(reviews, int(pool["candidate_limit_per_product_axis"]))
    candidates = _representative_grounding_pool(all_candidates, int(pool["second_reviewer_products_per_axis"]))

    reviews_path = PATHS.data / "reviews_full_pool.jsonl"
    product_path = PATHS.data / "product_master_full_pool.json"
    candidate_path = PATHS.data / "lexical_tactile_candidates.jsonl"
    all_candidate_path = PATHS.data / "lexical_tactile_candidates_all.jsonl"
    write_jsonl(reviews_path, reviews)
    write_json(product_path, products)
    write_jsonl(candidate_path, candidates)
    write_jsonl(all_candidate_path, all_candidates)
    candidate_axes = Counter(row["candidate_axis_hint"] for row in candidates)
    manifest = {
        "status": "complete", "phase": 0, "generated_at": utc_now(),
        "selection": {
            "min_unique_reviewers": min_users,
            "max_reviews_per_product": int(pool["max_reviews_per_product"]),
            "max_products": None,
            "all_eligible_products_included": True,
            "one_review_per_user": True,
            "image_required": True,
            "review_char_range": [min_chars, max_chars],
        },
        "source": {
            "scanned_dataset_rows": scanned, "eligible_train_reviews_with_image": eligible,
            "train_products": len(metadata), "train_products_with_local_image": len(eligible_asins),
            "products_with_eligible_reviews": len(per_product_user),
            "products_meeting_min_reviewers": len(selected_asins),
        },
        "outputs_summary": {
            "products": len(products), "parent_families": len({row["product_family_id"] for row in products}),
            "selected_reviews": len(reviews), "reviews_per_product": dict(sorted(review_counts.items())),
            "lexical_candidates_all": len(all_candidates),
            "lexical_candidates": len(candidates), "candidate_axis_distribution": dict(candidate_axes),
            "candidate_products": len({row["asin"] for row in candidates}),
            "second_reviewer_products_per_axis_cap": int(pool["second_reviewer_products_per_axis"]),
        },
        "split": split, "human_validation": "skipped_by_user_pending",
        "candidate_method": "all reviews scanned by high-recall lexical clauses; Qwen grounds one deterministic axis per candidate product plus a deterministic sample of up to 100 second reviewers per axis",
        "outputs": {
            "reviews": str(reviews_path), "reviews_sha256": sha256_file(reviews_path),
            "product_master": str(product_path), "product_master_sha256": sha256_file(product_path),
            "candidates": str(candidate_path), "candidates_sha256": sha256_file(candidate_path),
            "all_candidates": str(all_candidate_path), "all_candidates_sha256": sha256_file(all_candidate_path),
            "split": str(split_path), "split_sha256": sha256_file(split_path),
        },
    }
    write_json(PATHS.manifests / "phase0_full_pool.json", manifest)
    write_json(PATHS.manifests / "phase0_protocol.json", manifest)
    (PATHS.reports / "phase0_protocol.md").write_text(
        "# Phase 0 — Full-pool protocol\n\n"
        f"- 전체 적격 ASIN: {len(products):,} (500개 상한 없음)\n"
        f"- parent product family: {manifest['outputs_summary']['parent_families']:,}\n"
        f"- 선택 리뷰: {len(reviews):,}\n- 전체 촉감 후보 구절: {len(all_candidates):,}\n- Qwen 대표 grounding pool: {len(candidates):,}\n"
        "- 기존 v1에 등장한 family는 train에만 배치\n"
        "- development/test는 기존 v1에서 보지 않은 family로만 구성하고 test는 잠금\n"
        "- 사람 검증은 사용자 요청으로 건너뛰었으며 pending 상태로 유지\n",
        encoding="utf-8",
    )
    return manifest
