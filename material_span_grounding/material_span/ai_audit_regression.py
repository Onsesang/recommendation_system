from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .common import read_jsonl, save_json, write_jsonl


ANNOTATOR = "codex_ai_adjudicator_not_human"


def _bool(value: object) -> bool:
    normalized = str(value).strip().lower()
    if normalized not in {"true", "false"}:
        raise ValueError(f"Invalid boolean value: {value!r}")
    return normalized == "true"


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def build_fixture(
    audit_csv: Path,
    missing_csv: Path,
    dense_input: Path,
    fixture_path: Path,
    regression_input_path: Path,
) -> dict[str, Any]:
    audit_rows = _read_csv(audit_csv)
    missing_rows = _read_csv(missing_csv)
    if len(audit_rows) != 200 or len(missing_rows) != 24:
        raise ValueError("Expected the complete 200-candidate/24-missing Codex audit")
    if {
        row.get("annotator_id", "").strip() for row in audit_rows + missing_rows
    } != {ANNOTATOR}:
        raise ValueError("Fixture may only be built from explicitly marked Codex AI rows")

    candidate_cases = []
    for row in audit_rows:
        expected_accepted = _bool(row["human_accepted"])
        candidate_cases.append(
            {
                "span_id": row["span_id"],
                "review_id": row["review_id"],
                "quote": row["quote"],
                "qwen_v2_0_accepted": _bool(row["qwen_accepted"]),
                "expected_accepted": expected_accepted,
                "expected_claim": row["human_claim"] if expected_accepted else "",
                "expected_scope": row["human_scope"] if expected_accepted else "",
                "expected_property_status": (
                    row["human_property_status"] if expected_accepted else ""
                ),
                "expected_visual_observability": (
                    row["human_visual_observability"] if expected_accepted else ""
                ),
            }
        )

    missing_cases = [
        {
            "missing_span_id": row["missing_span_id"],
            "review_id": row["review_id"],
            "quote": row["quote"],
            "expected_accepted": True,
            "expected_claim": row["claim"],
            "expected_scope": row["scope"],
            "expected_property_status": row["property_status"],
            "expected_intensity": row["intensity"],
            "expected_sentiment": row["sentiment"],
            "expected_evidence_basis": row["evidence_basis"],
            "expected_visual_observability": row["visual_observability"],
        }
        for row in missing_rows
    ]
    changed = [
        row["span_id"]
        for row in candidate_cases
        if row["qwen_v2_0_accepted"] != row["expected_accepted"]
    ]
    if len(changed) != 18:
        raise ValueError(f"Expected 18 changed decisions, found {len(changed)}")

    review_ids = {row["review_id"] for row in candidate_cases}
    dense_rows = read_jsonl(dense_input)
    regression_rows = [row for row in dense_rows if row["review_id"] in review_ids]
    if len(regression_rows) != 68 or {row["review_id"] for row in regression_rows} != review_ids:
        raise ValueError("Could not resolve all 68 audited reviews in dense input")
    write_jsonl(regression_input_path, regression_rows)

    fixture = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "label_source": ANNOTATOR,
        "is_independent_human_gold": False,
        "usage": "Prompt-development regression only; not an unbiased evaluation set.",
        "candidate_cases": sorted(
            candidate_cases, key=lambda row: (row["review_id"], row["span_id"])
        ),
        "missing_extraction_cases": sorted(
            missing_cases,
            key=lambda row: (row["review_id"], row["missing_span_id"]),
        ),
        "changed_decision_span_ids": sorted(changed),
        "review_ids": sorted(review_ids),
    }
    save_json(fixture_path, fixture)
    return fixture


def _capture(expected: str, extracted: list[str]) -> tuple[bool, bool, str | None]:
    if expected in extracted:
        return True, True, expected
    covering = [
        quote for quote in extracted if expected in quote or quote in expected
    ]
    if not covering:
        return False, False, None
    best = min(covering, key=lambda quote: (abs(len(quote) - len(expected)), len(quote)))
    return False, True, best


