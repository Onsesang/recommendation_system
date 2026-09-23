#!/usr/bin/env python3
"""Apply a transparent Codex AI adjudication to both 100-span audit sets.

This is not an independent human audit. Every stored annotation and missing span
is explicitly marked as AI adjudication so it cannot be mistaken for human gold.
"""

from __future__ import annotations

import argparse
import json
import urllib.error
import urllib.request
from collections import defaultdict
from typing import Any


ANNOTATOR = "codex_ai_adjudicator_not_human"
COMMENT = (
    "Codex AI adjudication; not independent human annotation. "
    "Reviewed against semantic_verification_v1.1."
)
BASES = {
    "a": "http://100.96.162.32:8765",
    "b": "http://100.96.162.32:8766",
}


def accepted(
    claim: str,
    scope: str,
    property_status: str,
    visual_observability: str,
) -> dict[str, Any]:
    return {
        "human_accepted": True,
        "human_claim": claim,
        "human_scope": scope,
        "human_property_status": property_status,
        "human_visual_observability": visual_observability,
    }


def rejected() -> dict[str, Any]:
    return {
        "human_accepted": False,
        "human_claim": "",
        "human_scope": "",
        "human_property_status": "",
        "human_visual_observability": "",
    }


# Only disagreements or metadata/claim corrections are listed. Every other span
# was individually reviewed and retains the Qwen decision/structured fields.
OVERRIDES: dict[str, dict[str, Any]] = {
    # Annotator A: false positives.
    "623ec0005f4790aba578": rejected(),  # vague whole-product flimsiness
    "f228cdb5dca7d39d49e6": rejected(),  # sleeve length is fit/sizing
    "1c6a3512e65d89125319": rejected(),  # liking fabric feel states no property
    # Annotator A: false negatives.
    "211eadf9f09d26609c6c": accepted(
        "The integrated shirt graphic is not expected to peel",
        "outer_surface",
        "absent",
        "high",
    ),
    "e6e07aa839c680b874c6": accepted(
        "The sweatshirt appears to have shrunk after washing",
        "whole_garment",
        "uncertain",
        "low",
    ),
    # Annotator A: metadata/claim corrections.
    "b3421511cfef92ab91c3": accepted(
        "The garment did not shrink during washing or drying",
        "main_fabric",
        "absent",
        "low",
    ),
    "64868d6ac541bba6508b": accepted(
        "The reviewer is concerned that the sweatshirt may pill sooner rather than later",
        "main_fabric",
        "uncertain",
        "low",
    ),
    "0dabc9a1aed5d0477cbc": accepted(
        "Two pairs developed holes in various places",
        "whole_garment",
        "present",
        "high",
    ),
    # Annotator B: false positives.
    "842868b2dd38ff0e314f": rejected(),  # nice feel is explicitly vague
    "edc420460a61fc5f17de": rejected(),  # color shade, not material evidence
    "9dd574a69eb3bfd5354e": rejected(),  # dress adjustment/fit, claim overreaches
    "dfb7e85f969e293c0a3f": rejected(),  # "messed up" is vague; snag is separate
    "2aefcf834653bc2a7d68": rejected(),  # metaphor, not a self-contained property
    "830fbf2704c3453ec121": rejected(),  # skin-to-skin contact caused by fit/slippage
    "4011477d2663f1d0c6e6": rejected(),  # thigh-on-thigh friction, not fabric friction
    "a18bf818746179220916": rejected(),  # creeping down is fit/slippage
    "0d85bc376340534a5ffd": rejected(),  # cozy is explicitly vague
    # Annotator B: false negatives.
    "8fe2b7a12b38ef3b2125": accepted(
        "The garment arrived with a hole in the side",
        "whole_garment",
        "present",
        "high",
    ),
    "79adda79c0f268d2f355": accepted(
        "The stitching came undone before the first wear",
        "component",
        "present",
        "high",
    ),
    "047efa2b64c2852e49cf": accepted(
        "The vinegar odor disappeared after washing",
        "whole_garment",
        "absent",
        "low",
    ),
    "583f47a53019dab4eb26": accepted(
        "The pants remained in new condition after a year",
        "whole_garment",
        "present",
        "low",
    ),
    # Annotator B: metadata/claim corrections.
    "b5ff936a6ffe6b848baf": accepted(
        "The white version would likely show through",
        "main_fabric",
        "uncertain",
        "high",
    ),
    "be01ae01ee9a13dc380b": accepted(
        "The garment has a strong vinegar odor when first opened",
        "whole_garment",
        "present",
        "low",
    ),
    "f8d24c89c8ca6f93b033": accepted(
        "The garment did not shrink at all after washing",
        "main_fabric",
        "absent",
        "low",
    ),
    "d2d8cc0703b6aea3b737": accepted(
        "The leggings feel warm",
        "whole_garment",
        "present",
        "low",
    ),
    "c0b222b1b22eeb785ebd": accepted(
        "The material is rough",
        "main_fabric",
        "present",
        "low",
    ),
}


