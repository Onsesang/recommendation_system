"""Scenario review sheet as one self-contained HTML page.

Each user turn is laid out as a chat: the answer every model setting gave, the tool
calls the model returned, the photos of the products it showed or referred to, and the
raw OpenAI exchange behind the answer (response ids, model snapshot, function calls and
what the tools sent back). Product photos are fetched once, shrunk and embedded as data
URIs so the page opens anywhere, including as a claude.ai artifact.

    python -m shopping_agent.evaluation.tool_agent_scenarios --render <run>/results.json
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from html import escape
from pathlib import Path
from typing import Any

import numpy as np

from shopping_agent.v1.config import AGENT_ROOT


IMAGE_CACHE = AGENT_ROOT / "evaluation/results/.image_cache"
THUMB_WIDTH = 240
# Failures from the rules every turn must follow (check_answer); the rest are scenario expectations.
ANSWER_RULES = ("OpenAI 실패", "마크다운", "다른 언어", "수치 노출", "등급어", "이미지 예측을 리뷰", "보여주지 않은", "예외")
CRITERIA = (
    ("search", "조건 해석", "촉감 표현이 맞는 want·avoid·옷 종류로 바뀌었나"),
    ("refers", "대화 맥락·지칭", "“두 번째 거”, “그거”가 맞는 상품을 가리켰나"),
    ("cart", "장바구니 조회", "장바구니 내용을 도구로 확인했나"),
    ("no_tools", "인사·범위 밖", "도구 없이 안내했나, 취급하지 않는 상품을 추천하지 않았나"),
    ("forbid", "근거 정직성", "리뷰·가격·결제를 지어내거나 지침을 노출하지 않았나"),
    ("other", "기타 대화", "취향 기억처럼 위에 속하지 않는 대화"),
)
TACTILE_KO = {
    "soft": "부드러움", "firm": "탄탄함", "smooth": "매끄러움", "rough": "까끌함", "non_elastic": "안 늘어남",
    "elastic": "신축성", "thin": "얇음", "thick": "두꺼움", "flexible": "하늘하늘", "stiff": "뻣뻣함",
    "warm": "따뜻함", "cool": "시원함", "spongy": "폭신함", "crisp": "각 잡힘",
}


# --------------------------------------------------------------------------- images


def thumb_url(url: str) -> str:
    """Amazon serves any width from the same path: `._AC_UL1500_.jpg` → `._AC_UL240_.jpg`."""
    if "media-amazon.com" not in url:
        return url
    resized = re.sub(r"\._[A-Z0-9_,]+_\.(jpg|jpeg|png)$", rf"._AC_UL{THUMB_WIDTH}_.\1", url, flags=re.I)
    if resized == url:
        resized = re.sub(r"\.(jpg|jpeg|png)$", rf"._AC_UL{THUMB_WIDTH}_.\1", url, flags=re.I)
    return resized


def _fetch(url: str) -> str | None:
    IMAGE_CACHE.mkdir(parents=True, exist_ok=True)
    path = IMAGE_CACHE / (hashlib.sha1(url.encode()).hexdigest() + ".jpg")
    if not path.exists():
        try:
            request = urllib.request.Request(thumb_url(url), headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(request, timeout=15) as response:
                if not response.headers.get_content_type().startswith("image/"):
                    return None
                data = response.read(400_000)
            path.write_bytes(data)
        except Exception:
            return None
    data = path.read_bytes()
    kind = "png" if data[:4] == b"\x89PNG" else "jpeg"
    return f"data:image/{kind};base64," + base64.b64encode(data).decode()


def embed_images(urls: set[str]) -> dict[str, str]:
    with ThreadPoolExecutor(max_workers=16) as pool:
        pairs = list(zip(urls, pool.map(_fetch, urls)))
    return {url: data for url, data in pairs if data}


# --------------------------------------------------------------------------- analysis


def turn_criterion(row: dict[str, Any]) -> str:
    """The review question a turn answers: the scenario's `criterion`, else the first expectation it sets."""
    if row.get("criterion"):
        return row["criterion"]
    expect = row.get("expect", {})
    for key in ("search", "refers", "no_tools", "forbid"):
        if expect.get(key):
            return key
    return "cart" if expect.get("tools") else "other"


def is_answer_rule(failure: str) -> bool:
    return failure.startswith(ANSWER_RULES)


