from __future__ import annotations

import json
import tempfile
import threading
import unittest
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path

from shopping_agent.evaluation.review_app import ReviewApp, build_pages, make_handler


def _row(scenario, turn, message, products=()):
    calls = [{"name": "search_products", "arguments": {"category": "dress", "want": ["thin"], "avoid": []}}] if products else []
    return {
        "scenario": scenario, "title": "흐름", "turn": turn, "message": message, "note": "기대",
        "answer": f"{message}에 대한 답", "action": "respond", "tool_calls": calls, "latency_seconds": 1.0,
        "llm_requests": 1, "chars": 5, "sentences": 1, "passed": True, "failures": [], "warnings": [],
        "top_products": [{"number": n, "product_id": pid, "title": pid, "evidence_source": "image_predicted_last2",
                          "remote_image_url": "", "tactile_terms": []} for n, pid in enumerate(products, 1)],
    }


REPORT = {
    "generated_at": "2026-09-26T00:00:00+00:00",
    "scenario_file": "demo.json",
    "results": [
        {"model": model, "reasoning_effort": "low", "run": 1,
         "rows": [_row("S1", 1, "원피스 찾아줘", products), _row("S1", 2, "2번 담아줘"), _row("S2", 1, "안녕")]}
        for model, products in (("mini", ["P1", "P2"]), ("nano", ["P2", "P3"]))
    ],
}


class ReviewAppTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.results = Path(self.temporary.name) / "results.json"
        self.results.write_text(json.dumps(REPORT), encoding="utf-8")
        self.app = ReviewApp(self.results)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(self.app))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.temporary.cleanup()

    def request(self, method, path, payload=None):
        connection = HTTPConnection("127.0.0.1", self.server.server_address[1], timeout=10)
        body = json.dumps(payload) if payload is not None else None
        connection.request(method, path, body=body, headers={"Content-Type": "application/json"} if body else {})
        response = connection.getresponse()
        raw = response.read()
        connection.close()
        return response.status, raw, response.getheader("Content-Type")

    def test_pages_group_settings_and_keep_their_own_history(self) -> None:
        pages = build_pages(REPORT)
        self.assertEqual([page["id"] for page in pages], ["S1-1", "S1-2", "S2-1"])
        second = pages[1]
        self.assertEqual([entry["config"] for entry in second["entries"]], ["mini/low #1", "nano/low #1"])
        history = second["entries"][0]["history"]
        self.assertEqual([turn["message"] for turn in history], ["원피스 찾아줘"])
        self.assertEqual(history[0]["top_products"][1]["product_id"], "P2")
        self.assertEqual(pages[2]["entries"][0]["history"], [])
        # Products are pooled once per turn, best rank first, remembering who ranked them where.
        pooled = pages[0]["products"]
        self.assertEqual([product["product_id"] for product in pooled], ["P2", "P1", "P3"])
        self.assertEqual(pooled[0]["ranks"], {"mini/low #1": 2, "nano/low #1": 1})
        self.assertEqual(pooled[0]["key"], "product|S1-1|P2")
        self.assertEqual(pages[1]["products"], [])

    def test_judgments_are_validated_saved_and_exported(self) -> None:
        status, raw, _ = self.request("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn("시나리오 검수".encode(), raw)
        status, raw, _ = self.request("GET", "/api/data")
        data = json.loads(raw)
        self.assertEqual(len(data["pages"]), 3)
        key = data["pages"][1]["entries"][0]["key"]

        status, raw, _ = self.request("POST", "/api/judgments", {"key": key, "values": {"reference": "X", "tone": 4}})
        self.assertEqual(status, 200)
        status, raw, _ = self.request("POST", "/api/judgments", {"key": key, "values": {"memo": "다른 상품 담음"}})
        self.assertEqual(json.loads(raw)["item"]["reference"], "X")
        for bad in ({"key": key, "values": {"tone": 7}}, {"key": key, "values": {"honesty": "maybe"}},
                    {"key": "nope", "values": {"tone": 3}}, {"key": key, "values": {"score": 1}}):
            self.assertEqual(self.request("POST", "/api/judgments", bad)[0], 400)
        self.request("POST", "/api/reviewer", {"reviewer": "검수자"})

        saved = json.loads((self.results.parent / "judgments.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["reviewer"], "검수자")
        self.assertEqual(saved["items"][key]["memo"], "다른 상품 담음")
        # A restarted server resumes from the saved file.
        self.assertEqual(ReviewApp(self.results).data()["judgments"][key]["tone"], 4)

        product = data["pages"][0]["products"][0]["key"]
        self.assertEqual(self.request("POST", "/api/judgments", {"key": product, "values": {"relevance": "PARTIAL", "memo": "레깅스"}})[0], 200)
        for bad in ({"key": product, "values": {"relevance": "maybe"}}, {"key": product, "values": {"tone": 3}},
                    {"key": key, "values": {"relevance": "O"}}):
            self.assertEqual(self.request("POST", "/api/judgments", bad)[0], 400)
        status, raw, _ = self.request("GET", "/api/export_products.csv")
        rows = raw.decode("utf-8-sig").strip().splitlines()
        self.assertEqual(len(rows), 1 + 3)
        self.assertIn("PARTIAL", rows[1])
        self.assertIn("mini/low #1 2위", rows[1])

        status, raw, content_type = self.request("GET", "/api/export.csv")
        self.assertEqual(status, 200)
        self.assertIn("text/csv", content_type)
        text = raw.decode("utf-8-sig")
        self.assertIn("다른 상품 담음", text)
        self.assertEqual(len(text.strip().splitlines()), 1 + 6)


if __name__ == "__main__":
    unittest.main()