def missing(
    assignment: str,
    review_id: str,
    quote: str,
    claim: str,
    scope: str,
    property_status: str,
    intensity: str,
    sentiment: str,
    evidence_basis: str,
    visual_observability: str,
) -> dict[str, str]:
    return {
        "assignment": assignment,
        "review_id": review_id,
        "quote": quote,
        "claim": claim,
        "scope": scope,
        "property_status": property_status,
        "intensity": intensity,
        "sentiment": sentiment,
        "evidence_basis": evidence_basis,
        "visual_observability": visual_observability,
    }


MISSING = [
    missing("a", "367f2135c76d82bbd63c", "keeps me warm.", "The scarf keeps the wearer warm", "whole_garment", "present", "none", "positive", "worn_experience", "low"),
    missing("a", "5c4779cd692fdbeee32a", "Compact, light.", "The garment is light", "whole_garment", "present", "none", "positive", "unspecified", "medium"),
    missing("a", "743be48cd2417efbc5a5", "this lightweight scarf", "The scarf is lightweight", "whole_garment", "present", "none", "positive", "unspecified", "medium"),
    missing("a", "743be48cd2417efbc5a5", "sheer", "The fabric is sheer", "main_fabric", "present", "none", "neutral", "visual_only", "high"),
    missing("a", "743be48cd2417efbc5a5", "raw, unfinsihed edges", "The lace trim has raw, unfinished edges", "component", "present", "none", "negative", "visual_only", "high"),
    missing("a", "0640265beccef2458e45", "the sleeves are flowy", "The sleeves have a flowy drape", "component", "present", "none", "positive", "visual_only", "medium"),
    missing("a", "6af087c6a0d18087db1d", "durable material", "The material is durable", "main_fabric", "present", "none", "positive", "unspecified", "low"),
    missing("a", "1938381659185203deac", "without lined", "The skirt has no lining", "lining", "absent", "none", "neutral", "visual_only", "high"),
    missing("a", "1ce543158028377ea990", "is soft against the skin", "The fabric is soft against the skin", "main_fabric", "present", "none", "positive", "direct_touch", "low"),
    missing("a", "52a5ab965746c194b2dd", "Regular crew neck is stretchy enough", "The crew neck has sufficient stretch", "component", "present", "none", "positive", "product_behavior", "low"),
    missing("a", "3c9297fd3833479a469b", "Kept me warm enough in 60 de.g beach weather.", "The garment was warm enough in 60-degree beach weather", "whole_garment", "present", "none", "positive", "worn_experience", "low"),
    missing("a", "3c9297fd3833479a469b", "Might be a bit thin for any weather for under 60 deg", "The garment may be a bit thin below 60 degrees", "main_fabric", "uncertain", "slight", "negative", "worn_experience", "medium"),
    missing("a", "79c598c28329c33db8a2", "single layer of fabric that probably wouldn't keep your hands warm", "The single-layer pocket fabric probably would not keep hands warm", "component", "uncertain", "none", "negative", "worn_experience", "low"),
    missing("a", "584995e27d259a1b8adf", "handwash only", "The socks are hand-wash only", "whole_garment", "present", "none", "negative", "product_behavior", "low"),
    missing("a", "77456c353b61997e2246", "soft", "The socks are described as soft", "main_fabric", "present", "none", "positive", "unspecified", "low"),
    missing("a", "75466a6be648c606d875", "great compression", "The leggings provide compression", "main_fabric", "present", "none", "positive", "worn_experience", "low"),
    missing("a", "28355f51b573084198ef", "They have a little bit of compression to them", "The tanks have a little compression", "main_fabric", "present", "slight", "positive", "worn_experience", "low"),
    missing("b", "c911980ed3305001f84e", "just a teeny bit floppy", "The hats are a little floppy", "whole_garment", "present", "slight", "positive", "visual_only", "medium"),
    missing("b", "9be0068dae19289fff21", "one raw edge beneath the neck facing", "The garment has one raw edge beneath the neck facing", "component", "present", "none", "negative", "visual_only", "high"),
    missing("b", "bb903bd322dea632c706", "very durable", "The garment is described as very durable", "whole_garment", "present", "strong", "positive", "product_behavior", "low"),
    missing("b", "8a9acd6ab19a40c9a4a0", "soft", "The garment is described as soft", "main_fabric", "present", "none", "positive", "unspecified", "low"),
    missing("b", "8a9acd6ab19a40c9a4a0", "warm", "The garment is described as warm", "whole_garment", "present", "none", "positive", "worn_experience", "low"),
    missing("b", "941810b007341cd228aa", "they’re a tad bit see-through", "The garment is a little see-through", "main_fabric", "present", "slight", "negative", "visual_only", "high"),
    missing("b", "b5d7a5f76ead86602b1f", "Thin", "The garment is thin", "main_fabric", "present", "none", "negative", "unspecified", "medium"),
]