def evaluate_fixture(
    fixture: dict[str, Any],
    extraction_path: Path,
    verification_path: Path,
) -> dict[str, Any]:
    extracted_rows = read_jsonl(extraction_path)
    verified_rows = read_jsonl(verification_path)
    quotes_by_review = {
        row["review_id"]: [item["quote"] for item in row.get("evidence", [])]
        for row in extracted_rows
    }
    verified_by_key = {
        (row["review_id"], row["quote"]): row
        for row in verified_rows
        if row.get("status") == "success"
    }

    extraction_results = []
    for case in fixture["missing_extraction_cases"]:
        exact, covered, matched_quote = _capture(
            case["quote"], quotes_by_review.get(case["review_id"], [])
        )
        verification = (
            verified_by_key.get((case["review_id"], matched_quote))
            if matched_quote is not None
            else None
        )
        extraction_results.append(
            {
                **case,
                "exact_extracted": exact,
                "containment_covered": covered,
                "matched_quote": matched_quote,
                "matched_verification_accepted": (
                    verification.get("accepted") if verification else None
                ),
            }
        )

    candidate_results = []
    for case in fixture["candidate_cases"]:
        verification = verified_by_key.get((case["review_id"], case["quote"]))
        candidate_results.append(
            {
                **case,
                "candidate_present": verification is not None,
                "actual_accepted": (
                    verification.get("accepted") if verification else None
                ),
                "decision_match": (
                    verification.get("accepted") == case["expected_accepted"]
                    if verification
                    else None
                ),
            }
        )

    expected_positive = [
        case for case in fixture["candidate_cases"] if case["expected_accepted"]
    ] + fixture["missing_extraction_cases"]
    positive_coverage = []
    for case in expected_positive:
        exact, covered, matched = _capture(
            case["quote"], quotes_by_review.get(case["review_id"], [])
        )
        positive_coverage.append(
            {**case, "exact_extracted": exact, "containment_covered": covered, "matched_quote": matched}
        )

    available = [row for row in candidate_results if row["candidate_present"]]
    changed_ids = set(fixture["changed_decision_span_ids"])
    changed_results = [row for row in candidate_results if row["span_id"] in changed_ids]
    metrics = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "label_source": fixture["label_source"],
        "is_independent_human_gold": False,
        "scope": {
            "reviews": len(extracted_rows),
            "extracted_spans": sum(
                len(row.get("evidence", [])) for row in extracted_rows
            ),
            "verified_spans": len(verified_rows),
        },
        "missing_span_regression": {
            "total": len(extraction_results),
            "exact_extracted": sum(row["exact_extracted"] for row in extraction_results),
            "containment_covered": sum(
                row["containment_covered"] for row in extraction_results
            ),
            "covered_and_accepted": sum(
                row["containment_covered"]
                and row["matched_verification_accepted"] is True
                for row in extraction_results
            ),
            "cases": extraction_results,
        },
        "all_codex_positive_extraction": {
            "total": len(positive_coverage),
            "exact_extracted": sum(row["exact_extracted"] for row in positive_coverage),
            "containment_covered": sum(
                row["containment_covered"] for row in positive_coverage
            ),
            "cases": positive_coverage,
        },
        "candidate_decision_regression": {
            "total": len(candidate_results),
            "available": len(available),
            "matches": sum(row["decision_match"] is True for row in available),
            "accuracy_on_available": (
                sum(row["decision_match"] is True for row in available) / len(available)
                if available
                else None
            ),
            "changed_cases_total": len(changed_results),
            "changed_cases_available": sum(
                row["candidate_present"] for row in changed_results
            ),
            "changed_cases_fixed": sum(
                row["decision_match"] is True for row in changed_results
            ),
            "cases": candidate_results,
        },
    }
    return metrics