def annotate(results: list[dict[str, Any]]) -> None:
    """Attach to each row the list the user saw before the turn and the products the turn touched."""
    for result in results:
        shown: list[dict[str, Any]] = []
        seen: dict[str, dict[str, Any]] = {}
        scenario = None
        for row in result["rows"]:
            if row["scenario"] != scenario:
                scenario, shown, seen = row["scenario"], [], {}
            row["_shown_before"] = shown
            for item in row["top_products"]:
                seen.setdefault(item["product_id"], item)
            touched = []
            for call in row["tool_calls"]:
                if call["name"] == "search_products":
                    continue
                arguments = call.get("arguments", {})
                for product_id in arguments.get("product_ids") or [arguments.get("product_id")]:
                    if product_id:
                        number = next((i for i, item in enumerate(shown, 1) if item["product_id"] == product_id), None)
                        touched.append({"call": call["name"], "product_id": product_id, "number": number,
                                        "item": seen.get(product_id), "quantity": arguments.get("quantity")})
            row["_touched"] = touched
            refers = row.get("expect", {}).get("refers")
            row["_expected"] = [
                {"number": position, "item": shown[position - 1] if position <= len(shown) else None}
                for position in (refers or {}).get("positions", [])
            ]
            if "search_products" in [call["name"] for call in row["tool_calls"]] and row["top_products"]:
                shown = row["top_products"]


def config_label(result: dict[str, Any]) -> str:
    effort = result.get("reasoning_effort") or "default"
    variant = f" · {result['variant']}" if result.get("variant") else ""
    return f"{result['model']} · {effort}{variant} · #{result['run']}"


def _group(result: dict[str, Any]) -> str:
    """What the page's hide toggles group cards by: the ranking variant, else the model."""
    return result.get("variant") or result["model"]


def summary_rows(results: list[dict[str, Any]]) -> dict[str, Any]:
    table: dict[str, list[tuple[int, int]]] = {key: [] for key, _, _ in CRITERIA}
    answer_rules, requests, tokens, calls = [], [], [], []
    for result in results:
        counts = {key: [0, 0] for key, _, _ in CRITERIA}
        rule_failures = 0
        request_count = token_count = call_count = 0
        for row in result["rows"]:
            key = turn_criterion(row)
            expectation_failures = [f for f in row["failures"] if not is_answer_rule(f)]
            counts[key][1] += 1
            counts[key][0] += not expectation_failures
            rule_failures += any(is_answer_rule(f) for f in row["failures"])
            for record in row.get("openai_requests", []):
                request_count += 1
                usage = record.get("usage") or {}
                token_count += (usage.get("input_tokens") or 0) + (usage.get("output_tokens") or 0)
                call_count += sum(item.get("type") == "function_call" for item in record.get("returned", []))
        for key in table:
            table[key].append(tuple(counts[key]))
        answer_rules.append(rule_failures)
        requests.append(request_count)
        tokens.append(token_count)
        calls.append(call_count)
    return {"criteria": table, "answer_rules": answer_rules, "requests": requests, "tokens": tokens, "calls": calls}


# --------------------------------------------------------------------------- html pieces


def _e(value: Any) -> str:
    return escape("" if value is None else str(value))


def _short_title(title: str, limit: int = 58) -> str:
    return title if len(title) <= limit else title[: limit - 1].rstrip() + "…"


def _evidence_badge(source: str | None) -> str:
    if source == "review_grounded_overlay":
        return '<span class="ev ev-review">리뷰 근거</span>'
    return '<span class="ev ev-pred">이미지 예측</span>'


def _terms(terms: list[Any]) -> str:
    parts = []
    for term in terms:
        if isinstance(term, dict):
            name = TACTILE_KO.get(term.get("class"), term.get("class"))
            sign = "피함" if term.get("direction") == "negative" else "원함"
            parts.append(f"{sign} {name} {float(term.get('raw_probability', 0.0)):.2f}")
    return " · ".join(parts)


def _product(item: dict[str, Any] | None, label: str, images: dict[str, str], mark: str = "") -> str:
    if not item:
        return f'<div class="prod missing"><div class="ph"></div><div class="pt"><b>{_e(label)}</b> 목록에 없음</div></div>'
    image = images.get(item.get("remote_image_url") or "")
    picture = (f'<img src="{image}" alt="{_e(label)} 상품 사진" loading="lazy">' if image
               else '<div class="ph" aria-hidden="true"></div>')
    terms = _terms(item.get("tactile_terms", []))
    reviews = item.get("train_count")
    popularity = f"<span>리뷰 {reviews}개(학습)</span>" if reviews is not None else ""
    return (
        f'<figure class="prod {mark}">{picture}<figcaption class="pt">'
        f'<b>{_e(label)}</b> {_e(_short_title(item.get("title", "")))}'
        f'<span class="pmeta">{_evidence_badge(item.get("evidence_source"))}'
        f'{f"<span>{_e(terms)}</span>" if terms else ""}{popularity}</span></figcaption></figure>'
    )


