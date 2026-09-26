"""Human review UI for scenario evaluation results.

    python -m shopping_agent.evaluation.review_app shopping_agent/evaluation/results/<run>/results.json
    # open http://127.0.0.1:8890

Two review modes share one page per scenario turn:

- 추천 검수 (default): for every search turn, the top products each setting
  recommended are pooled once and judged 맞음 / 애매 / 안 맞음 against the user's
  request, which gives precision@k per setting.
- 대화 검수: every answer gets O/X for condition interpretation, product reference
  and evidence honesty, plus a memo.

Every click is saved at once to judgments.json next to results.json, so the review
can stop and resume anytime.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import threading
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from shopping_agent.evaluation.tool_agent_scenarios import label


STATIC_ROOT = Path(__file__).resolve().parent / "review_static"
TOP_K = 5  # products per setting to judge; precision@3 and @5 come from these
CRITERIA = ("condition", "reference", "honesty")
CRITERION_VALUES = {"O", "X", "NA"}
RELEVANCE_VALUES = {"O", "PARTIAL", "X"}
MAX_MEMO = 2000


def entry_key(result: dict[str, Any], row: dict[str, Any]) -> str:
    return f"{label(result)}|{row['scenario']}-{row['turn']}"


def product_key(page_id: str, product_id: str) -> str:
    # Keyed by the user's request, not the setting: a product is judged once per turn.
    return f"product|{page_id}|{product_id}"


def _search_args(row: dict[str, Any]) -> dict[str, Any] | None:
    calls = [call for call in row.get("tool_calls", []) if call["name"] == "search_products"]
    return calls[-1]["arguments"] if calls else None


def _pool_products(page: dict[str, Any]) -> list[dict[str, Any]]:
    """Union of every setting's top-K products, best rank first, with who recommended each."""
    pooled: dict[str, dict[str, Any]] = {}
    for entry in page["entries"]:
        if entry["search"] is None:
            continue
        for item in entry["top_products"][:TOP_K]:
            product = pooled.setdefault(
                item["product_id"],
                {
                    "key": product_key(page["id"], item["product_id"]),
                    "product_id": item["product_id"],
                    "title": item.get("title", ""),
                    "category": item.get("category"),
                    "remote_image_url": item.get("remote_image_url"),
                    "evidence_source": item.get("evidence_source"),
                    "tactile_terms": item.get("tactile_terms", []),
                    "ranks": {},
                },
            )
            product["ranks"][entry["config"]] = item["number"]
    return sorted(pooled.values(), key=lambda product: (min(product["ranks"].values()), -len(product["ranks"])))


def build_pages(report: dict[str, Any]) -> list[dict[str, Any]]:
    """Group results by scenario turn; each setting keeps its own earlier turns as context."""
    pages: dict[tuple[str, int], dict[str, Any]] = {}
    order: list[tuple[str, int]] = []
    for result in report["results"]:
        history: dict[str, list[dict[str, Any]]] = {}
        for row in result["rows"]:
            previous = history.setdefault(row["scenario"], [])
            page_id = (row["scenario"], row["turn"])
            if page_id not in pages:
                pages[page_id] = {
                    "id": f"{row['scenario']}-{row['turn']}",
                    "scenario": row["scenario"],
                    "title": row["title"],
                    "turn": row["turn"],
                    "message": row["message"],
                    "note": row["note"],
                    "entries": [],
                }
                order.append(page_id)
            pages[page_id]["entries"].append(
                {
                    "key": entry_key(result, row),
                    "config": label(result),
                    "model": result["model"],
                    "reasoning_effort": result["reasoning_effort"],
                    "run": result["run"],
                    "answer": row["answer"],
                    "tool_calls": row["tool_calls"],
                    "search": _search_args(row),
                    "top_products": row["top_products"],
                    "latency_seconds": row["latency_seconds"],
                    "chars": row["chars"],
                    "sentences": row["sentences"],
                    "passed": row["passed"],
                    "failures": row["failures"],
                    "warnings": row["warnings"],
                    "history": list(previous),
                }
            )
            previous.append(
                {
                    "turn": row["turn"],
                    "message": row["message"],
                    "answer": row["answer"],
                    "tool_calls": row["tool_calls"],
                    "top_products": row["top_products"],
                }
            )
    ordered = [pages[page_id] for page_id in order]
    for page in ordered:
        page["products"] = _pool_products(page)
    return ordered


