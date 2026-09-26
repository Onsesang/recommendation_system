#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import mimetypes
import os
import traceback
import uuid
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from . import API_VERSION, PACKAGE_VERSION
from .auth import AuthService
from .config import AGENT_ROOT, AgentSettings
from .database import AgentDatabase
from .llm import build_llm_provider
from .tool_agent import TOOL_NAMES, build_tool_agent
from .personalization import PersonalizedRanker
from .rate_limit import RateLimited, RateLimiter, client_ip
from .preferences import PreferenceService
from .service import ShoppingAgentService
from .tools import ShoppingTools
from .tracing import TraceRecorder


MAX_BODY_BYTES = 256 * 1024
STATIC_ROOT = Path(__file__).resolve().parent / "static"
COOKIE_NAME = "shopping_agent_session"


def _int(query: dict[str, list[str]], name: str, default: int) -> int:
    try:
        return int(query.get(name, [str(default)])[0])
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc


def _openapi() -> dict[str, Any]:
    return {
        "openapi": "3.1.0",
        "info": {"title": "Personalized Shopping Agent API", "version": PACKAGE_VERSION},
        "servers": [{"url": "http://127.0.0.1:8878"}],
        "paths": {
            "/agent/v1/health": {"get": {"summary": "Agent and model health"}},
            "/agent/v1/auth/register": {"post": {"summary": "Register and sign in"}},
            "/agent/v1/auth/login": {"post": {"summary": "Sign in"}},
            "/agent/v1/auth/logout": {"post": {"summary": "Revoke current session"}},
            "/agent/v1/auth/me": {"get": {"summary": "Current user"}},
            "/agent/v1/products": {"get": {"summary": "Personalization-ready product catalog"}},
            "/agent/v1/products/{product_id}": {"get": {"summary": "Grounded product detail"}},
            "/agent/v1/sessions": {"post": {"summary": "Create shopping conversation"}},
            "/agent/v1/sessions/{session_id}": {"get": {"summary": "Conversation state and messages"}},
            "/agent/v1/sessions/{session_id}/messages": {"post": {"summary": "Run personalized shopping agent"}},
            "/agent/v1/events": {"post": {"summary": "Record an idempotent behavior event"}},
            "/agent/v1/preferences": {"get": {"summary": "List automatically learned preferences"}},
            "/agent/v1/preferences/{preference_id}": {
                "patch": {"summary": "Correct a preference"},
                "delete": {"summary": "Forget a preference"},
            },
            "/agent/v1/cart": {"get": {"summary": "Current user cart"}},
            "/agent/v1/cart/items": {"post": {"summary": "Add or update cart item"}},
            "/agent/v1/cart/items/{product_id}": {"delete": {"summary": "Remove cart item"}},
        },
    }


class AgentApplication:
    def __init__(self, settings: AgentSettings) -> None:
        self.settings = settings
        self.database = AgentDatabase(settings.database_path)
        auth_config = settings.config["auth"]
        self.auth = AuthService(
            self.database,
            password_min_length=int(auth_config["password_min_length"]),
            iterations=int(auth_config["pbkdf2_iterations"]),
            session_days=settings.session_days,
        )
        if settings.catalog_mode == "full":
            from .full_catalog import FullCatalogTools

            self.tools = FullCatalogTools()
        else:
            self.tools = ShoppingTools()
        self.preferences = PreferenceService(self.database)
        limits = dict(settings.config.get("rate_limits", {}))
        self.trusted_proxies = set(limits.pop("trusted_proxies", []))
        self.rate_limiter = RateLimiter(limits)
        self.ranker = PersonalizedRanker(self.database, self.tools, settings.config)
        self.llm = build_llm_provider(settings)
        self.tracer = TraceRecorder(
            AGENT_ROOT / "traces",
            project=settings.langsmith_project,
            langsmith_enabled=settings.langsmith_tracing,
        )
        self.agent = ShoppingAgentService(
            self.database,
            self.tools,
            self.preferences,
            self.ranker,
            self.llm,
            self.tracer,
            settings.config,
            tool_agent=build_tool_agent(settings),
        )

    def health(self) -> dict[str, Any]:
        return {
            "status": "ok",
            "service": "personalized-shopping-agent",
            "api_version": API_VERSION,
            "package_version": PACKAGE_VERSION,
            "llm": {
                "provider": self.llm.info.provider,
                "model": self.llm.info.model_id,
                "remote_configured": self.llm.info.provider != "deterministic",
            },
            "tracing": {
                "trace_id_enabled": True,
                "local_jsonl": True,
                "langsmith_ready": True,
                "langsmith_export_configured": self.settings.langsmith_tracing,
                "langsmith_export_active": False,
                "project": self.settings.langsmith_project,
            },
            "features": {
                "login": True,
                "automatic_chat_preferences": True,
                "conversation_tool_routing": True,
                "conversation_tools": list(self.agent.conversation_tools.names),
                "agent_mode": "openai_tool_loop" if self.agent.tool_agent else "router_pipeline",
                "agent_tools": sorted(TOOL_NAMES) if self.agent.tool_agent else [],
                "behavior_personalization": True,
                "cart": True,
                "checkout": False,
                "catalog_mode": self.settings.catalog_mode,
            },
            **self.tools.health(),
        }