def _search_chips(arguments: dict[str, Any]) -> str:
    chips = [f'<span class="chip k">옷 종류 <b>{_e(arguments.get("category") or "없음")}</b></span>']
    for key, name in (("want", "원함"), ("avoid", "피함")):
        values = arguments.get(key) or []
        if values:
            text = ", ".join(f"{TACTILE_KO.get(v, v)}({v})" for v in values)
            chips.append(f'<span class="chip {key}">{name} <b>{_e(text)}</b></span>')
    if arguments.get("keywords"):
        chips.append(f'<span class="chip k">키워드 <b>{_e(", ".join(arguments["keywords"]))}</b></span>')
    if arguments.get("unsupported_concepts"):
        chips.append(f'<span class="chip un">반영 못 함 <b>{_e(", ".join(arguments["unsupported_concepts"]))}</b></span>')
    return "".join(chips)


def _tool_block(call: dict[str, Any]) -> str:
    arguments = call.get("arguments", {})
    status = "" if call.get("ok", True) else ' <span class="bad-t">오류 반환</span>'
    if call["name"] == "search_products":
        body = f'<div class="chips">{_search_chips(arguments)}</div>'
    else:
        body = f'<code>{_e(json.dumps(arguments, ensure_ascii=False))}</code>'
    return f'<div class="tool"><span class="tname">{_e(call["name"])}</span>{status}{body}</div>'


def _touched_block(row: dict[str, Any], images: dict[str, str]) -> str:
    if not row["_touched"] and not row["_expected"]:
        return ""
    expected_ids = {entry["item"]["product_id"] for entry in row["_expected"] if entry["item"]}
    cells = []
    for entry in row["_touched"]:
        number = f"화면 {entry['number']}번" if entry["number"] else "목록 밖 상품"
        verb = {"add_to_cart": "담기", "remove_from_cart": "빼기", "compare_products": "비교",
                "get_product_detail": "상세"}.get(entry["call"], entry["call"])
        quantity = f" ×{entry['quantity']}" if entry.get("quantity") is not None else ""
        mark = ""
        if expected_ids:
            mark = "hit" if entry["product_id"] in expected_ids else "miss"
        cells.append(_product(entry["item"], f"{verb} · {number}{quantity}", images, mark))
    touched_ids = {entry["product_id"] for entry in row["_touched"]}
    for entry in row["_expected"]:
        if entry["item"] and entry["item"]["product_id"] not in touched_ids:
            cells.append(_product(entry["item"], f"기대했던 {entry['number']}번 (가리키지 않음)", images, "miss"))
    return f'<div class="prods">{"".join(cells)}</div>'


def _trace(row: dict[str, Any]) -> str:
    records = row.get("openai_requests") or []
    if not records:
        return '<p class="muted small">OpenAI 요청 기록 없음</p>'
    items = []
    for index, record in enumerate(records, 1):
        sent = record.get("sent", {})
        if "tool_outputs" in sent:
            sent_html = "".join(f'<pre>{_e(text)}</pre>' for text in sent["tool_outputs"])
            sent_html = f'<div class="small muted">도구 결과를 모델에 전달</div>{sent_html}'
        elif "rewrite_request" in sent:
            sent_html = f'<div class="small muted">다시 쓰기 요청: {_e(sent["rewrite_request"])}</div>'
        else:
            sent_html = (f'<div class="small muted">대화 {sent.get("history_messages")}개 메시지 전송 · 마지막 사용자 발화 '
                         f'“{_e(sent.get("last_user_message"))}”</div>')
        if record.get("error"):
            got = f'<div class="bad-t">오류: {_e(record["error"])}</div>'
        else:
            returned = []
            for item in record.get("returned", []):
                if item["type"] == "function_call":
                    returned.append(f'<div>function_call <b>{_e(item["name"])}</b> <code>{_e(item.get("arguments"))}</code></div>')
                elif item["type"] == "message":
                    returned.append(f'<div>message “{_e(item.get("text"))}”</div>')
                else:
                    returned.append(f'<div class="muted">{_e(item["type"])}</div>')
            usage = record.get("usage") or {}
            got = (f'<div class="small muted">{_e(record.get("response_id"))} · {_e(record.get("response_model"))} · '
                   f'{record.get("seconds")}초 · 입력 {usage.get("input_tokens")} / 출력 {usage.get("output_tokens")} 토큰'
                   f'{" (추론 " + str(usage.get("reasoning_tokens")) + ")" if usage.get("reasoning_tokens") else ""}'
                   f'{" · tool_choice=none" if record.get("tool_choice") == "none" else ""}</div>{"".join(returned)}')
        items.append(f'<li><div class="req">요청 {index}</div>{sent_html}<div class="req">응답</div>{got}</li>')
    return f'<ol class="trace">{"".join(items)}</ol>'