def request_json(url: str, method: str = "GET", payload: dict | None = None) -> dict:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={"Content-Type": "application/json", "User-Agent": "codex-ai-audit/1.0"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {url} failed: HTTP {error.code}: {detail}") from error


def build_annotation(item: dict) -> dict:
    qwen = item["qwen"]
    decision = OVERRIDES.get(item["span_id"])
    if decision is None:
        decision = (
            accepted(qwen["claim"], qwen["scope"], qwen["property_status"], qwen["visual_observability"])
            if qwen["accepted"]
            else rejected()
        )
    changed = (
        decision["human_accepted"] != qwen["accepted"]
        or (
            decision["human_accepted"]
            and any(
                decision[human] != qwen[qwen_key]
                for human, qwen_key in (
                    ("human_claim", "claim"),
                    ("human_scope", "scope"),
                    ("human_property_status", "property_status"),
                    ("human_visual_observability", "visual_observability"),
                )
            )
        )
    )
    action = "edit" if changed and decision["human_accepted"] else "good" if decision["human_accepted"] else "bad"
    return {"action": action, **decision, "annotator_id": ANNOTATOR, "comment": COMMENT}


def validate(assignments: dict[str, dict]) -> dict[str, Any]:
    all_items = [item for snapshot in assignments.values() for item in snapshot["items"]]
    item_by_span = {item["span_id"]: item for item in all_items}
    if set(OVERRIDES) - set(item_by_span):
        raise RuntimeError(f"Unknown override span IDs: {sorted(set(OVERRIDES) - set(item_by_span))}")
    by_assignment_review: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for assignment, snapshot in assignments.items():
        for item in snapshot["items"]:
            by_assignment_review[(assignment, item["review_id"])].append(item)
    existing_quotes = {(item["review_id"], item["quote"]) for item in all_items}
    for row in MISSING:
        key = (row["assignment"], row["review_id"])
        if key not in by_assignment_review:
            raise RuntimeError(f"Unknown missing-span review: {key}")
        review = by_assignment_review[key][0]["review"]
        if row["quote"] not in review:
            raise RuntimeError(f"Missing quote is not exact for {key}: {row['quote']!r}")
        if (row["review_id"], row["quote"]) in existing_quotes:
            raise RuntimeError(f"Missing quote already extracted: {key}: {row['quote']!r}")
    decisions = {item["span_id"]: build_annotation(item) for item in all_items}
    return {
        "items": len(all_items),
        "qwen_accepted": sum(item["qwen"]["accepted"] for item in all_items),
        "codex_accepted": sum(row["human_accepted"] for row in decisions.values()),
        "decision_changes": sum(
            decisions[item["span_id"]]["human_accepted"] != item["qwen"]["accepted"]
            for item in all_items
        ),
        "structured_edits": sum(row["action"] == "edit" for row in decisions.values()),
        "missing_spans": len(MISSING),
        "reviews": len({item["review_id"] for item in all_items}),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    assignments = {label: request_json(f"{base}/api/items") for label, base in BASES.items()}
    for label, snapshot in assignments.items():
        if snapshot["annotations"] or snapshot["missing_spans"] or snapshot["review_checks"]:
            raise RuntimeError(f"Assignment {label} already has saved work; refusing to overwrite")
    summary = validate(assignments)
    if not args.apply:
        print(json.dumps({"status": "validated_dry_run", **summary}, ensure_ascii=False, indent=2))
        return

    for label, snapshot in assignments.items():
        base = BASES[label]
        for item in snapshot["items"]:
            request_json(
                f"{base}/api/annotations/{item['span_id']}",
                "POST",
                build_annotation(item),
            )
    for row in MISSING:
        snapshot = assignments[row["assignment"]]
        source = next(item for item in snapshot["items"] if item["review_id"] == row["review_id"])
        payload = {
            "source_span_id": source["span_id"],
            **{key: value for key, value in row.items() if key not in {"assignment", "review_id"}},
            "annotator_id": ANNOTATOR,
            "comment": COMMENT,
        }
        request_json(f"{BASES[row['assignment']]}/api/missing-spans", "POST", payload)
    for label, snapshot in assignments.items():
        base = BASES[label]
        for review_id in sorted({item["review_id"] for item in snapshot["items"]}):
            request_json(
                f"{base}/api/review-checks/{review_id}",
                "POST",
                {"annotator_id": ANNOTATOR},
            )
    final = {label: request_json(f"{base}/api/health") for label, base in BASES.items()}
    print(json.dumps({"status": "complete", **summary, "servers": final}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

