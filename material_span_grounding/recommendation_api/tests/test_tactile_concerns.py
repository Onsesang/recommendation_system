from __future__ import annotations

import unittest

from recommendation_api.tactile_concerns import (
    ConcernPolicy,
    TactileConcernDetector,
)
from recommendation_api.tactile_models import TactileClaim
from recommendation_api.tactile_normalization import concept_matches


def claim(
    claim_id: str,
    reviewer_id: str,
    text: str,
    *,
    sentiment: str = "negative",
    rating: float | None = 2.0,
    verified: bool | None = True,
    confidence: float = 0.9,
    property_status: str = "present",
    human_verified: bool = False,
) -> TactileClaim:
    return TactileClaim(
        claim_id=claim_id,
        product_id="P1",
        review_id=f"review-{claim_id}",
        reviewer_id=reviewer_id,
        original_span=text,
        normalized_text=text,
        sentiment=sentiment,
        property_status=property_status,
        confidence=confidence,
        source="review_human_verified" if human_verified else "review_qwen",
        human_verified=human_verified,
        rating=rating,
        verified_purchase=verified,
    )


class FakeStore:
    def __init__(self, claims: list[TactileClaim]) -> None:
        self.product_metadata = {"P1": {"category": "tops", "title": "Test"}}
        self.config = {
            "concern": {
                "min_reviewers": 2,
                "min_negative_ratio": 0.5,
                "minimum_score": 0.1,
                "reviewer_saturation": 4.0,
                "verified_purchase_bonus": 0.05,
                "human_verified_bonus": 0.1,
            },
            "profile": {"public_evidence_per_concept": 5},
        }
        self._claims = claims

    def require_feature(self, name: str) -> None:
        if not self.config.get("feature_flags", {}).get(name, True):
            raise LookupError(f"Feature disabled: {name}")

    def concepts(self, product_id: str):
        grouped = {}
        for row in self._claims:
            for match in concept_matches(
                row.normalized_text, property_status=row.property_status
            ):
                grouped.setdefault(match.concept, []).append((row, match))
        return grouped


class TactileConcernTests(unittest.TestCase):
    def test_repeated_negative_concern_is_grounded_and_actionable(self) -> None:
        rows = [
            claim("C1", "U1", "The fabric is scratchy", rating=1.0),
            claim("C2", "U2", "Very scratchy", rating=2.0, human_verified=True),
            claim("C3", "U3", "Not scratchy", sentiment="positive", property_status="absent"),
        ]
        result = TactileConcernDetector(FakeStore(rows)).detect("P1")

        self.assertEqual(result["status"], "available")
        concern = result["concerns"][0]
        self.assertEqual(concern["property"], "scratchiness")
        self.assertEqual(concern["reviewer_count"], 2)
        self.assertAlmostEqual(concern["negative_ratio"], 2 / 3, places=6)
        self.assertEqual(concern["alternative_action"]["desired_direction"], "less")
        self.assertEqual(
            {row["original_span"] for row in concern["evidence"]},
            {"The fabric is scratchy", "Very scratchy"},
        )
        self.assertTrue(all("reviewer_id" not in row for row in concern["evidence"]))

    def test_duplicate_claims_from_one_reviewer_do_not_make_a_concern(self) -> None:
        rows = [
            claim("C1", "U1", "scratchy"),
            claim("C2", "U1", "very scratchy"),
            claim("C3", "U1", "scratchiest fabric"),
        ]
        result = TactileConcernDetector(FakeStore(rows)).detect("P1")
        self.assertEqual(result["status"], "no_qualifying_concerns")
        self.assertEqual(result["concerns"], [])

    def test_low_rating_does_not_convert_neutral_claim_to_negative(self) -> None:
        rows = [
            claim("C1", "U1", "thin", sentiment="neutral", rating=1.0),
            claim("C2", "U2", "very thin", sentiment="neutral", rating=1.0),
        ]
        result = TactileConcernDetector(FakeStore(rows)).detect("P1")
        self.assertEqual(result["concerns"], [])

    def test_contradictory_negative_directions_are_suppressed(self) -> None:
        rows = [
            claim("C1", "U1", "scratchy"),
            claim("C2", "U2", "not scratchy", property_status="absent"),
        ]
        result = TactileConcernDetector(FakeStore(rows)).detect("P1")
        self.assertEqual(result["concerns"], [])

    def test_absent_property_requests_more_in_alternative_action(self) -> None:
        rows = [
            claim("C1", "U1", "not soft", property_status="absent"),
            claim("C2", "U2", "isn't soft", property_status="absent"),
        ]
        concern = TactileConcernDetector(FakeStore(rows)).detect("P1")["concerns"][0]
        self.assertEqual(concern["property"], "softness")
        self.assertEqual(concern["alternative_action"]["desired_direction"], "more")

    def test_empty_and_unknown_products(self) -> None:
        result = TactileConcernDetector(FakeStore([])).detect("P1")
        self.assertEqual(result["status"], "insufficient_evidence")
        with self.assertRaises(KeyError):
            TactileConcernDetector(FakeStore([])).detect("missing")

    def test_disabled_feature_is_rejected(self) -> None:
        store = FakeStore([])
        store.config["feature_flags"] = {"tactile_concern": False}
        with self.assertRaises(LookupError):
            TactileConcernDetector(store).detect("P1")

    def test_verified_human_evidence_increases_confidence_and_config_validates(self) -> None:
        plain = [
            claim("C1", "U1", "scratchy", verified=False, human_verified=False),
            claim("C2", "U2", "scratchy", verified=False, human_verified=False),
        ]
        strong = [
            claim("C1", "U1", "scratchy", verified=True, human_verified=True),
            claim("C2", "U2", "scratchy", verified=True, human_verified=True),
        ]
        plain_result = TactileConcernDetector(FakeStore(plain)).detect("P1")["concerns"][0]
        strong_result = TactileConcernDetector(FakeStore(strong)).detect("P1")["concerns"][0]
        self.assertGreater(strong_result["confidence"], plain_result["confidence"])
        self.assertGreater(strong_result["concern_score"], plain_result["concern_score"])
        with self.assertRaises(ValueError):
            ConcernPolicy.from_config({"min_reviewers": 1})


if __name__ == "__main__":
    unittest.main()
