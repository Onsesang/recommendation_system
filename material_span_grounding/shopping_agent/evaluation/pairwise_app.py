"""Blind A/B review of two ranking settings, one click per search turn.

    python -m shopping_agent.evaluation.pairwise_app \\
        shopping_agent/evaluation/results/<ranking run>/results.json \\
        --baseline baseline --candidates texture_words color
    # open http://127.0.0.1:8892

For every candidate setting and every search turn where its top-3 differs from the
baseline's top-3, the page shows both lists side by side as "A" and "B" (sides are
shuffled per turn, stable across reloads) and asks which fits the request better.
Turns with identical top-3 are skipped, which keeps the review to a few dozen clicks
instead of judging every product. Choices are saved to pairwise_judgments.json next
to results.json; the summary reveals which side was which.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import threading
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


STATIC = Path(__file__).resolve().parent / "review_static" / "pairwise.html"
CHOICES = {"A", "B", "TIE"}
TOP_K = 3


def _product(item: dict[str, Any]) -> dict[str, Any]:
    return {key: item.get(key) for key in ("number", "product_id", "title", "category", "remote_image_url", "tactile_terms")}


def build_pairs(report: dict[str, Any], baseline: str, candidates: list[str], top_k: int = TOP_K) -> list[dict[str, Any]]:
    by_name = {result["model"]: result for result in report["results"]}
    missing = [name for name in [baseline, *candidates] if name not in by_name]
    if missing:
        raise ValueError(f"unknown settings: {missing}")
    base_rows = {f"{row['scenario']}-{row['turn']}": row for row in by_name[baseline]["rows"]}
    pairs = []
    for candidate in candidates:
        for row in by_name[candidate]["rows"]:
            turn_id = f"{row['scenario']}-{row['turn']}"
            base = base_rows[turn_id]
            left = [_product(item) for item in base["top_products"][:top_k]]
            right = [_product(item) for item in row["top_products"][:top_k]]
            if {item["product_id"] for item in left} == {item["product_id"] for item in right}:
                continue
            pair_id = f"{candidate}|{turn_id}"
            # Stable per pair, so a reload never swaps sides under the reviewer.
            candidate_is_a = hashlib.sha256(pair_id.encode()).digest()[0] % 2 == 0
            pairs.append({
                "id": pair_id, "candidate": candidate, "turn": turn_id, "title": row["title"],
                "message": row["message"], "note": row.get("note", ""),
                "search": (row.get("tool_calls") or [{}])[0].get("arguments", {}),
                "a": right if candidate_is_a else left,
                "b": left if candidate_is_a else right,
                "a_is": candidate if candidate_is_a else baseline,
                "b_is": baseline if candidate_is_a else candidate,
            })
    return pairs


class PairwiseStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.lock = threading.Lock()
        self.data = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {"items": {}}

    def update(self, pair_id: str, values: dict[str, Any], valid: set[str]) -> dict[str, Any]:
        if pair_id not in valid:
            raise KeyError(f"unknown pair: {pair_id}")
        clean = {}
        for field, value in values.items():
            if field == "choice":
                if value is not None and value not in CHOICES:
                    raise ValueError("choice must be A, B, TIE or null")
            elif field == "memo":
                if not isinstance(value, str):
                    raise ValueError("memo must be a string")
                value = value[:2000]
            else:
                raise ValueError(f"unknown field: {field}")
            clean[field] = value
        with self.lock:
            item = self.data["items"].setdefault(pair_id, {})
            item.update(clean)
            item["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
            temporary = self.path.with_suffix(".json.tmp")
            temporary.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(temporary, self.path)
            return dict(item)


def summarize(pairs: list[dict[str, Any]], items: dict[str, Any], baseline: str) -> dict[str, Any]:
    summary: dict[str, dict[str, int]] = {}
    for pair in pairs:
        row = summary.setdefault(pair["candidate"], {"pairs": 0, "judged": 0, "candidate": 0, "baseline": 0, "tie": 0})
        row["pairs"] += 1
        choice = items.get(pair["id"], {}).get("choice")
        if not choice:
            continue
        row["judged"] += 1
        if choice == "TIE":
            row["tie"] += 1
        else:
            winner = pair["a_is"] if choice == "A" else pair["b_is"]
            row["baseline" if winner == baseline else "candidate"] += 1
    return summary


class PairwiseApp:
    def __init__(self, results: Path, baseline: str, candidates: list[str]) -> None:
        self.results = results
        self.baseline = baseline
        self.pairs = build_pairs(json.loads(results.read_text(encoding="utf-8")), baseline, candidates)
        self.valid = {pair["id"] for pair in self.pairs}
        self.store = PairwiseStore(results.parent / "pairwise_judgments.json")

    def data(self) -> dict[str, Any]:
        # Side labels stay on the server until the summary is requested.
        public = [{key: value for key, value in pair.items() if key not in {"a_is", "b_is", "candidate"}}
                  for pair in self.pairs]
        return {"run": self.results.parent.name, "pairs": public, "judgments": self.store.data["items"]}

    def summary(self) -> dict[str, Any]:
        return {"baseline": self.baseline, "settings": summarize(self.pairs, self.store.data["items"], self.baseline)}


def make_handler(app: PairwiseApp) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            return

        def _send(self, status: int, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, status: int, payload: Any) -> None:
            self._send(status, json.dumps(payload, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

        def do_GET(self) -> None:
            path = urlparse(self.path).path
            if path in {"/", "/index.html"}:
                self._send(HTTPStatus.OK, STATIC.read_bytes(), "text/html; charset=utf-8")
            elif path == "/api/data":
                self._json(HTTPStatus.OK, app.data())
            elif path == "/api/summary":
                self._json(HTTPStatus.OK, app.summary())
            else:
                self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})

        def do_POST(self) -> None:
            try:
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(min(length, 64 * 1024)) or b"{}")
                if urlparse(self.path).path != "/api/judgments":
                    raise KeyError("not found")
                item = app.store.update(str(body.get("id")), dict(body.get("values") or {}), app.valid)
                self._json(HTTPStatus.OK, {"id": body.get("id"), "item": item})
            except (KeyError, ValueError, json.JSONDecodeError) as exc:
                self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})

    return Handler


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("results", type=Path)
    parser.add_argument("--baseline", default="baseline")
    parser.add_argument("--candidates", nargs="+", required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8892)
    args = parser.parse_args()
    app = PairwiseApp(args.results, args.baseline, args.candidates)
    server = ThreadingHTTPServer((args.host, args.port), make_handler(app))
    print(f"A/B 비교 검수: http://{args.host}:{args.port}  ({len(app.pairs)}건)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
