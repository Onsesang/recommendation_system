from __future__ import annotations

import unittest
from collections import defaultdict

from recommendation_api.tactile_description import (
    TactileDescriptionService,
    describe_product_tactile,
)
from recommendation_api.tactile_models import TactileClaim
from recommendation_api.tactile_normalization import concept_matches


def _claim(
    claim_id: str,
    text: str,
    *,
    reviewer: str,
    review_id: str | None = None,
    sentiment: str = "neutral",
    confidence: float = 0.8,
    property_status: str = "present",
) -> TactileClaim:
    return TactileClaim(
        claim_id=claim_id,
        product_id="P1",
        review_id=review_id or f"review-{claim_id}",
        reviewer_id=reviewer,
        original_span=text,
        normalized_text=text,
        sentiment=sentiment,
        property_status=property_status,
        confidence=confidence,
        source="review_qwen",
    )


class _FakeStore:
    def __init__(self, claims: list[TactileClaim]) -> None:
        self.config = {"profile": {"public_evidence_per_concept": 5}}
        self.product_metadata = {
            "P1": {"title": "Test product"},
            "EMPTY": {"title": "Empty product"},
        }
        self.claims_by_asin = {"P1": claims, "EMPTY": []}

    def require_feature(self, name: str) -> None:
        return None

    def concepts(self, product_id: str):
        grouped = defaultdict(list)
        for claim in self.claims_by_asin[product_id]:
            for match in concept_matches(
                claim.normalized_text, property_status=claim.property_status
            ):
                grouped[match.concept].append((claim, match))
        return dict(grouped)


class TactileDescriptionTests(unittest.TestCase):
    def test_counts_distinct_reviewers_and_preserves_exact_evidence(self) -> None:
        store = _FakeStore(
            [
                _claim("c1", "It is very soft", reviewer="u1", sentiment="positive", confidence=0.9),
                _claim("c2", "soft after washing", reviewer="u1", sentiment="positive", confidence=0.7),
                _claim("c3", "pleasantly soft", reviewer="u2", sentiment="neutral", confidence=0.8),
            ]
        )

        result = TactileDescriptionService(store).describe("P1")
        summary = result["summary"][0]

        self.assertEqual(result["reviewer_count"], 2)
        self.assertEqual(result["claim_count"], 3)
        self.assertEqual(summary["reviewer_count"], 2)
        self.assertEqual(
            summary["sentiment_distribution"],
            {"positive": 1, "neutral": 1, "negative": 0},
        )
        self.assertEqual(
            summary["representative_evidence"],
            ["It is very soft", "pleasantly soft"],
        )
        self.assertNotIn("reviewer_id", summary["evidence_details"][0])

    def test_one_reviewer_uses_singular_conservative_wording(self) -> None:
        store = _FakeStore([_claim("c1", "It is soft", reviewer="u1", sentiment="positive")])

        summary = describe_product_tactile(store, "P1")["summary"][0]

        self.assertEqual(summary["display_text"], "구매자 1명이 부드럽다고 언급했습니다.")
        self.assertNotIn("많", summary["display_text"])
        self.assertEqual(summary["source_breakdown"], {"review_qwen": 1})
        self.assertEqual(summary["evidence_details"][0]["confidence"], 0.8)
        self.assertEqual(summary["evidence_details"][0]["source"], "review_qwen")

    def test_contradictory_evidence_reports_both_sides_and_reduces_confidence(self) -> None:
        store = _FakeStore(
            [
                _claim("c1", "It is soft", reviewer="u1", confidence=0.9),
                _claim(
                    "c2",
                    "It is not soft",
                    reviewer="u2",
                    confidence=0.8,
                    property_status="absent",
                ),
            ]
        )

        summary = TactileDescriptionService(store).describe("P1")["summary"][0]

        self.assertTrue(summary["contradictory"])
        self.assertEqual(
            summary["direction_distribution"],
            {"present": 1, "absent": 1, "mixed": 0},
        )
        self.assertIn("의견이 엇갈립니다", summary["display_text"])
        self.assertEqual(summary["confidence"], 0.425)
        self.assertCountEqual(
            summary["representative_evidence"], ["It is soft", "It is not soft"]
        )

    def test_empty_state_does_not_invent_a_description(self) -> None:
        result = TactileDescriptionService(_FakeStore([])).describe("EMPTY")

        self.assertEqual(result["status"], "insufficient_evidence")
        self.assertEqual(result["summary"], [])
        self.assertEqual(result["reviewer_count"], 0)
        self.assertIn("근거를 찾지 못했습니다", result["message"])

    def test_open_vocabulary_claim_remains_quoted_and_exact(self) -> None:
        text = "The texture feels papery"
        result = TactileDescriptionService(
            _FakeStore([_claim("c1", text, reviewer="u1")])
        ).describe("P1")
        summary = result["summary"][0]

        self.assertTrue(summary["concept"].startswith("open:"))
        self.assertIn(text, summary["display_text"])
        self.assertEqual(summary["representative_evidence"], [text])

    def test_unknown_product_is_rejected(self) -> None:
        with self.assertRaisesRegex(KeyError, "Unknown ASIN"):
            TactileDescriptionService(_FakeStore([])).describe("UNKNOWN")


if __name__ == "__main__":
    unittest.main()