def _answer_card(result: dict[str, Any], row: dict[str, Any], images: dict[str, str]) -> str:
    expectation = [f for f in row["failures"] if not is_answer_rule(f)]
    rules = [f for f in row["failures"] if is_answer_rule(f)]
    state = "pass" if row["passed"] else "fail"
    badge = '<span class="pill ok">통과</span>' if row["passed"] else '<span class="pill bad">실패</span>'
    if row["passed"] and row["warnings"]:
        badge += '<span class="pill warn">경고</span>'
    model_note = ""
    if row.get("llm_model") and row["llm_model"] != result["model"]:
        model_note = f' <span class="pill warn">{_e(row["llm_model"])}가 대신 답함</span>'
    tools = "".join(_tool_block(call) for call in row["tool_calls"]) or '<div class="tool none">도구 호출 없음</div>'
    products = ""
    if any(call["name"] == "search_products" for call in row["tool_calls"]) and row["top_products"]:
        products = '<div class="prods">' + "".join(
            _product(item, f"{item['number']}번", images) for item in row["top_products"][:3]
        ) + "</div>"
    products += _touched_block(row, images)
    notes = "".join(f'<li class="bad-t">{_e(f)}</li>' for f in expectation + rules)
    notes += "".join(f'<li class="warn-t">{_e(w)}</li>' for w in row["warnings"])
    cart = '<span class="small muted"> · 장바구니 변경됨</span>' if row.get("cart_updated") else ""
    return f"""
<section class="card {state}{' warned' if row['warnings'] else ''}" data-group="{_e(_group(result))}">
  <header class="card-h"><span class="cfg">{_e(config_label(result))}</span>{badge}{model_note}</header>
  <div class="bubble agent">{_e(row['answer']) or '<i>응답 없음</i>'}</div>
  <div class="small muted">{row['latency_seconds']}초 · OpenAI 요청 {len(row.get('openai_requests') or [])}회 · {row['chars']}자 / {row['sentences']}문장{cart}</div>
  <div class="tools">{tools}</div>
  {products}
  {f'<ul class="notes">{notes}</ul>' if notes else ''}
  <details><summary>OpenAI 요청·응답 원문</summary>{_trace(row)}</details>
</section>"""


# --------------------------------------------------------------------------- page


