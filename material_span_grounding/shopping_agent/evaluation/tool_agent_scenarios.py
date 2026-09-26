"""Scenario evaluation for the OpenAI tool-loop agent against the real API.

Scenarios live in a JSON file (default: evaluation/demo_scenarios.json, format in
evaluation/SCENARIOS.md). Each turn is checked automatically on the tool the model
chose, the structured search it produced, which shown product it referred to and
the cart side effects. Every turn also gets answer checks that apply everywhere:
no markdown, no image prediction presented as review evidence, no reference to a
product that was never shown, and a screen-reader length warning.

Answer quality is left to a human reviewer: the run writes a review sheet
(review.md, review.csv) that puts every answer next to the products it was
grounded on, with empty judgement columns to fill in.

    python -m shopping_agent.evaluation.tool_agent_scenarios --check
    python -m shopping_agent.evaluation.tool_agent_scenarios \
        --models gpt-5.4-mini gpt-5.4-nano --reasoning-efforts low --repeats 2
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import tempfile
import time
import uuid
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from demo_agent.models import SUPPORTED_CATEGORIES, TACTILE_CLASSES

from shopping_agent.v1.config import AGENT_ROOT, AgentSettings
from shopping_agent.v1.tool_agent import TOOL_NAMES, OpenAIToolLoop


DEFAULT_SCENARIOS = AGENT_ROOT / "evaluation/demo_scenarios.json"
RESULTS_ROOT = AGENT_ROOT / "evaluation/results"

# The agent instructions ask for 2~5 sentences; longer answers are tiring through a screen reader.
MAX_SENTENCES = 5
MAX_CHARS = 300

EXPECT_KEYS = {"no_tools", "tools", "search", "refers", "cart_updated", "forbid"}
SEARCH_KEYS = {"category", "want", "avoid", "not_want", "keyword", "unsupported", "either"}
REFERRING_TOOLS = {"get_product_detail", "compare_products", "add_to_cart"}
# Cart items can come from earlier conversations, so removal is exempt from the "never shown" rule.
REFERS_TOOLS = REFERRING_TOOLS | {"remove_from_cart"}
QUANTITY_TOOLS = {"add_to_cart", "remove_from_cart"}
# Scripts other than Hangul and Latin: a stray token like "օրինակ" is unreadable through a screen reader.
FOREIGN_SCRIPT = re.compile(
    r"[\u0370-\u03FF\u0400-\u04FF\u0530-\u058F\u0590-\u05FF\u0600-\u06FF\u0900-\u097F"
    r"\u0E00-\u0E7F\u3040-\u30FF\u4E00-\u9FFF]+"
)
JUDGEMENT_COLUMNS = ["판정_조건해석(O/X)", "판정_지칭(O/X)", "판정_근거정직성(O/X)", "판정_말투(1-5)", "메모"]


# --------------------------------------------------------------------------- scenario file


def validate_scenarios(data: Any) -> list[str]:
    """Return every problem in a scenario document, so an editor can fix them in one pass."""
    if not isinstance(data, dict) or not isinstance(data.get("scenarios"), list):
        return ["최상위는 {\"scenarios\": [...]} 형태여야 한다"]
    errors: list[str] = []
    seen_ids: set[str] = set()
    for index, scenario in enumerate(data["scenarios"], 1):
        where = f"scenarios[{index}]"
        if not isinstance(scenario, dict):
            errors.append(f"{where}: 객체가 아니다")
            continue
        scenario_id = scenario.get("id")
        if not isinstance(scenario_id, str) or not scenario_id:
            errors.append(f"{where}: id가 없다")
        elif scenario_id in seen_ids:
            errors.append(f"{where}: id {scenario_id} 중복")
        else:
            seen_ids.add(scenario_id)
            where = scenario_id
        turns = scenario.get("turns")
        if not isinstance(turns, list) or not turns:
            errors.append(f"{where}: turns가 비어 있다")
            continue
        for turn_no, turn in enumerate(turns, 1):
            errors.extend(_validate_turn(turn, f"{where}-{turn_no}"))
    return errors


def _validate_turn(turn: Any, where: str) -> list[str]:
    if not isinstance(turn, dict):
        return [f"{where}: 객체가 아니다"]
    errors = []
    if not isinstance(turn.get("message"), str) or not turn["message"].strip():
        errors.append(f"{where}: message가 없다")
    expect = turn.get("expect", {})
    if not isinstance(expect, dict):
        return errors + [f"{where}: expect는 객체여야 한다"]
    for key in sorted(set(expect) - EXPECT_KEYS):
        errors.append(f"{where}: 알 수 없는 expect 키 {key}")
    for name in expect.get("tools", []):
        if name not in TOOL_NAMES:
            errors.append(f"{where}: 없는 도구 {name}")
    search = expect.get("search")
    if search is not None:
        if not isinstance(search, dict):
            errors.append(f"{where}: search는 객체여야 한다")
        else:
            for key in sorted(set(search) - SEARCH_KEYS):
                errors.append(f"{where}: 알 수 없는 search 키 {key}")
            for category in search.get("category", []):
                if category is not None and category not in SUPPORTED_CATEGORIES:
                    errors.append(f"{where}: 없는 category {category}")
            for key in ("want", "avoid", "not_want"):
                for value in search.get(key, []):
                    if value not in TACTILE_CLASSES:
                        errors.append(f"{where}: {key}에 없는 촉감 {value}")
            either = search.get("either", [])
            if not isinstance(either, list) or any(
                not isinstance(option, dict) or not option or set(option) - {"want", "avoid"} for option in either
            ):
                errors.append(f"{where}: either는 {{want, avoid}} 객체 목록")
            else:
                for option in either:
                    for key, values in option.items():
                        for value in values:
                            if value not in TACTILE_CLASSES:
                                errors.append(f"{where}: either.{key}에 없는 촉감 {value}")
            keyword = search.get("keyword")
            if keyword is not None and not (
                isinstance(keyword, str) or (isinstance(keyword, list) and keyword and all(isinstance(v, str) for v in keyword))
            ):
                errors.append(f"{where}: keyword는 문자열 또는 후보 문자열 목록")
    refers = expect.get("refers")
    if refers is not None:
        if not isinstance(refers, dict) or refers.get("tool") not in REFERS_TOOLS:
            errors.append(f"{where}: refers.tool은 {sorted(REFERS_TOOLS)} 중 하나")
        elif not refers.get("positions") or not all(
            isinstance(value, int) and value >= 1 for value in refers["positions"]
        ):
            errors.append(f"{where}: refers.positions는 1 이상 정수 목록")
        elif "quantity" in refers and (
            refers["tool"] not in QUANTITY_TOOLS
            or not (isinstance(refers["quantity"], int) or (refers["quantity"] is None and refers["tool"] == "remove_from_cart"))
        ):
            errors.append(f"{where}: refers.quantity는 담기·빼기에서 쓰는 정수 (빼기는 전부=null)")
    forbid = expect.get("forbid", [])
    if not isinstance(forbid, list):
        errors.append(f"{where}: forbid는 정규식 문자열 목록")
    else:
        for pattern in forbid:
            try:
                re.compile(pattern)
            except (re.error, TypeError) as exc:
                errors.append(f"{where}: forbid 정규식 오류 {pattern!r}: {exc}")
    if "no_tools" in expect and ({"tools", "search", "refers"} & set(expect)):
        errors.append(f"{where}: no_tools와 도구 기대를 함께 쓸 수 없다")
    return errors


def load_scenarios(path: Path, only: list[str] | None = None) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    errors = validate_scenarios(data)
    if errors:
        raise ValueError("시나리오 파일 오류:\n  " + "\n  ".join(errors))
    scenarios = data["scenarios"]
    if only:
        missing = sorted(set(only) - {row["id"] for row in scenarios})
        if missing:
            raise ValueError(f"없는 시나리오 id: {missing}")
        scenarios = [row for row in scenarios if row["id"] in only]
    return scenarios


# --------------------------------------------------------------------------- checks


def _called(result: dict[str, Any]) -> list[str]:
    return [call["name"] for call in result.get("tool_calls", [])]


def _search_args(result: dict[str, Any]) -> dict[str, Any] | None:
    calls = [call for call in result.get("tool_calls", []) if call["name"] == "search_products"]
    return calls[-1]["arguments"] if calls else None


def _referenced_ids(call: dict[str, Any]) -> list[str]:
    arguments = call.get("arguments", {})
    return list(arguments.get("product_ids") or [arguments.get("product_id")])


def check_expectations(expect: dict[str, Any], result: dict[str, Any], shown: list[str]) -> list[str]:
    """Scenario-specific checks. `shown` is the product list the user saw before this turn."""
    failures: list[str] = []
    called = _called(result)
    if expect.get("no_tools"):
        if called:
            failures.append(f"도구를 호출함: {called}")
        if result.get("products"):
            failures.append("상품을 반환함")
    for name in expect.get("tools", []):
        if name not in called:
            failures.append(f"{name} 미호출 (호출: {called})")
    if "search" in expect:
        failures.extend(_check_search(expect["search"], result))
    if "refers" in expect:
        failures.extend(_check_refers(expect["refers"], result, shown))
    if "cart_updated" in expect and bool(result.get("cart_updated")) != expect["cart_updated"]:
        failures.append(f"cart_updated={result.get('cart_updated')} (기대 {expect['cart_updated']})")
    for pattern in expect.get("forbid", []):
        match = re.search(pattern, result.get("message", ""))
        if match:
            failures.append(f"금지 표현 “{match.group(0)}” ({pattern})")
    return failures


def _check_search(spec: dict[str, Any], result: dict[str, Any]) -> list[str]:
    args = _search_args(result)
    if args is None:
        return ["search_products 미호출"]
    problems = []
    if "category" in spec and args.get("category") not in spec["category"]:
        problems.append(f"category={args.get('category')} (기대 {spec['category']})")
    want, avoid = set(args.get("want", [])), set(args.get("avoid", []))
    if not set(spec.get("want", [])) <= want:
        problems.append(f"want={sorted(want)} (기대 포함 {spec['want']})")
    if not set(spec.get("avoid", [])) <= avoid:
        problems.append(f"avoid={sorted(avoid)} (기대 포함 {spec['avoid']})")
    if set(spec.get("not_want", [])) & want:
        problems.append(f"want에 {sorted(set(spec['not_want']) & want)} 포함")
    either = spec.get("either")
    if either and not any(
        set(option.get("want", [])) <= want and set(option.get("avoid", [])) <= avoid for option in either
    ):
        problems.append(f"want={sorted(want)} avoid={sorted(avoid)} (기대: {either} 중 하나)")
    keyword = spec.get("keyword")
    if keyword:
        candidates = [keyword] if isinstance(keyword, str) else keyword
        got = " ".join(value.casefold() for value in args.get("keywords", []))
        if not any(candidate.casefold() in got for candidate in candidates):
            problems.append(f"keywords={args.get('keywords')} (기대 포함 {candidates} 중 하나)")
    if spec.get("unsupported") and not args.get("unsupported_concepts"):
        problems.append("unsupported_concepts 비어 있음")
    if not result.get("products"):
        problems.append("검색 결과 없음")
    return problems


def _check_refers(spec: dict[str, Any], result: dict[str, Any], shown: list[str]) -> list[str]:
    positions = spec["positions"]
    if max(positions) > len(shown):
        return [f"기대한 {positions}번이 직전 목록({len(shown)}개)에 없음 — 시나리오 확인 필요"]
    expected = sorted(shown[position - 1] for position in positions)
    for call in result.get("tool_calls", []):
        if call["name"] == spec["tool"]:
            got = sorted(_referenced_ids(call))
            if got != expected:
                return [f"{spec['tool']} 대상 {got} ≠ 기대 {positions}번 {expected}"]
            quantity = call.get("arguments", {}).get("quantity")
            if "quantity" in spec and quantity != spec["quantity"]:
                return [f"수량 {quantity} ≠ 기대 {spec['quantity']}"]
            return []
    return [f"{spec['tool']} 미호출 (호출: {_called(result)})"]


def check_answer(result: dict[str, Any], shown: list[str]) -> list[str]:
    """Rules from the agent instructions that must hold on every turn."""
    failures: list[str] = []
    if result.get("provenance", {}).get("agent_mode") != "openai_tool_loop":
        failures.append("OpenAI 실패로 로컬 라우터 fallback")
    message = result.get("message", "")
    if re.search(r"(\*\*|^#|^\s*[-*] |\|)", message, re.M):
        failures.append("마크다운 사용")
    foreign = FOREIGN_SCRIPT.findall(message)
    if foreign:
        failures.append(f"다른 언어 문자 섞임: {foreign}")
    number = re.search(r"\d*\.\d+|\d+\s*%", message)
    if number:
        failures.append(f"수치 노출: “{number.group(0)}”")
    grade = re.search(r"(높음|낮음)", message)
    if grade:
        failures.append(f"등급어 사용: “{grade.group(0)}”")
    grounded = any(row.get("tactile_target_source") == "review_grounded_overlay" for row in result.get("products", []))
    if not grounded:
        for match in re.finditer(r"리뷰", message):
            # "리뷰 근거는 없고", "리뷰 근거가 아니라" are the honest disclaimers the agent should give.
            window = message[match.start(): match.start() + 20]
            if not re.search(r"(?:없|아니|아닌|않)", window):
                failures.append("이미지 예측을 리뷰 근거처럼 표현")
                break
    visible = set(shown) | {row["product_id"] for row in result.get("products", [])}
    for call in result.get("tool_calls", []):
        if call["name"] in REFERRING_TOOLS:
            unknown = [value for value in _referenced_ids(call) if value not in visible]
            if unknown:
                failures.append(f"보여주지 않은 상품 지칭: {call['name']} {unknown}")
    return failures


def sentence_count(text: str) -> int:
    parts = [part for part in re.split(r"(?<=[.!?])\s+|\n+", text.strip()) if part.strip()]
    return len(parts)


def mentioned_numbers(message: str) -> list[int]:
    """Product numbers in the order the answer first mentions them."""
    seen: list[int] = []
    # "1번부터 3번까지" is a range, not an introduction order.
    message = re.sub(r"\d+번\s*(?:부터|~|-)\s*\d+번(?:까지)?", " ", message)
    for value in re.findall(r"(\d+)번", message):
        if int(value) not in seen:
            seen.append(int(value))
    return seen


def answer_warnings(message: str, searched: bool = False) -> list[str]:
    warnings = []
    # The instructions allow "~편" once per answer and "매우" once per sentence; repeats sound mechanical.
    hedges = len(re.findall(r"편(?:이|입|으로|인|이라)", message))
    if hedges >= 2:
        warnings.append(f"'~편' {hedges}회 반복")
    intensifiers = message.count("매우")
    if intensifiers >= 3:
        warnings.append(f"'매우' {intensifiers}회 반복")
    if searched:
        # A search answer should read the list from 1번 in order; skipped numbers confuse a listener.
        numbers = mentioned_numbers(message)
        if numbers and numbers != list(range(1, len(numbers) + 1)):
            warnings.append(f"번호를 순서대로 소개하지 않음: {numbers}")
    sentences = sentence_count(message)
    if sentences > MAX_SENTENCES:
        warnings.append(f"{sentences}문장 (권장 {MAX_SENTENCES} 이하)")
    if len(message) > MAX_CHARS:
        warnings.append(f"{len(message)}자 (권장 {MAX_CHARS} 이하)")
    return warnings


# --------------------------------------------------------------------------- run


def _tool_loop(settings: AgentSettings, model: str, effort: str | None) -> OpenAIToolLoop:
    config = settings.config["tool_agent"]
    return OpenAIToolLoop(
        api_key=settings.openai_api_key,
        model=model,
        timeout=int(settings.config["llm"]["timeout_seconds"]),
        max_steps=int(config["max_steps"]),
        max_output_tokens=int(config["max_output_tokens"]),
        reasoning_effort=effort,
    )


def run_config(app: Any, scenarios: list[dict[str, Any]], *, model: str, effort: str | None, run: int) -> dict[str, Any]:
    app.agent.tool_agent = _tool_loop(app.settings, model, effort)
    rows = []
    for scenario in scenarios:
        # A fresh user per scenario keeps carts and learned preferences from leaking between scenarios.
        login = app.auth.register(
            email=f"eval_{uuid.uuid4().hex[:12]}@example.com", password="password123", display_name="평가"
        )
        user_id = login.user["user_id"]
        session_id = app.agent.create_session(user_id)["session_id"]
        shown: list[str] = []
        for turn_no, turn in enumerate(scenario["turns"], 1):
            started = time.perf_counter()
            try:
                result = app.agent.message(user_id, session_id, turn["message"])
                error = None
            except Exception as exc:  # keep the run going; the sheet shows the failure
                result, error = {"message": "", "tool_calls": [], "products": [], "provenance": {}}, str(exc)
            elapsed = time.perf_counter() - started
            failures = [f"예외: {error}"] if error else []
            failures += check_expectations(turn.get("expect", {}), result, shown)
            failures += check_answer(result, shown)
            message = result.get("message", "")
            rows.append(
                {
                    "scenario": scenario["id"],
                    "title": scenario.get("title", ""),
                    "turn": turn_no,
                    "message": turn["message"],
                    "note": turn.get("note", ""),
                    "answer": message,
                    "action": result.get("action"),
                    "tool_calls": result.get("tool_calls", []),
                    "latency_seconds": round(elapsed, 2),
                    "llm_requests": result.get("provenance", {}).get("llm_requests"),
                    "chars": len(message),
                    "sentences": sentence_count(message),
                    "passed": not failures,
                    "failures": failures,
                    "warnings": answer_warnings(message, searched="search_products" in _called(result)),
                    "top_products": [
                        {
                            "number": number,
                            "product_id": row["product_id"],
                            "title": row.get("title", ""),
                            "category": row.get("category"),
                            "evidence_source": row.get("tactile_target_source"),
                            "remote_image_url": row.get("remote_image_url"),
                            "tactile_terms": row.get("score_breakdown", {}).get("tactile_terms", []),
                        }
                        # Ten covers every number the agent can refer to (shown_products_memory);
                        # the reports still show the first three.
                        for number, row in enumerate(result.get("products", [])[:10], 1)
                    ],
                }
            )
            if "search_products" in _called(result) and result.get("products"):
                shown = [row["product_id"] for row in result["products"]]
    return {"model": model, "reasoning_effort": effort, "run": run, **summarize(rows), "rows": rows}


def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    return ordered[round(fraction * (len(ordered) - 1))] if ordered else 0.0


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    latencies = [row["latency_seconds"] for row in rows]
    count = max(1, len(rows))
    return {
        "turns": len(rows),
        "passed": sum(row["passed"] for row in rows),
        "latency_median": _percentile(latencies, 0.5),
        "latency_p90": _percentile(latencies, 0.9),
        "latency_max": max(latencies, default=0.0),
        "mean_chars": round(sum(row["chars"] for row in rows) / count, 1),
        "mean_sentences": round(sum(row["sentences"] for row in rows) / count, 1),
        "length_warnings": sum(bool(row["warnings"]) for row in rows),
        "fallbacks": sum(any("fallback" in value for value in row["failures"]) for row in rows),
    }


def _config_key(result: dict[str, Any]) -> str:
    return f"{result['model']}/{result['reasoning_effort'] or 'default'}"


def label(result: dict[str, Any]) -> str:
    return f"{_config_key(result)} #{result['run']}"


def instability(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Turns whose pass/fail or search conditions changed between repeats of the same setting."""
    groups: dict[tuple[str, str, int], list[dict[str, Any]]] = {}
    for result in results:
        for row in result["rows"]:
            groups.setdefault((_config_key(result), row["scenario"], row["turn"]), []).append(row)
    unstable = []
    for (config, scenario, turn), rows in groups.items():
        if len(rows) < 2:
            continue
        searches = {
            # English keywords vary freely between runs; only category and tactile conditions count.
            json.dumps({k: v for k, v in (_search_args(row) or {}).items() if k in {"category", "want", "avoid"}},
                       sort_keys=True)
            for row in rows
        }
        passed = {row["passed"] for row in rows}
        if len(passed) > 1 or len(searches) > 1:
            unstable.append(
                {
                    "config": config,
                    "scenario": scenario,
                    "turn": turn,
                    "message": rows[0]["message"],
                    "pass_changed": len(passed) > 1,
                    "search_changed": len(searches) > 1,
                }
            )
    return unstable


