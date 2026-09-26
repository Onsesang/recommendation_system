from __future__ import annotations

import json
import tempfile
import threading
import unittest
from dataclasses import replace
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path

from shopping_agent.v1.config import AgentSettings
from shopping_agent.v1.server import AgentApplication, make_handler


class AgentApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temporary = tempfile.TemporaryDirectory()
        settings = replace(
            AgentSettings.load(),
            database_path=Path(cls.temporary.name) / "agent.sqlite3",
            llm_provider="deterministic",
            openai_api_key="",
            gemini_api_key="",
            # These assertions describe the curated catalog, independent of the local .env.
            catalog_mode="curated",
            cors_origins=("https://onsesang-front.vercel.app", "http://localhost:3000"),
        )
        cls.app = AgentApplication(settings)
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(cls.app))
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.port = cls.server.server_address[1]
        status, payload, headers = cls.request(
            "POST", "/agent/v1/auth/register",
            {"email": "api@example.com", "password": "password123", "display_name": "API 사용자"}
        )
        assert status == 201
        cls.token = payload["access_token"]

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown(); cls.server.server_close(); cls.thread.join(timeout=2)
        cls.temporary.cleanup()

    @classmethod
    def request(cls, method, path, payload=None, token=None):
        connection = HTTPConnection("127.0.0.1", cls.port, timeout=20)
        headers = {}
        body = None
        if payload is not None:
            body = json.dumps(payload)
            headers["Content-Type"] = "application/json"
        if token:
            headers["Authorization"] = f"Bearer {token}"
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        raw = response.read()
        result = json.loads(raw) if "json" in (response.getheader("Content-Type") or "") else raw.decode()
        response_headers = dict(response.getheaders())
        connection.close()
        return response.status, result, response_headers

    def auth_request(self, method, path, payload=None):
        return self.request(method, path, payload, self.token)

    def test_health_openapi_and_unauthorized(self) -> None:
        status, health, _ = self.request("GET", "/agent/v1/health")
        self.assertEqual(status, 200)
        self.assertEqual(health["package_version"], "1.1.0")
        self.assertEqual(health["catalog_products"], 465)
        self.assertEqual(
            set(health["features"]["conversation_tools"]),
            {"respond_greeting", "respond_out_of_scope", "search_products"},
        )
        self.assertFalse(health["features"]["checkout"])
        self.assertTrue(health["tracing"]["langsmith_ready"])
        self.assertFalse(health["tracing"]["langsmith_export_active"])
        status, spec, _ = self.request("GET", "/agent/v1/openapi.json")
        self.assertIn("/agent/v1/sessions/{session_id}/messages", spec["paths"])
        status, _, _ = self.request("GET", "/agent/v1/products")
        self.assertEqual(status, 401)

    def test_catalog_session_message_preferences_and_detail(self) -> None:
        status, catalog, _ = self.auth_request("GET", "/agent/v1/products?page=1&page_size=30")
        self.assertEqual((status, len(catalog["items"]), catalog["total"]), (200, 30, 465))
        status, session, _ = self.auth_request("POST", "/agent/v1/sessions", {})
        self.assertEqual(status, 201)
        status, agent, _ = self.auth_request(
            "POST", f"/agent/v1/sessions/{session['session_id']}/messages",
            {"message": "부드럽고 비치지 않는 바지를 찾아줘", "limit": 5}
        )
        self.assertEqual(status, 200)
        self.assertEqual(agent["action"], "search_products")
        self.assertEqual(agent["intent"]["category"], "pants")
        self.assertTrue(agent["products"])
        self.assertTrue(agent["trace_id"])
        self.assertIn("personalization_weighted", agent["products"][0]["score_breakdown"])
        self.assertNotIn("reviewer_id", json.dumps(agent, ensure_ascii=False))
        status, preferences, _ = self.auth_request("GET", "/agent/v1/preferences")
        self.assertTrue(preferences["items"])
        product_id = agent["products"][0]["product_id"]
        status, detail, _ = self.auth_request("GET", f"/agent/v1/products/{product_id}")
        self.assertEqual(status, 200)
        self.assertIn("tactile_summary", detail)
        self.assertNotIn("reviewer_id", json.dumps(detail, ensure_ascii=False))

    def test_agent_routes_greeting_and_out_of_scope_without_search(self) -> None:
        before = len(self.auth_request("GET", "/agent/v1/preferences")[1]["items"])
        session = self.auth_request("POST", "/agent/v1/sessions", {})[1]
        path = f"/agent/v1/sessions/{session['session_id']}/messages"

        status, greeting, _ = self.auth_request("POST", path, {"message": "안녕"})
        self.assertEqual(status, 200)
        self.assertEqual(greeting["action"], "respond_greeting")
        self.assertEqual(greeting["routing"]["source"], "local_intent_model")
        self.assertFalse(greeting["products"])
        self.assertIn("원하는", greeting["message"])
        self.assertIn("옷", greeting["message"])

        status, off_topic, _ = self.auth_request(
            "POST", path, {"message": "오늘 서울 날씨 알려줘"}
        )
        self.assertEqual(status, 200)
        self.assertEqual(off_topic["action"], "respond_out_of_scope")
        self.assertFalse(off_topic["products"])
        self.assertIn("답변할 수 없습니다", off_topic["message"])
        self.assertIn("스타일", off_topic["message"])
        after = len(self.auth_request("GET", "/agent/v1/preferences")[1]["items"])
        self.assertEqual(after, before)

    def test_event_cart_preference_update_delete_and_disabled_checkout(self) -> None:
        product_id = self.app.tools.catalog.catalog_asins[0]
        event = {"event_id": "api-idempotent", "event_type": "product_click", "product_id": product_id, "context": {"rank": 1}}
        self.assertEqual(self.auth_request("POST", "/agent/v1/events", event)[0], 201)
        status, duplicate, _ = self.auth_request("POST", "/agent/v1/events", event)
        self.assertEqual((status, duplicate["created"]), (200, False))
        self.assertEqual(self.auth_request("POST", "/agent/v1/cart/items", {"product_id": product_id})[0], 201)
        status, cart, _ = self.auth_request("GET", "/agent/v1/cart")
        self.assertEqual(len(cart["items"]), 1)
        self.assertFalse(cart["checkout_enabled"])
        self.assertEqual(self.auth_request("DELETE", f"/agent/v1/cart/items/{product_id}")[0], 200)
        preferences = self.auth_request("GET", "/agent/v1/preferences")[1]["items"]
        if preferences:
            preference_id = preferences[0]["preference_id"]
            status, updated, _ = self.auth_request("PATCH", f"/agent/v1/preferences/{preference_id}", {"strength": .5})
            self.assertEqual(updated["strength"], .5)
            self.assertEqual(self.auth_request("DELETE", f"/agent/v1/preferences/{preference_id}")[0], 200)
        self.assertEqual(self.auth_request("POST", "/agent/v1/checkout", {})[0], 404)

    def test_cors_echoes_only_registered_origins(self) -> None:
        for origin, allowed in (("https://onsesang-front.vercel.app", True), ("http://localhost:3000", True),
                                ("https://evil.example.com", False)):
            connection = HTTPConnection("127.0.0.1", self.port, timeout=10)
            connection.request("OPTIONS", "/agent/v1/auth/login", headers={
                "Origin": origin, "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type, authorization"})
            response = connection.getresponse(); response.read(); connection.close()
            self.assertEqual(response.status, 204)
            self.assertEqual(response.getheader("Access-Control-Allow-Origin"), origin if allowed else None)
            self.assertIn("Authorization", response.getheader("Access-Control-Allow-Headers"))
            self.assertEqual(response.getheader("Vary"), "Origin")

    def test_rate_limits_return_429_with_retry_after(self) -> None:
        from shopping_agent.v1.rate_limit import RateLimiter
        original = self.app.rate_limiter
        self.app.rate_limiter = RateLimiter({"login": {"limit": 2, "window_seconds": 60},
                                             "messages": {"limit": 1, "window_seconds": 60}})
        try:
            bad_login = {"email": "api@example.com", "password": "wrong-password"}
            self.assertEqual(self.request("POST", "/agent/v1/auth/login", bad_login)[0], 401)
            self.assertEqual(self.request("POST", "/agent/v1/auth/login", bad_login)[0], 401)
            status, payload, headers = self.request("POST", "/agent/v1/auth/login", bad_login)
            self.assertEqual((status, payload["error"]["code"]), (429, "too_many_requests"))
            self.assertGreaterEqual(int(headers["Retry-After"]), 1)
            self.assertIn("초 후 다시 시도", payload["error"]["message"])
            session = self.auth_request("POST", "/agent/v1/sessions", {})[1]
            path = f"/agent/v1/sessions/{session['session_id']}/messages"
            self.assertEqual(self.auth_request("POST", path, {"message": "안녕"})[0], 200)
            self.assertEqual(self.auth_request("POST", path, {"message": "안녕"})[0], 429)
        finally:
            self.app.rate_limiter = original

    def test_ui_contains_login_cart_agent_and_inert_checkout(self) -> None:
        status, html, _ = self.request("GET", "/agent-demo")
        self.assertEqual(status, 200)
        for value in ("loginForm", "registerForm", "promptInput", "cartDialog", "preferencesDialog"):
            self.assertIn(value, html)
        self.assertIn('id="checkoutButton"', html)
        self.assertIn("disabled", html)
        status, script, _ = self.request("GET", "/agent-static/app.js")
        self.assertEqual(status, 200)
        self.assertNotIn("/agent/v1/checkout", script)
        self.assertIn("디자인이 비슷한 상품", script)
        self.assertIn("촉감이 비슷한 상품", script)
        self.assertIn('"similar_product_click"', script)
        self.assertIn('result.action === "search_products"', script)


if __name__ == "__main__":
    unittest.main()