CSS = """
:root{--bg:#eef1f4;--surface:#ffffff;--ink:#17202b;--muted:#5a6573;--line:#d9dee5;--accent:#2d5b86;
--user:#dde8f3;--user-ink:#12304d;--ok:#1d7349;--ok-bg:#e1f2e8;--bad:#b0261c;--bad-bg:#fbe4e1;--warn:#8a5a00;
--warn-bg:#fbefd5;--want:#1d5f8a;--want-bg:#e0edf7;--avoid:#8a3d1d;--avoid-bg:#f6e6dc;--pred-bg:#efe9fb;--pred:#5b3fa8;
--code:#f4f6f8}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){color-scheme:dark;--bg:#0e1318;--surface:#161e27;
--ink:#e4e9ee;--muted:#98a4b1;--line:#29333e;--accent:#8db6dc;--user:#1f3347;--user-ink:#d8e7f5;--ok:#6fd19f;
--ok-bg:#16301f;--bad:#ff8f84;--bad-bg:#3a1a17;--warn:#f0c46a;--warn-bg:#352a12;--want:#9cc9ec;--want-bg:#17283a;
--avoid:#f0ad8a;--avoid-bg:#35231a;--pred-bg:#261f3b;--pred:#c4b2f5;--code:#10171e}}
:root[data-theme="dark"]{color-scheme:dark;--bg:#0e1318;--surface:#161e27;--ink:#e4e9ee;--muted:#98a4b1;--line:#29333e;
--accent:#8db6dc;--user:#1f3347;--user-ink:#d8e7f5;--ok:#6fd19f;--ok-bg:#16301f;--bad:#ff8f84;--bad-bg:#3a1a17;
--warn:#f0c46a;--warn-bg:#352a12;--want:#9cc9ec;--want-bg:#17283a;--avoid:#f0ad8a;--avoid-bg:#35231a;--pred-bg:#261f3b;
--pred:#c4b2f5;--code:#10171e}
body{background:var(--bg);color:var(--ink);font-family:"IBM Plex Sans KR","Apple SD Gothic Neo","Malgun Gothic",sans-serif;
font-size:15px;line-height:1.6}
.wrap{max-width:1500px;margin:0 auto;padding-inline:16px;padding-block:28px 64px}
h1{font-size:28px;line-height:1.25;margin:0 0 6px;text-wrap:balance;letter-spacing:-.01em}
h2{font-size:20px;margin:0;text-wrap:balance}
h3{font-size:13px;letter-spacing:.06em;text-transform:uppercase;color:var(--muted);margin:0 0 10px;font-weight:600}
p{margin:0;max-width:70ch}
code,pre{font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:12.5px}
code{background:var(--code);border-radius:4px;padding:1px 5px;word-break:break-all}
pre{background:var(--code);border:1px solid var(--line);border-radius:6px;padding:8px 10px;white-space:pre-wrap;
word-break:break-all;margin:6px 0;max-height:220px;overflow:auto}
.muted{color:var(--muted)}.small{font-size:13px}
.lede{display:grid;gap:10px;margin-bottom:28px}
.panel{background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:18px 20px}
.top{display:grid;gap:16px;grid-template-columns:repeat(auto-fit,minmax(min(100%,460px),1fr));margin-bottom:28px}
.tscroll{overflow-x:auto}
table{border-collapse:collapse;width:100%;font-size:14px;font-variant-numeric:tabular-nums}
th,td{text-align:left;padding:7px 10px;border-bottom:1px solid var(--line);vertical-align:top}
th{font-weight:600;color:var(--muted);font-size:13px}
td.num{white-space:nowrap}
.full{color:var(--ok);font-weight:600}.part{color:var(--warn);font-weight:600}.zero{color:var(--bad);font-weight:600}
.proof{display:grid;gap:8px}
.proof li{margin-bottom:4px}
.filters{display:flex;flex-wrap:wrap;gap:8px 18px;align-items:center;position:sticky;top:env(safe-area-inset-top,0px);
z-index:5;background:var(--bg);padding:10px 0;border-bottom:1px solid var(--line);margin-bottom:18px}
.filters label{display:flex;gap:6px;align-items:center;cursor:pointer}
.filters a{color:var(--accent);text-decoration:none;font-size:14px}
.filters a:hover{text-decoration:underline}
.scenario{margin-bottom:36px}
.scenario>header{display:flex;gap:10px;align-items:baseline;flex-wrap:wrap;margin-bottom:14px}
.sid{font-family:"IBM Plex Mono",monospace;color:var(--accent);font-weight:600}
.turn{margin-bottom:26px}
.turn-h{display:flex;justify-content:flex-end;margin-bottom:6px}
.bubble{border-radius:14px;padding:10px 14px;max-width:62ch;white-space:pre-wrap}
.bubble.user{background:var(--user);color:var(--user-ink);border-bottom-right-radius:4px;font-weight:500}
.bubble.agent{background:var(--code);border:1px solid var(--line);border-top-left-radius:4px}
.expect{text-align:right;font-size:13px;color:var(--muted);margin-bottom:10px}
.expect b{color:var(--ink);font-weight:600}
.cards{display:grid;gap:12px;grid-template-columns:repeat(auto-fit,minmax(min(100%,330px),1fr))}
.card{background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:12px 14px;display:grid;gap:9px;
align-content:start;min-width:0}
.card.fail{border-color:var(--bad);box-shadow:inset 3px 0 0 var(--bad)}
.card-h{display:flex;gap:6px;align-items:center;flex-wrap:wrap}
.cfg{font-family:"IBM Plex Mono",monospace;font-size:12.5px;font-weight:600;margin-right:auto}
.pill{font-size:12px;font-weight:600;border-radius:999px;padding:1px 9px}
.pill.ok{background:var(--ok-bg);color:var(--ok)}.pill.bad{background:var(--bad-bg);color:var(--bad)}
.pill.warn{background:var(--warn-bg);color:var(--warn)}
.tools{display:grid;gap:6px}
.tool{font-size:13px;display:grid;gap:4px}
.tool.none{color:var(--muted)}
.tname{font-family:"IBM Plex Mono",monospace;font-weight:600;color:var(--accent);font-size:12.5px}
.chips{display:flex;flex-wrap:wrap;gap:5px}
.chip{font-size:12.5px;border-radius:6px;padding:1px 7px;background:var(--code);border:1px solid var(--line)}
.chip b{font-weight:600}
.chip.want{background:var(--want-bg);color:var(--want);border-color:transparent}
.chip.avoid{background:var(--avoid-bg);color:var(--avoid);border-color:transparent}
.chip.un{background:var(--warn-bg);color:var(--warn);border-color:transparent}
.prods{display:grid;gap:8px;grid-template-columns:repeat(3,minmax(0,1fr))}
.prod{margin:0;display:grid;gap:5px;align-content:start;font-size:12.5px;line-height:1.4;min-width:0;border-radius:8px}
.prod img,.prod .ph{width:100%;aspect-ratio:3/4;object-fit:contain;background:#fff;border-radius:6px;border:1px solid var(--line)}
.prod.hit img,.prod.hit .ph{outline:3px solid var(--ok);outline-offset:-3px}
.prod.miss img,.prod.miss .ph{outline:3px solid var(--bad);outline-offset:-3px}
.prod.miss .pt b{color:var(--bad)}.prod.hit .pt b{color:var(--ok)}
.pt{overflow-wrap:anywhere}
.pmeta{display:flex;flex-direction:column;gap:2px;color:var(--muted);margin-top:3px}
.ev{font-size:11.5px;font-weight:600;border-radius:4px;padding:0 5px;justify-self:start;width:max-content}
.ev-pred{background:var(--pred-bg);color:var(--pred)}.ev-review{background:var(--ok-bg);color:var(--ok)}
.notes{margin:0;padding-left:18px;font-size:13px}
.bad-t{color:var(--bad)}.warn-t{color:var(--warn)}
details summary{cursor:pointer;color:var(--accent);font-size:13px}
details summary:focus-visible,.filters input:focus-visible,a:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.trace{padding-left:18px;font-size:13px;display:grid;gap:10px;margin:8px 0 0}
.req{font-weight:600;font-size:12px;letter-spacing:.04em;color:var(--muted);margin-top:4px}
body.only-issues .turn:not(.has-issue){display:none}
@media (max-width:520px){.prods{grid-template-columns:repeat(2,minmax(0,1fr))}h1{font-size:23px}}
"""