# --------------------------------------------------------------------------- reports


def terms_text(terms: list[Any]) -> str:
    """`thin↑0.83, rough↓0.33`: ↑ is a wanted class, ↓ an avoided one, with the predicted probability."""
    parts = []
    for term in terms:
        if isinstance(term, dict):
            arrow = "↓" if term.get("direction") == "negative" else "↑"
            parts.append(f"{term.get('class')}{arrow}{float(term.get('raw_probability', 0.0)):.2f}")
        else:
            parts.append(str(term))
    return ", ".join(parts) or "-"


def _tool_text(call: dict[str, Any]) -> str:
    return f"{call['name']} {json.dumps(call.get('arguments', {}), ensure_ascii=False)}"


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    results = report["results"]
    lines = [
        "# 시연 시나리오 검수표",
        "",
        f"- 생성: {report['generated_at']} · 시나리오 파일: `{report['scenario_file']}`",
        "- 자동 판정은 도구 선택, 검색 조건, 지칭, 장바구니 변화, 마크다운·리뷰 표현 규칙만 본다.",
        "  **답변이 자연스러운지, 상품이 조건에 맞는지는 사람이 판정한다** (review.csv의 판정 칸).",
        f"- 길이 경고 기준: {MAX_SENTENCES}문장 또는 {MAX_CHARS}자 초과",
        "",
        "## 요약",
        "",
        "| 설정 | 자동 통과 | 지연 중앙값 | p90 | 최대 | 평균 글자 | 평균 문장 | 길이 경고 | fallback |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for result in results:
        lines.append(
            f"| {label(result)} | {result['passed']}/{result['turns']} | {result['latency_median']}초 | "
            f"{result['latency_p90']}초 | {result['latency_max']}초 | {result['mean_chars']} | "
            f"{result['mean_sentences']} | {result['length_warnings']} | {result['fallbacks']} |"
        )
    if report["instability"]:
        lines += ["", "## 반복 실행 간 달라진 턴", ""]
        for row in report["instability"]:
            changed = " · ".join(
                text for flag, text in ((row["pass_changed"], "통과 여부"), (row["search_changed"], "검색 조건")) if flag
            )
            lines.append(f"- {row['config']} {row['scenario']}-{row['turn']} “{row['message']}”: {changed} 변경")
    lines += ["", "## 턴별 비교", ""]
    scenario_turns: dict[tuple[str, int], list[tuple[dict[str, Any], dict[str, Any]]]] = {}
    for result in results:
        for row in result["rows"]:
            scenario_turns.setdefault((row["scenario"], row["turn"]), []).append((result, row))
    current = None
    for (scenario, turn), entries in scenario_turns.items():
        first = entries[0][1]
        if scenario != current:
            lines += [f"### {scenario}. {first['title']}", ""]
            current = scenario
        lines += [f"#### {scenario}-{turn} 사용자: {first['message']}", ""]
        if first["note"]:
            lines += [f"기대: {first['note']}", ""]
        for result, row in entries:
            status = "✅ 통과" if row["passed"] else "❌ 실패"
            lines.append(
                f"**{label(result)}** — {status} · {row['latency_seconds']}초 · {row['chars']}자/{row['sentences']}문장"
            )
            lines.append("")
            lines.append("> " + (row["answer"] or "(응답 없음)").replace("\n", "\n> "))
            lines.append("")
            for call in row["tool_calls"]:
                lines.append(f"- 도구 `{_tool_text(call)}`")
            if row["top_products"]:
                images = " ".join(
                    f'<img src="{item["remote_image_url"]}" width="80" alt="{item["number"]}번">'
                    for item in row["top_products"][:3]
                    if item["remote_image_url"]
                )
                if images:
                    lines.append(f"- {images}")
                for item in row["top_products"][:3]:
                    lines.append(
                        f"- {item['number']}번 {item['title'][:80]} · 근거 {item['evidence_source']} · "
                        f"촉감 {terms_text(item['tactile_terms'])}"
                    )
            for failure in row["failures"]:
                lines.append(f"- ❌ {failure}")
            for warning in row["warnings"]:
                lines.append(f"- ⚠️ {warning}")
            lines.append("")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_csv(path: Path, report: dict[str, Any]) -> None:
    header = [
        "설정", "모델", "reasoning", "반복", "시나리오", "턴", "사용자", "기대", "답변", "도구",
        "1번", "1번 촉감", "1번 이미지", "2번", "2번 촉감", "2번 이미지", "3번", "3번 촉감", "3번 이미지",
        "지연(초)", "글자", "문장", "자동통과", "자동실패", "경고", *JUDGEMENT_COLUMNS,
    ]
    # utf-8-sig so Excel and Google Sheets open the Korean text correctly.
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        for result in report["results"]:
            for row in result["rows"]:
                products = row["top_products"][:3] + [{}] * (3 - len(row["top_products"][:3]))
                product_cells = []
                for item in products[:3]:
                    product_cells += [
                        item.get("title", ""),
                        terms_text(item["tactile_terms"]) if item else "",
                        item.get("remote_image_url", ""),
                    ]
                writer.writerow(
                    [
                        label(result), result["model"], result["reasoning_effort"] or "default", result["run"],
                        row["scenario"], row["turn"], row["message"], row["note"], row["answer"],
                        "\n".join(_tool_text(call) for call in row["tool_calls"]),
                        *product_cells,
                        row["latency_seconds"], row["chars"], row["sentences"],
                        "O" if row["passed"] else "X", "\n".join(row["failures"]), "\n".join(row["warnings"]),
                        *[""] * len(JUDGEMENT_COLUMNS),
                    ]
                )


def write_reports(out_dir: Path, report: dict[str, Any]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "results.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    write_markdown(out_dir / "review.md", report)
    write_csv(out_dir / "review.csv", report)


# --------------------------------------------------------------------------- cli


def _display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(AGENT_ROOT.parent))
    except ValueError:
        return str(path)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--scenarios", type=Path, default=DEFAULT_SCENARIOS, help="시나리오 JSON 파일")
    parser.add_argument("--only", nargs="+", help="이 id의 시나리오만 실행 (예: S3 S5)")
    parser.add_argument("--models", nargs="+", default=["gpt-5.4-mini"])
    parser.add_argument(
        "--reasoning-efforts", nargs="+", default=["config"],
        help="예: low none. config는 configs/v1.json의 tool_agent.reasoning_effort",
    )
    parser.add_argument("--repeats", type=int, default=1, help="같은 설정을 반복 실행해 흔들림을 본다")
    parser.add_argument("--out-dir", type=Path, help="기본값: evaluation/results/<시각>")
    parser.add_argument("--check", action="store_true", help="시나리오 파일만 검사하고 끝낸다 (API 호출 없음)")
    parser.add_argument("--render", type=Path, help="기존 results.json에서 review.md·review.csv만 다시 만든다")
    args = parser.parse_args()

    if args.render:
        write_reports(args.render.parent, json.loads(args.render.read_text(encoding="utf-8")))
        print(args.render.parent)
        return

    scenarios = load_scenarios(args.scenarios, args.only)
    turns = sum(len(row["turns"]) for row in scenarios)
    if args.check:
        print(f"OK: {args.scenarios} · 시나리오 {len(scenarios)}개 · 턴 {turns}개")
        return

    from shopping_agent.v1.server import AgentApplication  # loads the full catalog; not needed for --check

    temporary = tempfile.TemporaryDirectory()
    settings = replace(
        AgentSettings.load(),
        database_path=Path(temporary.name) / "agent.sqlite3",
        llm_provider="openai",
        catalog_mode="full",
        langsmith_tracing=False,
    )
    if not settings.openai_api_key:
        raise SystemExit("OPENAI_API_KEY is not configured")
    default_effort = settings.config["tool_agent"].get("reasoning_effort") or None
    efforts = [default_effort if value == "config" else value for value in args.reasoning_efforts]
    app = AgentApplication(settings)

    results = []
    for model in args.models:
        for effort in efforts:
            for run in range(1, args.repeats + 1):
                result = run_config(app, scenarios, model=model, effort=effort, run=run)
                results.append(result)
                print(
                    f"{label(result)}: {result['passed']}/{result['turns']} passed, "
                    f"median {result['latency_median']}s, max {result['latency_max']}s, "
                    f"length warnings {result['length_warnings']}",
                    flush=True,
                )
                for row in result["rows"]:
                    if not row["passed"]:
                        print(f"  FAIL {row['scenario']}-{row['turn']} {row['message']!r}: {row['failures']}")
    temporary.cleanup()

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "scenario_file": _display_path(args.scenarios),
        "scenario_count": len(scenarios),
        "turn_count": turns,
        "instability": instability(results),
        "results": results,
    }
    out_dir = args.out_dir or RESULTS_ROOT / datetime.now().strftime("%Y%m%d_%H%M%S")
    write_reports(out_dir, report)
    print(out_dir)


if __name__ == "__main__":
    main()
