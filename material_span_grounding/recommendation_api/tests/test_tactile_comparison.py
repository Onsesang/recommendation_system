from __future__ import annotations

import unittest

from recommendation_api.tactile_comparison import (
    TactileComparisonService,
    compare_products,
)
from recommendation_api.tactile_models import TactileClaim
from recommendation_api.tactile_normalization import concept_matches


def _claim(
    product_id: str,
    claim_id: str,
    text: str,
    *,
    reviewer: str,
    property_status: str = "present",
    confidence: float = 0.9,
) -> TactileClaim:
    return TactileClaim(
        claim_id=claim_id,
        product_id=product_id,
        review_id=f"review-{claim_id}",
        reviewer_id=reviewer,
        original_span=text,
        normalized_text=text,
        property_status=property_status,
        confidence=confidence,
    )


class FakeStore:
    def __init__(self, claims: dict[str, list[TactileClaim]], *, enabled: bool = True):
        self.claims_by_asin = claims
        self.product_metadata = {
            product_id: {"product_id": product_id} for product_id in claims
        }
        self.enabled = enabled

    def require_feature(self, name: str) -> None:
        if not self.enabled:
            raise LookupError(f"Feature disabled: {name}")

    def concepts(self, product_id: str):
        grouped = {}
        for claim in self.claims_by_asin[product_id]:
            for match in concept_matches(
                claim.normalized_text, property_status=claim.property_status
            ):
                grouped.setdefault(match.concept, []).append((claim, match))
        return grouped


class TactileComparisonTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = FakeStore(
            {
                "A": [
                    _claim("A", "a-soft", "soft fabric", reviewer="u1"),
                    _claim("A", "a-thin", "thin material", reviewer="u2"),
                    _claim("A", "a-stretch", "stretchy", reviewer="u3"),
                ],
                "B": [
                    _claim("B", "b-soft", "silky and soft", reviewer="u4"),
                    _claim(
                        "B",
                        "b-thin",
                        "not thin",
                        reviewer="u5",
                        property_status="absent",
                    ),
                ],
                "C": [
                    _claim("C", "c-soft", "not soft", reviewer="u6"),
                    _claim("C", "c-soft-2", "soft", reviewer="u7"),
                ],
                "EMPTY": [],
            }
        )

    def test_common_different_one_sided_and_conflicting_groups(self) -> None:
        result = compare_products(self.store, ["A", "B"])
        self.assertIn("softness", result["groups"]["common"])
        self.assertIn("thinness", result["groups"]["different"])
        self.assertIn("thinness", result["groups"]["conflicting"])
        self.assertIn("stretchiness", result["groups"]["one_sided"])

        stretch = next(
            row for row in result["dimensions"] if row["concept"] == "stretchiness"
        )
        self.assertEqual(stretch["products"]["B"]["status"], "insufficient_evidence")
        self.assertEqual(stretch["products"]["B"]["summary"], "insufficient_evidence")
        self.assertIsNone(stretch["products"]["B"]["confidence"])
        self.assertNotIn("medium", str(result).casefold())

    def test_evidence_is_exact_and_traceable_without_reviewer_id(self) -> None:
        result = TactileComparisonService(self.store).compare(["A", "B"], evidence_limit=1)
        soft = next(row for row in result["dimensions"] if row["concept"] == "softness")
        evidence = soft["products"]["A"]["evidence"][0]
        self.assertEqual(evidence["original_span"], "soft fabric")
        self.assertEqual(evidence["claim_id"], "a-soft")
        self.assertEqual(evidence["review_id"], "review-a-soft")
        self.assertEqual(evidence["product_id"], "A")
        self.assertNotIn("reviewer_id", evidence)

    def test_internal_conflict_and_three_or_more_products(self) -> None:
        result = compare_products(self.store, ["A", "B", "C"])
        soft = next(row for row in result["dimensions"] if row["concept"] == "softness")
        self.assertEqual(soft["products"]["C"]["status"], "conflicting")
        self.assertIn("conflicting", soft["classifications"])
        self.assertEqual(result["products"], ["A", "B", "C"])

    def test_all_empty_returns_explicit_empty_state_without_axes(self) -> None:
        store = FakeStore({"A": [], "B": []})
        result = compare_products(store, ["A", "B"])
        self.assertEqual(result["status"], "insufficient_evidence")
        self.assertEqual(result["dimensions"], [])
        self.assertEqual(
            result["product_evidence_status"],
            {"A": "insufficient_evidence", "B": "insufficient_evidence"},
        )

    def test_post_body_and_input_validation(self) -> None:
        service = TactileComparisonService(self.store)
        with self.assertRaisesRegex(ValueError, "required"):
            service.compare_request({})
        with self.assertRaises(ValueError):
            service.compare(["A"])
        with self.assertRaises(ValueError):
            service.compare(["A", "A"])
        with self.assertRaises(ValueError):
            service.compare(["A", "B"], evidence_limit=True)
        with self.assertRaises(KeyError):
            service.compare(["A", "UNKNOWN"])

    def test_disabled_feature_is_rejected(self) -> None:
        store = FakeStore({"A": [], "B": []}, enabled=False)
        with self.assertRaises(LookupError):
            compare_products(store, ["A", "B"])


if __name__ == "__main__":
    unittest.main()
