from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from material_span.ai_audit_regression import _capture, evaluate_fixture
from material_span.common import write_jsonl
from material_span.verify import apply_semantic_guardrails


class AiAuditRegressionTests(unittest.TestCase):
    def test_semantic_guardrail_rejects_vague_and_accepts_bare_property(self) -> None:
        base = {
            "status": "success",
            "accepted": True,
            "claim": "x",
            "scope": "whole_garment",
            "property_status": "present",
            "intensity": "none",
            "sentiment": "neutral",
            "evidence_basis": "unspecified",
            "visual_observability": "low",
            "ambiguous": False,
            "rejection_reason": "",
        }
        vague = apply_semantic_guardrails(base, {"quote": "Fabric has a nice feel"})
        self.assertFalse(vague["accepted"])
        rejected = {**base, "accepted": False, "claim": "", "property_status": "not_applicable"}
        concrete = apply_semantic_guardrails(rejected, {"quote": "soft"})
        self.assertTrue(concrete["accepted"])

    def test_capture_accepts_exact_and_containing_quote(self) -> None:
        self.assertEqual(_capture("soft", ["soft"]), (True, True, "soft"))
        self.assertEqual(
            _capture("soft", ["the fabric is soft"]),
            (False, True, "the fabric is soft"),
        )
        self.assertEqual(_capture("warm", ["thin"]), (False, False, None))

    def test_evaluate_fixture_counts_regressions(self) -> None:
        fixture = {
            "label_source": "codex_ai_adjudicator_not_human",
            "changed_decision_span_ids": ["s1"],
            "candidate_cases": [
                {
                    "span_id": "s1",
                    "review_id": "r1",
                    "quote": "is soft",
                    "qwen_v2_0_accepted": False,
                    "expected_accepted": True,
                }
            ],
            "missing_extraction_cases": [
                {
                    "missing_span_id": "m1",
                    "review_id": "r1",
                    "quote": "warm",
                    "expected_accepted": True,
                }
            ],
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            extraction = root / "extract.jsonl"
            verification = root / "verify.jsonl"
            write_jsonl(
                extraction,
                [{"review_id": "r1", "evidence": [{"quote": "is soft"}, {"quote": "very warm"}]}],
            )
            write_jsonl(
                verification,
                [
                    {"review_id": "r1", "quote": "is soft", "status": "success", "accepted": True},
                    {"review_id": "r1", "quote": "very warm", "status": "success", "accepted": True},
                ],
            )
            metrics = evaluate_fixture(fixture, extraction, verification)
        self.assertEqual(metrics["missing_span_regression"]["containment_covered"], 1)
        self.assertEqual(metrics["missing_span_regression"]["covered_and_accepted"], 1)
        self.assertEqual(metrics["candidate_decision_regression"]["changed_cases_fixed"], 1)


if __name__ == "__main__":
    unittest.main()