SCRIPT = """
(function(){
  function bind(id, cls){var el=document.getElementById(id); if(!el) return;
    el.addEventListener('change', function(){document.body.classList.toggle(cls, el.checked);});
    document.body.classList.toggle(cls, el.checked);}
  bind('f-issues','only-issues');
  document.querySelectorAll('input[data-hide]').forEach(function(box){
    function apply(){document.querySelectorAll('.card').forEach(function(card){
      if(card.getAttribute('data-group')===box.getAttribute('data-hide')) card.hidden=box.checked;});}
    box.addEventListener('change', apply); apply();
  });
})();
"""


def _ratio_cell(passed: int, total: int) -> str:
    if not total:
        return '<td class="num muted">-</td>'
    cls = "full" if passed == total else "zero" if passed == 0 else "part"
    return f'<td class="num"><span class="{cls}">{passed}/{total}</span></td>'


def _summary_html(report: dict[str, Any]) -> str:
    results = report["results"]
    summary = summary_rows(results)
    head = "".join(f"<th>{_e(config_label(r))}</th>" for r in results)
    body = []
    for key, name, question in CRITERIA:
        cells = summary["criteria"][key]
        if not any(total for _, total in cells):
            continue
        body.append(f'<tr><td><b>{name}</b><div class="small muted">{question}</div></td>'
                    + "".join(_ratio_cell(p, t) for p, t in cells) + "</tr>")
    body.append('<tr><td><b>답변 공통 규칙</b><div class="small muted">마크다운·수치·다른 언어·리뷰 사칭·안 보여준 상품 없음</div></td>'
                + "".join(_ratio_cell(r["turns"] - n, r["turns"]) for r, n in zip(results, summary["answer_rules"])) + "</tr>")
    body.append('<tr><td><b>전체 자동 통과</b></td>' + "".join(_ratio_cell(r["passed"], r["turns"]) for r in results) + "</tr>")
    quality = f'<table><thead><tr><th>판단 기준</th>{head}</tr></thead><tbody>{"".join(body)}</tbody></table>'

    perf = [
        ("지연 중앙값", [f"{r['latency_median']}초" for r in results]),
        ("지연 p90 / 최대", [f"{r['latency_p90']} / {r['latency_max']}초" for r in results]),
        ("평균 길이", [f"{r['mean_chars']}자 · {r['mean_sentences']}문장" for r in results]),
        ("길이·말투 경고 턴", [str(r["length_warnings"]) for r in results]),
        ("OpenAI 요청 / 모델이 낸 도구 호출", [f"{q}회 / {c}회" for q, c in zip(summary["requests"], summary["calls"])]),
        ("토큰 합계", [f"{t:,}" for t in summary["tokens"]]),
        ("로컬 라우터 fallback", [str(r["fallbacks"]) for r in results]),
    ]
    perf_rows = "".join(f"<tr><td>{name}</td>" + "".join(f'<td class="num">{_e(v)}</td>' for v in values) + "</tr>"
                        for name, values in perf)
    speed = f'<table><thead><tr><th>속도·길이</th>{head}</tr></thead><tbody>{perf_rows}</tbody></table>'
    return (f'<div class="panel"><h3>품질 · 자동 판정</h3><div class="tscroll">{quality}</div></div>'
            f'<div class="panel"><h3>속도 · 길이 · 호출</h3><div class="tscroll">{speed}</div></div>')


