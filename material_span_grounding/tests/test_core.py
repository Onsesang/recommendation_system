from __future__ import annotations

import unittest

from material_span.extract import parse_extraction, render_prompt
from material_span.extract_recall import _merge_outputs
from material_span.density import _threshold_counts
from material_span.dense_m0_m1 import _fold_for_group
from material_span.human_audit import compute_metrics
from material_span.simple_m0_m1 import infer_category, split_name
from material_span.verify import parse_verification, render_verification_prompt


class ExtractionContractTests(unittest.TestCase):
    def test_density_threshold_counts(self) -> None:
        self.assertEqual(
            _threshold_counts([1, 2, 5, 10], (1, 2, 5, 10)),
            {"1": 4, "2": 3, "5": 2, "10": 1},
        )

    def test_simple_experiment_category_and_split_are_deterministic(self) -> None:
        self.assertEqual(infer_category("Soft knitted cardigan"), "sweater")
        self.assertEqual(split_name("brand:test", 17), split_name("brand:test", 17))
        self.assertIn(split_name("brand:test", 17), {"train", "validation", "test"})
        self.assertEqual(_fold_for_group("brand:test"), _fold_for_group("brand:test"))
        self.assertIn(_fold_for_group("brand:test"), range(5))

    def test_render_prompt_preserves_review(self) -> None:
        result = render_prompt("ID=__REVIEW_ID__ TEXT=__REVIEW_TEXT__", "R1", "Not soft!")
        self.assertEqual(result, "ID=R1 TEXT=Not soft!")

    def test_valid_exact_quote(self) -> None:
        result = parse_extraction(
            '{"review_id":"R1","evidence":[{"quote":"not see-through"}]}',
            "R1",
            "The fabric is thick but not see-through.",
        )
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["evidence"], [{"quote": "not see-through"}])

    def test_paraphrase_is_rejected(self) -> None:
        result = parse_extraction(
            '{"review_id":"R1","evidence":[{"quote":"opaque fabric"}]}',
            "R1",
            "It is not see-through.",
        )
        self.assertEqual(result["status"], "partial_invalid_quote")
        self.assertEqual(result["evidence"], [])

    def test_empty_evidence_is_success(self) -> None:
        result = parse_extraction(
            '{"review_id":"R1","evidence":[]}', "R1", "Shipping was fast."
        )
        self.assertEqual(result["status"], "success")

    def test_exact_string_evidence_is_tolerated(self) -> None:
        result = parse_extraction(
            '{"review_id":"R1","evidence":["the thickest fabric"]}',
            "R1",
            "These use the thickest fabric available.",
        )
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["evidence"], [{"quote": "the thickest fabric"}])

    def test_recall_merge_keeps_distinct_contained_quotes(self) -> None:
        reviews = [
            {
                "review_id": "R1",
                "asin": "A1",
                "user_id": "U1",
                "text": "This is the thickest fabric I have used. It stretches well.",
            }
        ]
        v1 = [
            {
                **reviews[0],
                "evidence": [
                    {"quote": "This is the thickest fabric I have used."}
                ],
            }
        ]
        lenses = [
            {
                "review_id": "R1",
                "lens": "surface_use",
                "status": "success",
                "evidence": [{"quote": "the thickest fabric"}],
                "invalid_quotes": [],
                "returned_quote_count": 1,
            },
            {
                "review_id": "R1",
                "lens": "behavior_care",
                "status": "success",
                "evidence": [{"quote": "It stretches well."}],
                "invalid_quotes": [],
                "returned_quote_count": 1,
            },
        ]
        merged = _merge_outputs(reviews, lenses, v1)[0]
        self.assertEqual(
            [item["quote"] for item in merged["evidence"]],
            [
                "This is the thickest fabric I have used.",
                "the thickest fabric",
                "It stretches well.",
            ],
        )
        self.assertEqual(
            merged["evidence"][0]["sources"], ["v1"]
        )

    def test_review_id_mismatch_is_schema_failure(self) -> None:
        result = parse_extraction(
            '{"review_id":"R2","evidence":[]}', "R1", "Soft fabric."
        )
        self.assertEqual(result["status"], "schema_failure")

    def test_verification_contract_accepts_valid_json(self) -> None:
        source = {"span_id": "S1", "quote": "not see-through", "review_text": "It is not see-through."}
        output = (
            '{"span_id":"S1","accepted":true,"quote":"not see-through",'
            '"claim":"the fabric is not see-through","scope":"main_fabric",'
            '"property_status":"absent","intensity":"none","sentiment":"positive",'
            '"evidence_basis":"worn_experience","visual_observability":"high",'
            '"ambiguous":false,"rejection_reason":""}'
        )
        self.assertEqual(parse_verification(output, source)["status"], "success")

    def test_verification_rejects_changed_quote(self) -> None:
        source = {"span_id": "S1", "quote": "not see-through", "review_text": "It is not see-through."}
        output = (
            '{"span_id":"S1","accepted":true,"quote":"opaque",'
            '"claim":"opaque","scope":"main_fabric","property_status":"present",'
            '"intensity":"none","sentiment":"positive","evidence_basis":"unspecified",'
            '"visual_observability":"high","ambiguous":false,"rejection_reason":""}'
        )
        self.assertEqual(parse_verification(output, source)["status"], "schema_failure")

    def test_verification_prompt_keeps_source_fields(self) -> None:
        source = {"span_id": "S1", "quote": "very soft", "review_text": "It is very soft."}
        rendered = render_verification_prompt(
            "__SPAN_ID__|__QUOTE__|__REVIEW_TEXT__", source
        )
        self.assertEqual(rendered, "S1|very soft|It is very soft.")

    def test_human_audit_waits_for_small_sample(self) -> None:
        rows = [
            {
                "span_id": "S1",
                "qwen_accepted": "True",
                "human_accepted": "True",
                "qwen_scope": "main_fabric",
                "human_scope": "main_fabric",
                "qwen_property_status": "present",
                "human_property_status": "present",
                "qwen_visual_observability": "low",
                "human_visual_observability": "low",
                "annotator_id": "A",
            }
        ]
        metrics = compute_metrics(rows)
        self.assertEqual(metrics["status"], "waiting_for_labels")
        self.assertFalse(metrics["development_triggered"])

    def test_human_audit_triggers_on_severe_early_failure(self) -> None:
        rows = []
        for index in range(35):
            rows.append(
                {
                    "span_id": f"A{index}",
                    "qwen_accepted": "True",
                    "human_accepted": "True" if index < 20 else "False",
                    "qwen_scope": "main_fabric",
                    "human_scope": "component",
                    "qwen_property_status": "present",
                    "human_property_status": "absent",
                    "qwen_visual_observability": "low",
                    "human_visual_observability": "high",
                    "annotator_id": "A",
                }
            )
        for index in range(15):
            rows.append(
                {
                    "span_id": f"R{index}",
                    "qwen_accepted": "False",
                    "human_accepted": "True" if index < 8 else "False",
                    "annotator_id": "A",
                }
            )
        for index in range(89):
            rows.append(
                {
                    "span_id": f"U{index}",
                    "qwen_accepted": "True",
                    "human_accepted": "",
                    "annotator_id": "",
                }
            )
        metrics = compute_metrics(rows)
        self.assertEqual(metrics["status"], "early_severe_failure")
        self.assertTrue(metrics["development_triggered"])
        self.assertEqual(len(metrics["error_analysis"]["false_positives"]), 15)
        self.assertEqual(len(metrics["error_analysis"]["false_negatives"]), 8)

    def test_human_audit_final_pass(self) -> None:
        rows = []
        for index in range(100):
            rows.append(
                {
                    "span_id": f"A{index}",
                    "qwen_accepted": "True",
                    "human_accepted": "True" if index < 95 else "False",
                    "qwen_scope": "main_fabric",
                    "human_scope": "main_fabric",
                    "qwen_property_status": "present",
                    "human_property_status": "present",
                    "qwen_visual_observability": "low",
                    "human_visual_observability": "low",
                    "annotator_id": "A",
                }
            )
        for index in range(39):
            rows.append(
                {
                    "span_id": f"R{index}",
                    "qwen_accepted": "False",
                    "human_accepted": "True" if index < 3 else "False",
                    "annotator_id": "A",
                }
            )
        metrics = compute_metrics(rows)
        self.assertEqual(metrics["status"], "final_pass")
        self.assertFalse(metrics["development_triggered"])

    def test_observed_recall_uses_only_complete_checked_reviews(self) -> None:
        rows = [
            {
                "span_id": "S1",
                "review_id": "R1",
                "qwen_accepted": "True",
                "human_accepted": "True",
            },
            {
                "span_id": "S2",
                "review_id": "R1",
                "qwen_accepted": "True",
                "human_accepted": "False",
            },
            {
                "span_id": "S3",
                "review_id": "R2",
                "qwen_accepted": "True",
                "human_accepted": "",
            },
        ]
        missing = [
            {"missing_span_id": "M1", "review_id": "R1", "quote": "thick"},
            {"missing_span_id": "M2", "review_id": "R2", "quote": "soft"},
        ]
        checks = [
            {"review_id": "R1", "checked": "True"},
            {"review_id": "R2", "checked": "True"},
        ]
        recall = compute_metrics(rows, missing, checks)["recall_audit"]
        self.assertEqual(recall["checked_reviews"], 2)
        self.assertEqual(recall["eligible_reviews"], 1)
        self.assertEqual(recall["accepted_extracted_spans"], 1)
        self.assertEqual(recall["missing_spans"], 1)
        self.assertEqual(recall["observed_span_recall"], 0.5)
        self.assertEqual(recall["pending_checked_reviews"][0]["review_id"], "R2")


if __name__ == "__main__":
    unittest.main()