class JudgmentStore:
    """judgments.json next to results.json, rewritten atomically on every change."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.lock = threading.Lock()
        if path.is_file():
            self.data = json.loads(path.read_text(encoding="utf-8"))
        else:
            self.data = {"reviewer": "", "items": {}}

    def _write(self) -> None:
        self.data["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        temporary = self.path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, self.path)

    def set_reviewer(self, name: str) -> None:
        with self.lock:
            self.data["reviewer"] = str(name)[:80]
            self._write()

    def update(self, key: str, values: dict[str, Any], valid_keys: set[str]) -> dict[str, Any]:
        if key not in valid_keys:
            raise KeyError(f"unknown entry: {key}")
        is_product = key.startswith("product|")
        clean: dict[str, Any] = {}
        for field, value in values.items():
            if field in CRITERIA and not is_product:
                if value is not None and value not in CRITERION_VALUES:
                    raise ValueError(f"{field} must be O, X, NA or null")
            elif field == "tone" and not is_product:
                if value is not None and (not isinstance(value, int) or not 1 <= value <= 5):
                    raise ValueError("tone must be 1~5 or null")
            elif field == "relevance" and is_product:
                if value is not None and value not in RELEVANCE_VALUES:
                    raise ValueError("relevance must be O, PARTIAL, X or null")
            elif field == "memo":
                if not isinstance(value, str):
                    raise ValueError("memo must be a string")
                value = value[:MAX_MEMO]
            else:
                raise ValueError(f"unknown field: {field}")
            clean[field] = value
        with self.lock:
            item = self.data["items"].setdefault(key, {})
            item.update(clean)
            item["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
            self._write()
            return dict(item)


def _csv(rows: list[list[Any]]) -> str:
    buffer = io.StringIO()
    csv.writer(buffer).writerows(rows)
    # BOM so Excel and Google Sheets read the Korean text as UTF-8.
    return "﻿" + buffer.getvalue()


def export_csv(pages: list[dict[str, Any]], judgments: dict[str, Any]) -> str:
    rows: list[list[Any]] = [
        ["턴", "시나리오", "사용자", "기대", "설정", "모델", "반복", "답변", "자동통과", "자동실패", "경고",
         "조건해석", "지칭", "근거정직성", "메모"]
    ]
    for page in pages:
        for entry in page["entries"]:
            item = judgments.get(entry["key"], {})
            rows.append(
                [page["id"], page["title"], page["message"], page["note"], entry["config"], entry["model"],
                 entry["run"], entry["answer"], "O" if entry["passed"] else "X", "\n".join(entry["failures"]),
                 "\n".join(entry["warnings"]), item.get("condition") or "", item.get("reference") or "",
                 item.get("honesty") or "", item.get("memo") or ""]
            )
    return _csv(rows)


def export_products_csv(pages: list[dict[str, Any]], judgments: dict[str, Any]) -> str:
    rows: list[list[Any]] = [
        ["턴", "시나리오", "사용자", "기대", "상품ID", "상품명", "카테고리", "추천한 설정(순위)", "판정", "메모", "이미지"]
    ]
    for page in pages:
        for product in page["products"]:
            item = judgments.get(product["key"], {})
            ranks = ", ".join(f"{config} {rank}위" for config, rank in product["ranks"].items())
            rows.append(
                [page["id"], page["title"], page["message"], page["note"], product["product_id"], product["title"],
                 product["category"] or "", ranks, item.get("relevance") or "", item.get("memo") or "",
                 product["remote_image_url"] or ""]
            )
    return _csv(rows)


class ReviewApp:
    def __init__(self, results_path: Path) -> None:
        self.results_path = results_path
        self.report = json.loads(results_path.read_text(encoding="utf-8"))
        self.pages = build_pages(self.report)
        self.keys = {entry["key"] for page in self.pages for entry in page["entries"]}
        self.keys |= {product["key"] for page in self.pages for product in page["products"]}
        self.store = JudgmentStore(results_path.parent / "judgments.json")

    def data(self) -> dict[str, Any]:
        return {
            "meta": {
                "run": self.results_path.parent.name,
                "generated_at": self.report.get("generated_at"),
                "scenario_file": self.report.get("scenario_file"),
                "configs": [label(result) for result in self.report["results"]],
                "top_k": TOP_K,
            },
            "pages": self.pages,
            "reviewer": self.store.data.get("reviewer", ""),
            "judgments": self.store.data.get("items", {}),
        }


def make_handler(app: ReviewApp) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:  # keep the terminal quiet
            return

        def _send(self, status: int, body: bytes, content_type: str, extra: dict[str, str] | None = None) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            for name, value in (extra or {}).items():
                self.send_header(name, value)
            self.end_headers()
            self.wfile.write(body)

        def _json(self, status: int, payload: Any) -> None:
            self._send(status, json.dumps(payload, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

        def _download(self, text: str, name: str) -> None:
            filename = f"{name}_{app.results_path.parent.name}.csv"
            self._send(HTTPStatus.OK, text.encode("utf-8"), "text/csv; charset=utf-8",
                       {"Content-Disposition": f'attachment; filename="{filename}"'})

        def do_GET(self) -> None:
            path = urlparse(self.path).path
            judgments = app.store.data.get("items", {})
            if path in {"/", "/index.html"}:
                self._send(HTTPStatus.OK, (STATIC_ROOT / "index.html").read_bytes(), "text/html; charset=utf-8")
            elif path == "/api/data":
                self._json(HTTPStatus.OK, app.data())
            elif path == "/api/export.csv":
                self._download(export_csv(app.pages, judgments), "conversation")
            elif path == "/api/export_products.csv":
                self._download(export_products_csv(app.pages, judgments), "products")
            else:
                self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})

        def do_POST(self) -> None:
            path = urlparse(self.path).path
            try:
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(min(length, 64 * 1024)) or b"{}")
                if path == "/api/judgments":
                    item = app.store.update(str(body.get("key")), dict(body.get("values") or {}), app.keys)
                    self._json(HTTPStatus.OK, {"key": body.get("key"), "item": item})
                elif path == "/api/reviewer":
                    app.store.set_reviewer(str(body.get("reviewer") or ""))
                    self._json(HTTPStatus.OK, {"reviewer": app.store.data["reviewer"]})
                else:
                    self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})
            except (KeyError, ValueError, json.JSONDecodeError) as exc:
                self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})

    return Handler


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("results", type=Path, help="tool_agent_scenarios가 만든 results.json")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8890)
    args = parser.parse_args()
    app = ReviewApp(args.results)
    server = ThreadingHTTPServer((args.host, args.port), make_handler(app))
    products = sum(len(page["products"]) for page in app.pages)
    print(f"검수 UI: http://{args.host}:{args.port}  ({len(app.pages)}페이지, 추천 상품 {products}개)", flush=True)
    print(f"판정 저장: {app.store.path}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
