from __future__ import annotations

import unittest

from recommendation_api.tactile_models import TactileClaim, TactileIntent
from recommendation_api.tactile_normalization import canonical_concept, concept_matches


class TactileContractTests(unittest.TestCase):
    def test_claim_public_contract_omits_reviewer_id(self) -> None:
        claim = TactileClaim(
            claim_id="S1",
            product_id="B000000001",
            review_id="R1",
            reviewer_id="private-user",
            original_span="not scratchy",
            normalized_text="the fabric is not scratchy",
            property_status="absent",
            confidence=0.9,
        )
        public = claim.public_dict()
        self.assertNotIn("reviewer_id", public)
        self.assertEqual(public["original_span"], "not scratchy")

    def test_probability_and_required_field_validation(self) -> None:
        with self.assertRaises(ValueError):
            TactileClaim("", "A", "R", None, "soft", "soft")
        with self.assertRaises(ValueError):
            TactileIntent(confidence=1.1)

    def test_negation_and_multiple_open_vocabulary_matches(self) -> None:
        absent = concept_matches("the fabric is not scratchy", property_status="absent")
        self.assertEqual((absent[0].concept, absent[0].direction), ("scratchiness", -1))
        both = concept_matches("thick and stretchy")
        self.assertEqual({row.concept for row in both}, {"thickness", "stretchiness"})

    def test_ambiguous_light_is_not_forced_to_weight(self) -> None:
        match = concept_matches("the garment is light")[0]
        self.assertTrue(match.open_vocabulary)
        self.assertNotEqual(match.concept, "weight_lightness")
        self.assertEqual(canonical_concept("lightweight"), "weight_lightness")

    def test_unknown_claim_remains_open_vocabulary(self) -> None:
        match = concept_matches("has a papery hand-feel")[0]
        self.assertEqual(match.label, "has a papery hand-feel")
        self.assertTrue(match.concept.startswith("open:"))


if __name__ == "__main__":
    unittest.main()