def _products_html(report: dict[str, Any]) -> str:
    """How the shown top 3 differ between settings: popularity, tactile fit, review evidence."""
    results = report["results"]
    if not report.get("variants"):
        return ""
    head = "".join(f"<th>{_e(config_label(r))}</th>" for r in results)
    stats = []
    for result in results:
        shown = [item for row in result["rows"] if any(c["name"] == "search_products" for c in row["tool_calls"])
                 for item in row["top_products"][:3]]
        counts = [item["train_count"] for item in shown if item.get("train_count") is not None]
        components = [term.get("match_component", 0.0) for item in shown for term in item.get("tactile_terms", [])
                      if isinstance(term, dict)]
        stats.append({
            "count": len(shown),
            "reviews_median": float(np.median(counts)) if counts else None,
            "reviews_zero": sum(value == 0 for value in counts),
            "tactile": sum(components) / len(components) if components else None,
            "grounded": sum(item.get("evidence_source") == "review_grounded_overlay" for item in shown),
        })
    rows = [
        ("화면 상위 3개 (검색 턴 합계)", [str(x["count"]) for x in stats]),
        ("학습 리뷰 수 중앙값", [f"{x['reviews_median']:.0f}개" if x["reviews_median"] is not None else "-" for x in stats]),
        ("학습 리뷰 0개 상품", [f"{x['reviews_zero']}개" for x in stats]),
        ("요청 촉감 충족 평균 (0~1)", [f"{x['tactile']:.2f}" if x["tactile"] is not None else "-" for x in stats]),
        ("리뷰 근거 있는 상품", [f"{x['grounded']}개" for x in stats]),
    ]
    body = "".join(f"<tr><td>{name}</td>" + "".join(f'<td class="num">{_e(v)}</td>' for v in values) + "</tr>"
                   for name, values in rows)
    described = "".join(f"<li><b>{_e(name)}</b>: {_e(text)}</li>" for name, text in report["variants"].items())
    return (f'<div class="panel"><h3>추천 방식 · 화면에 나온 상품</h3><ul class="small">{described}</ul>'
            f'<div class="tscroll"><table><thead><tr><th>상위 3개 기준</th>{head}</tr></thead><tbody>{body}</tbody></table></div>'
            f'<p class="small muted">촉감 충족은 원하는 촉감의 예측 확률, 피하는 촉감은 1에서 뺀 값의 평균입니다. '
            f'리뷰 수는 학습 split에 있는 리뷰 개수로, 인기도 점수의 재료입니다.</p></div>')


def _proof_html(report: dict[str, Any]) -> str:
    rows = [row for result in report["results"] for row in result["rows"]]
    records = [record for row in rows for record in row.get("openai_requests", [])]
    live = sum(row.get("agent_mode") == "openai_tool_loop" for row in rows)
    ids = {record.get("response_id") for record in records if record.get("response_id")}
    snapshots = sorted({record.get("response_model") for record in records if record.get("response_model")})
    calls = sum(len(row["tool_calls"]) for row in rows)
    from_model = sum(item.get("type") == "function_call" for record in records for item in record.get("returned", []))
    return f"""
<div class="panel proof">
  <h3>답변이 실제 OpenAI 호출에서 나왔는지</h3>
  <p>모든 발화는 서비스와 같은 <code>AgentService.message()</code> 경로로 보냈고, 문장별 정답이나 규칙으로 도구를 고르는 코드는 없습니다.
  검수표의 기대값은 판정 기준일 뿐 모델에 전달되지 않습니다.</p>
  <ul class="small">
    <li>OpenAI 도구 루프가 답한 턴: <b>{live}/{len(rows)}</b> (나머지는 로컬 라우터 fallback)</li>
    <li>Responses API 요청 <b>{len(records)}회</b>, 서로 다른 응답 ID <b>{len(ids)}개</b>. 응답 모델: {_e(", ".join(snapshots))}</li>
    <li>실행된 도구 호출 <b>{calls}회</b>, 모두 모델이 돌려준 <code>function_call</code> 항목 {from_model}개에서 나옴</li>
    <li>카드마다 “OpenAI 요청·응답 원문”을 열면 모델이 고른 함수와 인자, 도구가 모델에 돌려준 결과, 최종 문장을 차례로 볼 수 있습니다.</li>
  </ul>
</div>"""


