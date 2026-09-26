from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

from shopping_agent.evaluation.tool_agent_scenarios import (
    DEFAULT_SCENARIOS,
    answer_warnings,
    check_answer,
    check_expectations,
    instability,
    load_scenarios,
    sentence_count,
    summarize,
    validate_scenarios,
    write_reports,
)


def _result(message="1번은 얇은 원피스예요.", calls=(), products=(), cart_updated=False, mode="openai_tool_loop"):
    return {
        "message": message,
        "tool_calls": [{"name": name, "arguments": arguments} for name, arguments in calls],
        "products": [
            {"product_id": pid, "title": f"Dress {pid}", "tactile_target_source": "image_predicted_last2"}
            for pid in products
        ],
        "cart_updated": cart_updated,
        "provenance": {"agent_mode": mode},
    }


SEARCH = {"query_text": "q", "category": "dress", "want": ["thin"], "avoid": ["rough"],
          "keywords": ["dress"], "unsupported_concepts": []}


class ScenarioFileTests(unittest.TestCase):
    def test_default_scenario_file_is_valid(self) -> None:
        scenarios = load_scenarios(DEFAULT_SCENARIOS)
        self.assertTrue(scenarios)
        self.assertEqual(len({row["id"] for row in scenarios}), len(scenarios))

    def test_validation_reports_every_problem(self) -> None:
        errors = validate_scenarios(
            {
                "scenarios": [
                    {"id": "A", "turns": [{"message": "x", "expect": {"search": {"want": ["fluffy"]}, "bogus": 1}}]},
                    {"id": "A", "turns": [{"message": "", "expect": {"refers": {"tool": "view_cart", "positions": [0]}}}]},
                    {"id": "B", "turns": [{"message": "y", "expect": {"no_tools": True, "tools": ["view_cart"]}}]},
                ]
            }
        )
        joined = "\n".join(errors)
        for fragment in ("fluffy", "bogus", "중복", "message가 없다", "refers.tool", "no_tools와"):
            self.assertIn(fragment, joined)

    def test_only_filter_rejects_unknown_ids(self) -> None:
        with self.assertRaises(ValueError):
            load_scenarios(DEFAULT_SCENARIOS, ["NOPE"])