def make_handler(app: AgentApplication):
    class Handler(BaseHTTPRequestHandler):
        server_version = f"PersonalizedShoppingAgent/{PACKAGE_VERSION}"

        def _headers(self, content_type: str, length: int, extra: dict[str, str] | None = None) -> None:
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(length))
            origin = (self.headers.get("Origin") or "").rstrip("/")
            if origin and origin in app.settings.cors_origins:
                # Echo only a registered origin; other sites get no CORS grant at all.
                self.send_header("Access-Control-Allow-Origin", origin)
                self.send_header("Access-Control-Allow-Credentials", "true")
                if (self.headers.get("Access-Control-Request-Private-Network") or "").casefold() == "true":
                    # A device on the tailnet resolves the Funnel host to a 100.x address, which Chrome
                    # treats as a private network and preflights with this header.
                    self.send_header("Access-Control-Allow-Private-Network", "true")
            self.send_header("Vary", "Origin")
            self.send_header("Access-Control-Expose-Headers", "Retry-After")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, PATCH, DELETE, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
            self.send_header("Cache-Control", "no-store")
            for key, value in (extra or {}).items():
                self.send_header(key, value)

        def _json(self, status: HTTPStatus, payload: Any, extra: dict[str, str] | None = None) -> None:
            body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            self.send_response(status)
            self._headers("application/json; charset=utf-8", len(body), extra)
            self.end_headers()
            self.wfile.write(body)

        def _error(self, status: HTTPStatus, code: str, message: str) -> None:
            self._json(status, {"error": {"code": code, "message": message}})

        def _body(self) -> dict[str, Any]:
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError as exc:
                raise ValueError("Invalid Content-Length") from exc
            if length <= 0 or length > MAX_BODY_BYTES:
                raise ValueError(f"JSON body must be between 1 and {MAX_BODY_BYTES} bytes")
            if "application/json" not in self.headers.get("Content-Type", ""):
                raise ValueError("Content-Type must be application/json")
            try:
                value = json.loads(self.rfile.read(length))
            except json.JSONDecodeError as exc:
                raise ValueError("Body must be valid JSON") from exc
            if not isinstance(value, dict):
                raise ValueError("JSON body must be an object")
            return value

        def _token(self) -> str | None:
            authorization = self.headers.get("Authorization", "")
            if authorization.startswith("Bearer "):
                return authorization[7:].strip()
            cookie = SimpleCookie(self.headers.get("Cookie", ""))
            morsel = cookie.get(COOKIE_NAME)
            return morsel.value if morsel else None

        def _user(self) -> dict[str, Any]:
            return app.auth.authenticate(self._token())

        @staticmethod
        def _login_payload(result: Any) -> dict[str, Any]:
            return {
                "status": "authenticated",
                "user": result.user,
                "access_token": result.token,
                "token_type": "Bearer",
                "expires_at": result.expires_at,
            }

        @staticmethod
        def _cookie(token: str, max_age: int) -> str:
            secure = "; Secure" if os.getenv("SHOPPING_AGENT_COOKIE_SECURE", "false").casefold() in {"1", "true", "yes"} else ""
            return f"{COOKIE_NAME}={token}; Path=/; Max-Age={max_age}; HttpOnly; SameSite=Strict{secure}"

        def _authenticated(self, callback: Any) -> None:
            user = self._user()
            callback(user)

        def _client_ip(self) -> str:
            return client_ip(self.client_address[0], self.headers, app.trusted_proxies)

        def _route_error(self, exc: Exception) -> None:
            if isinstance(exc, RateLimited):
                self._json(
                    HTTPStatus.TOO_MANY_REQUESTS,
                    {"error": {"code": "too_many_requests", "message": str(exc)}},
                    {"Retry-After": str(exc.retry_after)},
                )
            elif isinstance(exc, PermissionError):
                self._error(HTTPStatus.UNAUTHORIZED, "unauthorized", str(exc))
            elif isinstance(exc, KeyError):
                self._error(HTTPStatus.NOT_FOUND, "not_found", str(exc).strip("'"))
            elif isinstance(exc, ValueError):
                self._error(HTTPStatus.BAD_REQUEST, "invalid_request", str(exc))
            else:
                traceback.print_exc()
                self._error(HTTPStatus.INTERNAL_SERVER_ERROR, "internal_error", "서버에서 요청을 처리하지 못했습니다.")

        def do_OPTIONS(self) -> None:
            self.send_response(HTTPStatus.NO_CONTENT)
            self._headers("text/plain", 0)
            self.end_headers()

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            path = unquote(parsed.path)
            query = parse_qs(parsed.query)
            try:
                if path in {"/", "/agent-demo", "/agent-demo/"}:
                    self._static("index.html")
                elif path in {"/agent-static/app.css", "/agent-static/app.js"}:
                    self._static(path.rsplit("/", 1)[-1])
                elif path.startswith("/images/"):
                    self._image(path)
                elif path == "/agent/v1/health":
                    self._json(HTTPStatus.OK, app.health())
                elif path == "/agent/v1/openapi.json":
                    self._json(HTTPStatus.OK, _openapi())
                elif path == "/agent/v1/auth/me":
                    self._json(HTTPStatus.OK, {"user": self._user()})
                elif path == "/agent/v1/products":
                    self._user()
                    self._json(
                        HTTPStatus.OK,
                        app.tools.list_products(
                            page=_int(query, "page", 1),
                            page_size=_int(query, "page_size", 30),
                        ),
                    )
                elif path.startswith("/agent/v1/products/"):
                    self._user()
                    product_id = path.removeprefix("/agent/v1/products/")
                    self._json(HTTPStatus.OK, app.tools.tactile.product_detail(product_id))
                elif path == "/agent/v1/preferences":
                    user = self._user()
                    self._json(
                        HTTPStatus.OK,
                        {"items": app.database.list_preferences(user["user_id"]), "auto_save": True},
                    )
                elif path == "/agent/v1/cart":
                    user = self._user()
                    items = []
                    for row in app.database.list_cart(user["user_id"]):
                        items.append({**row, "product": app.tools.public_product(row["product_id"])})
                    self._json(HTTPStatus.OK, {"items": items, "checkout_enabled": False})
                elif path.startswith("/agent/v1/sessions/"):
                    user = self._user()
                    session_id = path.removeprefix("/agent/v1/sessions/")
                    if "/" in session_id:
                        raise KeyError("Route not found")
                    self._json(HTTPStatus.OK, app.agent.session(user["user_id"], session_id))
                else:
                    raise KeyError("Route not found")
            except Exception as exc:
                self._route_error(exc)

        def do_POST(self) -> None:
            path = urlparse(self.path).path
            try:
                if path == "/agent/v1/auth/register":
                    app.rate_limiter.check("register", self._client_ip())
                    body = self._body()
                    result = app.auth.register(
                        email=body.get("email", ""),
                        password=body.get("password", ""),
                        display_name=body.get("display_name", ""),
                    )
                    self._json(
                        HTTPStatus.CREATED,
                        self._login_payload(result),
                        {"Set-Cookie": self._cookie(result.token, app.settings.session_days * 86400)},
                    )
                    return
                if path == "/agent/v1/auth/login":
                    app.rate_limiter.check("login", self._client_ip())
                    body = self._body()
                    result = app.auth.login(email=body.get("email", ""), password=body.get("password", ""))
                    self._json(
                        HTTPStatus.OK,
                        self._login_payload(result),
                        {"Set-Cookie": self._cookie(result.token, app.settings.session_days * 86400)},
                    )
                    return
                if path == "/agent/v1/auth/logout":
                    app.auth.logout(self._token())
                    self._json(
                        HTTPStatus.OK,
                        {"status": "logged_out"},
                        {"Set-Cookie": self._cookie("", 0)},
                    )
                    return
                user = self._user()
                if path == "/agent/v1/sessions":
                    self._json(HTTPStatus.CREATED, app.agent.create_session(user["user_id"]))
                elif path.startswith("/agent/v1/sessions/") and path.endswith("/messages"):
                    session_id = path.removeprefix("/agent/v1/sessions/").removesuffix("/messages")
                    # Each message costs OpenAI calls; cap bursts and daily volume per user.
                    app.rate_limiter.check("messages", user["user_id"])
                    app.rate_limiter.check("messages_daily", user["user_id"])
                    body = self._body()
                    self._json(
                        HTTPStatus.OK,
                        app.agent.message(
                            user["user_id"], session_id, body.get("message", ""), limit=body.get("limit")
                        ),
                    )
                elif path == "/agent/v1/events":
                    body = self._body()
                    event_type = str(body.get("event_type") or "")
                    product_id = str(body.get("product_id") or "")
                    if event_type not in app.settings.config["events"]["allowed"]:
                        raise ValueError("Unsupported event_type")
                    if not app.tools.product_exists(product_id):
                        raise KeyError(f"Unknown product_id: {product_id}")
                    context = body.get("context") or {}
                    if not isinstance(context, dict):
                        raise ValueError("context must be an object")
                    if event_type == "product_dwell":
                        dwell = int(context.get("dwell_ms", 0))
                        if not 0 <= dwell <= 300000:
                            raise ValueError("dwell_ms must be between 0 and 300000")
                    event_id = str(body.get("event_id") or f"evt_{uuid.uuid4().hex}")
                    created = app.database.record_event(
                        user["user_id"],
                        event_id=event_id,
                        event_type=event_type,
                        product_id=product_id,
                        session_id=body.get("session_id"),
                        context=context,
                    )
                    self._json(HTTPStatus.CREATED if created else HTTPStatus.OK, {"event_id": event_id, "created": created})
                elif path == "/agent/v1/cart/items":
                    body = self._body()
                    product_id = str(body.get("product_id") or "")
                    quantity = int(body.get("quantity", 1))
                    if not app.tools.product_exists(product_id):
                        raise KeyError(f"Unknown product_id: {product_id}")
                    if not 1 <= quantity <= 20:
                        raise ValueError("quantity must be between 1 and 20")
                    app.database.add_cart_item(user["user_id"], product_id, quantity)
                    event_id = f"evt_{uuid.uuid4().hex}"
                    app.database.record_event(
                        user["user_id"], event_id=event_id, event_type="cart_add",
                        product_id=product_id, session_id=body.get("session_id"), context={"quantity": quantity}
                    )
                    self._json(HTTPStatus.CREATED, {"status": "added", "product_id": product_id, "quantity": quantity})
                else:
                    raise KeyError("Route not found")
            except Exception as exc:
                self._route_error(exc)

        def do_PATCH(self) -> None:
            path = urlparse(self.path).path
            try:
                user = self._user()
                if not path.startswith("/agent/v1/preferences/"):
                    raise KeyError("Route not found")
                preference_id = path.removeprefix("/agent/v1/preferences/")
                body = self._body()
                for name in ("strength", "confidence"):
                    if name in body and not 0 <= float(body[name]) <= 1:
                        raise ValueError(f"{name} must be between 0 and 1")
                if "direction" in body and body["direction"] not in {"more", "less", "avoid", "must_have"}:
                    raise ValueError("Unsupported direction")
                self._json(
                    HTTPStatus.OK,
                    app.database.update_preference(user["user_id"], preference_id, body),
                )
            except Exception as exc:
                self._route_error(exc)

        def do_DELETE(self) -> None:
            path = urlparse(self.path).path
            try:
                user = self._user()
                if path.startswith("/agent/v1/preferences/"):
                    preference_id = path.removeprefix("/agent/v1/preferences/")
                    app.database.delete_preference(user["user_id"], preference_id)
                    self._json(HTTPStatus.OK, {"status": "forgotten", "preference_id": preference_id})
                elif path.startswith("/agent/v1/cart/items/"):
                    product_id = path.removeprefix("/agent/v1/cart/items/")
                    if not app.database.remove_cart_item(user["user_id"], product_id):
                        raise KeyError("Cart item not found")
                    app.database.record_event(
                        user["user_id"], event_id=f"evt_{uuid.uuid4().hex}", event_type="cart_remove",
                        product_id=product_id, session_id=None, context={}
                    )
                    self._json(HTTPStatus.OK, {"status": "removed", "product_id": product_id})
                else:
                    raise KeyError("Route not found")
            except Exception as exc:
                self._route_error(exc)

        def _static(self, filename: str) -> None:
            path = STATIC_ROOT / filename
            if not path.is_file():
                raise KeyError("Static file not found")
            body = path.read_bytes()
            content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            if content_type.startswith("text/") or filename.endswith(".js"):
                content_type += "; charset=utf-8"
            self.send_response(HTTPStatus.OK)
            self._headers(content_type, len(body))
            self.end_headers()
            self.wfile.write(body)

        def _image(self, path: str) -> None:
            product_id = Path(path).stem
            image = app.tools.legacy_store.image_path(product_id)
            body = image.read_bytes()
            self.send_response(HTTPStatus.OK)
            self._headers(mimetypes.guess_type(image.name)[0] or "image/jpeg", len(body))
            self.end_headers()
            self.wfile.write(body)

    return Handler


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Personalized shopping agent v1")
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--database", type=Path, default=None)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    settings = AgentSettings.load()
    if args.database is not None:
        settings = AgentSettings(**{**settings.__dict__, "database_path": args.database})
    host = args.host or settings.host
    port = args.port or settings.port
    app = AgentApplication(settings)
    server = ThreadingHTTPServer((host, port), make_handler(app))
    print(
        f"Shopping Agent v1 listening on http://{host}:{port}/agent-demo "
        f"({len(app.tools.catalog.catalog_asins)} products, llm={app.llm.info.provider})",
        flush=True,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