def write_html(path: Path, report: dict[str, Any]) -> None:
    results = report["results"]
    annotate(results)
    urls = set()
    for result in results:
        for row in result["rows"]:
            for item in row["top_products"][:3]:
                if item.get("remote_image_url"):
                    urls.add(item["remote_image_url"])
            for entry in row["_touched"] + row["_expected"]:
                if entry.get("item") and entry["item"].get("remote_image_url"):
                    urls.add(entry["item"]["remote_image_url"])
    images = embed_images(urls)

    turns: dict[tuple[str, int], list[tuple[dict[str, Any], dict[str, Any]]]] = {}
    for result in results:
        for row in result["rows"]:
            turns.setdefault((row["scenario"], row["turn"]), []).append((result, row))
    sections: list[str] = []
    nav: list[str] = []
    current = None
    turn_no = 0
    for (scenario, turn), entries in turns.items():
        first = entries[0][1]
        if scenario != current:
            if current is not None:
                sections.append("</section>")
            sections.append(f'<section class="scenario" id="{_e(scenario)}"><header><span class="sid">{_e(scenario)}</span>'
                            f'<h2>{_e(first["title"])}</h2></header>')
            nav.append(f'<a href="#{_e(scenario)}">{_e(scenario)}</a>')
            current = scenario
        turn_no += 1
        issue = any((not row["passed"]) or row["warnings"] for _, row in entries)
        cards = "".join(_answer_card(result, row, images) for result, row in entries)
        note = f'<div class="expect">기대 <b>{_e(first["note"])}</b></div>' if first["note"] else ""
        sections.append(
            f'<article class="turn{" has-issue" if issue else ""}" id="t{turn_no}">'
            f'<div class="turn-h"><div class="bubble user"><span class="muted small">{turn_no}. </span>{_e(first["message"])}</div></div>'
            f'{note}<div class="cards">{cards}</div></article>'
        )
    if current is not None:
        sections.append("</section>")

    groups = list(dict.fromkeys(_group(r) for r in results))
    toggles = "".join(
        f'<label><input type="checkbox" id="f-hide-{index}" data-hide="{_e(name)}"> {_e(name)} 숨기기</label>'
        for index, name in enumerate(groups)
    ) if len(groups) > 1 else ""
    note_html = ""
    if report.get("note"):
        paragraphs = "".join(f"<p>{_e(p)}</p>" for p in str(report["note"]).split("\n\n") if p.strip())
        note_html = f'<div class="panel lede"><h3>검수 결론</h3>{paragraphs}</div>'
    html = f"""<title>쇼핑 에이전트 시연 검수</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600&family=IBM+Plex+Sans+KR:wght@400;500;600&display=swap">
<style>{CSS}</style>
<div class="wrap">
  <div class="lede">
    <h1>쇼핑 에이전트 시연 검수</h1>
    <p class="muted">시연 발화 {report.get('turn_count')}개 · 시나리오 {report.get('scenario_count')}개 · 설정 {len(results)}개
    ({_e(', '.join(config_label(r) for r in results))}) · 생성 {_e(report.get('generated_at'))} · {_e(report.get('scenario_file'))}</p>
  </div>
  {note_html}
  <div class="top">{_summary_html(report)}{_products_html(report)}</div>
  <div class="top">{_proof_html(report)}
    <div class="panel proof"><h3>읽는 법</h3><ul class="small">
      <li>오른쪽 파란 말풍선이 사용자 발화, 아래 카드가 설정별 답변입니다. 같은 모델의 #1, #2는 같은 대화를 두 번 실행한 결과입니다.</li>
      <li>검색 턴은 화면에 보인 1~3번 상품 사진을, 상세·비교·담기·빼기 턴은 모델이 가리킨 상품 사진을 보여 줍니다.
      초록 테두리는 기대한 상품, 빨간 테두리는 기대와 다른 상품입니다.</li>
      <li><span class="ev ev-pred">이미지 예측</span>은 리뷰 근거 없이 사진으로 예측한 촉감입니다. 이런 상품을 두고 답변이 “리뷰”를 근거로 말하면 실패입니다.
      상품 아래 숫자는 검수용 예측 확률이며 사용자에게는 읽어 주지 않습니다.</li>
      <li>경고는 5문장 또는 300자 초과, 같은 말버릇 반복, 번호를 순서대로 소개하지 않음입니다. 스크린리더로 들을 때 길거나 헷갈리는 답입니다.</li>
    </ul></div>
  </div>
  <nav class="filters" aria-label="보기 설정">
    <label><input type="checkbox" id="f-issues"> 실패·경고 있는 발화만</label>{toggles}
    <span class="small muted">바로가기</span>{' '.join(nav)}
  </nav>
  {''.join(sections)}
</div>
<script>{SCRIPT}</script>
"""
    path.write_text(html, encoding="utf-8")