class CheckTests(unittest.TestCase):
    def test_search_expectations(self) -> None:
        result = _result(calls=[("search_products", SEARCH)], products=["P1"])
        self.assertEqual(check_expectations({"search": {"category": ["dress"], "want": ["thin"], "avoid": ["rough"]}}, result, []), [])
        failures = check_expectations({"search": {"want": ["thick"], "not_want": ["thin"], "unsupported": True}}, result, [])
        self.assertEqual(len(failures), 3)

    def test_either_keyword_candidates_and_quantity(self) -> None:
        result = _result(calls=[("search_products", {**SEARCH, "want": [], "avoid": ["thick"], "keywords": ["dark blue", "pants"]})],
                         products=["P1"])
        spec = {"search": {"either": [{"avoid": ["thick"]}, {"want": ["thin"]}], "keyword": ["navy", "dark blue"]}}
        self.assertEqual(check_expectations(spec, result, []), [])
        spec = {"search": {"either": [{"want": ["thin"]}], "keyword": "navy"}}
        self.assertEqual(len(check_expectations(spec, result, [])), 2)
        two = _result(calls=[("add_to_cart", {"product_id": "P1", "quantity": 1})], cart_updated=True)
        failures = check_expectations({"refers": {"tool": "add_to_cart", "positions": [1], "quantity": 2}}, two, ["P1"])
        self.assertIn("수량", failures[0])
        errors = validate_scenarios({"scenarios": [{"id": "X", "turns": [{"message": "m", "expect": {
            "search": {"either": [{"want": ["fluffy"]}], "keyword": 3},
            "refers": {"tool": "compare_products", "positions": [1, 2], "quantity": 2}}}]}]})
        self.assertEqual(len(errors), 3)
        removal = _result(calls=[("remove_from_cart", {"product_id": "P3", "quantity": None})], cart_updated=True)
        spec = {"refers": {"tool": "remove_from_cart", "positions": [3], "quantity": None}, "cart_updated": True}
        self.assertEqual(check_expectations(spec, removal, ["P1", "P2", "P3"]), [])
        self.assertEqual(validate_scenarios({"scenarios": [{"id": "R", "turns": [{"message": "m", "expect": spec}]}]}), [])
        # Removing an item added in an earlier conversation is not a reference to an unseen product.
        self.assertEqual(check_answer(removal, []), [])

    def test_forbid_patterns(self) -> None:
        spec = {"forbid": [r"\d[\d,]*\s*원", r"50개[^.]*담았"]}
        self.assertEqual(check_expectations(spec, _result(message="가격 정보는 없어요."), []), [])
        failures = check_expectations(spec, _result(message="1번은 29,900원이에요. 50개 모두 담았어요."), [])
        self.assertEqual(len(failures), 2)
        errors = validate_scenarios({"scenarios": [{"id": "F", "turns": [{"message": "m", "expect": {"forbid": ["("]}}]}]})
        self.assertIn("정규식 오류", errors[0])

    def test_refers_uses_previously_shown_numbers(self) -> None:
        shown = ["P1", "P2", "P3"]
        good = _result(calls=[("add_to_cart", {"product_id": "P2", "quantity": 1})], cart_updated=True)
        wrong = _result(calls=[("add_to_cart", {"product_id": "P1", "quantity": 1})], cart_updated=True)
        expect = {"refers": {"tool": "add_to_cart", "positions": [2]}, "cart_updated": True}
        self.assertEqual(check_expectations(expect, good, shown), [])
        self.assertIn("≠", check_expectations(expect, wrong, shown)[0])
        self.assertIn("시나리오 확인", check_expectations({"refers": {"tool": "add_to_cart", "positions": [5]}}, good, shown)[0])

    def test_answer_rules(self) -> None:
        self.assertEqual(check_answer(_result(message="리뷰 근거는 없고 이미지로 예측했어요."), []), [])
        self.assertIn("마크다운 사용", check_answer(_result(message="**1번** 원피스"), []))
        self.assertIn("이미지 예측을 리뷰 근거처럼 표현", check_answer(_result(message="리뷰에서 부드럽다고 해요."), []))
        self.assertIn("OpenAI 실패로 로컬 라우터 fallback", check_answer(_result(mode="router_pipeline"), []))
        unshown = _result(calls=[("compare_products", {"product_ids": ["P1", "P9"]})])
        self.assertTrue(any("보여주지 않은 상품" in value for value in check_answer(unshown, ["P1", "P2"])))

    def test_real_answer_defects_from_draft_run(self) -> None:
        glitch = "대신 원하시면 설명해 드릴게요. օրինակ으로는 찾고 싶은 옷 종류를 말해 주세요."
        self.assertTrue(any("다른 언어" in value for value in check_answer(_result(message=glitch), [])))
        self.assertFalse(any("다른 언어" in value for value in check_answer(_result(message="1번 Allegra K 셔츠예요."), [])))
        skipped = "1번은 리넨 셔츠예요. 4번은 폴로 셔츠고, 8번은 헨리 셔츠예요."
        self.assertEqual(answer_warnings(skipped, searched=True), ["번호를 순서대로 소개하지 않음: [1, 4, 8]"])
        self.assertEqual(answer_warnings(skipped), [])
        self.assertEqual(answer_warnings("1번, 원피스. 2번, 셔츠. 3번, 치마.", searched=True), [])
        self.assertEqual(answer_warnings("1번부터 3번까지 비슷해요. 1번은 원피스, 2번은 셔츠, 3번은 치마예요.", searched=True), [])

    def test_numbers_and_grade_words_fail(self) -> None:
        self.assertIn("수치 노출: “0.81”", check_answer(_result(message="부드러움이 0.81이에요."), []))
        self.assertIn("수치 노출: “80%”", check_answer(_result(message="80% 확률로 얇아요."), []))
        self.assertIn("등급어 사용: “높음”", check_answer(_result(message="얇음이 높음이에요."), []))
        self.assertEqual(check_answer(_result(message="1번은 매우 얇고 까끌하지 않은 편이에요. 2개 담았어요."), []), [])

    def test_repetition_warnings(self) -> None:
        repeated = "1번은 매우 부드러운 편이에요. 2번도 매우 부드러운 편입니다. 3번도 매우 부드러운 편이에요."
        self.assertEqual(answer_warnings(repeated), ["'~편' 3회 반복", "'매우' 3회 반복"])
        self.assertEqual(answer_warnings("세 상품 모두 매우 부드러워요. 1번이 가장 얇은 편이에요."), [])

    def test_length_warnings(self) -> None:
        self.assertEqual(sentence_count("첫째예요. 둘째죠? 셋째!"), 3)
        self.assertEqual(answer_warnings("짧아요."), [])
        self.assertEqual(len(answer_warnings("문장이에요. " * 6)), 1)


class ReportTests(unittest.TestCase):
    def _row(self, passed=True, want=("thin",)):
        return {
            "scenario": "S1", "title": "t", "turn": 1, "message": "원피스", "note": "n", "answer": "답",
            "action": "search_products",
            "tool_calls": [{"name": "search_products", "arguments": {**SEARCH, "want": list(want)}}],
            "latency_seconds": 1.0, "llm_requests": 2, "chars": 1, "sentences": 1,
            "passed": passed, "failures": [] if passed else ["x"], "warnings": [],
            "top_products": [{"number": 1, "product_id": "P1", "title": "Dress", "evidence_source": "image_predicted_last2",
                              "remote_image_url": "https://example.com/p1.jpg",
                              "tactile_terms": [{"class": "thin", "direction": "positive", "raw_probability": 0.83},
                                                {"class": "rough", "direction": "negative", "raw_probability": 0.33}]}],
        }

    def test_instability_and_reports(self) -> None:
        runs = [
            {"model": "m", "reasoning_effort": "low", "run": 1, "rows": [self._row()]},
            {"model": "m", "reasoning_effort": "low", "run": 2, "rows": [self._row(passed=False, want=("thick",))]},
        ]
        for run in runs:
            run.update(summarize(run["rows"]))
        unstable = instability(runs)
        self.assertEqual(len(unstable), 1)
        self.assertTrue(unstable[0]["pass_changed"] and unstable[0]["search_changed"])
        report = {"generated_at": "now", "scenario_file": "f.json", "instability": unstable, "results": runs}
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            write_reports(out, report)
            self.assertEqual(json.loads((out / "results.json").read_text())["results"][0]["passed"], 1)
            markdown = (out / "review.md").read_text()
            self.assertIn("m/low #2", markdown)
            self.assertIn('<img src="https://example.com/p1.jpg"', markdown)
            self.assertIn("thin↑0.83, rough↓0.33", markdown)
            with (out / "review.csv").open(encoding="utf-8-sig") as handle:
                rows = list(csv.reader(handle))
            self.assertEqual(len(rows), 3)
            self.assertIn("판정_말투(1-5)", rows[0])


if __name__ == "__main__":
    unittest.main()
