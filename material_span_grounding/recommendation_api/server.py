#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import mimetypes
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from .store import RecommendationStore
from .tactile_agent import TactileAgentService, intent_from_mapping, parse_tactile_intent
from .tactile_catalog import TactileCatalogService
from .tactile_comparison import TactileComparisonService
from .tactile_concerns import TactileConcernDetector
from .tactile_description import TactileDescriptionService
from .tactile_models import TactileIntent
from .tactile_ranking import TactileRankingService
from .tactile_store import TactileStore


MAX_BODY_BYTES = 128 * 1024
STATIC_ROOT = Path(__file__).resolve().parent / "static"
TACTILE_EVALUATION = (
    Path(__file__).resolve().parents[1]
    / "data/recommendation_eval/tactile_v1/metrics.json"
)


def _integer(query: dict[str, list[str]], name: str, default: int) -> int:
    try:
        return int(query.get(name, [str(default)])[0])
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc


def _boolean(query: dict[str, list[str]], name: str, default: bool = False) -> bool:
    value = query.get(name, [str(default)])[0].casefold()
    if value in {"1", "true", "yes"}:
        return True
    if value in {"0", "false", "no"}:
        return False
    raise ValueError(f"{name} must be true or false")


def make_handler(
    store: RecommendationStore,
    cors_origin: str = "*",
    tactile_store: TactileStore | None = None,
):
    tactile_catalog = (
        TactileCatalogService(tactile_store, image_root=store.image_root)
        if tactile_store
        else None
    )

    class RecommendationHandler(BaseHTTPRequestHandler):
        server_version = "MaterialRecommendationAPI/1.0"

        def log_message(self, format: str, *args: Any) -> None:
            super().log_message(format, *args)

        def _headers(self, content_type: str, length: int) -> None:
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(length))
            self.send_header("Access-Control-Allow-Origin", cors_origin)
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Cache-Control", "no-store")

        def _json(self, status: HTTPStatus, payload: Any) -> None:
            body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode(
                "utf-8"
            )
            self.send_response(status)
            self._headers("application/json; charset=utf-8", len(body))
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
                payload = json.loads(self.rfile.read(length))
            except json.JSONDecodeError as exc:
                raise ValueError("Body must be valid JSON") from exc
            if not isinstance(payload, dict):
                raise ValueError("JSON body must be an object")
            return payload

        def do_OPTIONS(self) -> None:
            self.send_response(HTTPStatus.NO_CONTENT)
            self._headers("text/plain", 0)
            self.end_headers()

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            path = unquote(parsed.path)
            query = parse_qs(parsed.query)
            try:
                if path in {"/", "/api"}:
                    self._json(
                        HTTPStatus.OK,
                        {
                            "service": "material-recommendation-api",
                            "version": "1.0",
                            "docs": "/docs",
                            "health": "/api/health",
                        },
                    )
                elif path == "/api/health":
                    health = store.health()
                    if tactile_store is not None:
                        health["tactile"] = tactile_store.health()
                    self._json(HTTPStatus.OK, health)
                elif path == "/v1/tactile/health":
                    if tactile_store is None:
                        raise LookupError("Tactile backend is unavailable")
                    self._json(HTTPStatus.OK, tactile_store.health())
                elif path == "/v1/tactile/evaluation":
                    if not TACTILE_EVALUATION.is_file():
                        raise KeyError("Tactile evaluation has not been generated")
                    self._json(
                        HTTPStatus.OK,
                        json.loads(TACTILE_EVALUATION.read_text(encoding="utf-8")),
                    )
                elif path == "/v1/multimodal/health":
                    if tactile_catalog is None:
                        raise LookupError("Multimodal backend is unavailable")
                    self._json(HTTPStatus.OK, tactile_catalog.multimodal_health())
                elif path == "/v1/multimodal/evaluation":
                    if tactile_catalog is None:
                        raise LookupError("Multimodal backend is unavailable")
                    self._json(HTTPStatus.OK, tactile_catalog.multimodal_evaluation())
                elif path == "/v1/products":
                    if tactile_catalog is None:
                        raise LookupError("Tactile backend is unavailable")
                    if "offset" in query or "limit" in query:
                        self._json(
                            HTTPStatus.OK,
                            tactile_store.list_products(
                                offset=_integer(query, "offset", 0),
                                limit=_integer(query, "limit", 50),
                            ),
                        )
                    else:
                        self._json(
                            HTTPStatus.OK,
                            tactile_catalog.catalog(
                                page=_integer(query, "page", 1),
                                page_size=_integer(query, "page_size", 30),
                            ),
                        )
                elif path == "/api/stats":
                    self._json(HTTPStatus.OK, store.stats())
                elif path == "/api/evaluation":
                    self._json(HTTPStatus.OK, store.evaluation())
                elif path == "/api/evaluation/protocol":
                    self._json(HTTPStatus.OK, store.evaluation_protocol())
                elif path == "/api/products":
                    self._json(
                        HTTPStatus.OK,
                        store.list_products(
                            offset=_integer(query, "offset", 0),
                            limit=_integer(query, "limit", 50),
                            category=query.get("category", [None])[0],
                            min_users=_integer(query, "min_users", 0),
                        ),
                    )
                elif path.startswith("/api/products/"):
                    asin = path.removeprefix("/api/products/")
                    self._json(HTTPStatus.OK, store.product(asin))
                elif path.startswith("/v1/products/") and path.endswith("/tactile"):
                    if tactile_store is None:
                        raise LookupError("Tactile backend is unavailable")
                    asin = path.removeprefix("/v1/products/").removesuffix("/tactile")
                    self._json(
                        HTTPStatus.OK,
                        tactile_store.profile(
                            asin,
                            include_claims=_boolean(query, "include_claims", True),
                        ),
                    )
                elif path.startswith("/v1/products/") and path.endswith("/tactile-summary"):
                    if tactile_store is None:
                        raise LookupError("Tactile backend is unavailable")
                    asin = path.removeprefix("/v1/products/").removesuffix(
                        "/tactile-summary"
                    )
                    self._json(
                        HTTPStatus.OK,
                        TactileDescriptionService(tactile_store).describe(asin),
                    )
                elif path.startswith("/v1/products/") and path.endswith("/tactile-concerns"):
                    if tactile_store is None:
                        raise LookupError("Tactile backend is unavailable")
                    asin = path.removeprefix("/v1/products/").removesuffix(
                        "/tactile-concerns"
                    )
                    self._json(
                        HTTPStatus.OK,
                        TactileConcernDetector(tactile_store).detect(asin),
                    )
                elif path.startswith("/v1/products/") and path.endswith("/related"):
                    if tactile_catalog is None:
                        raise LookupError("Tactile backend is unavailable")
                    asin = path.removeprefix("/v1/products/").removesuffix("/related")
                    self._json(
                        HTTPStatus.OK,
                        tactile_catalog.related(
                            asin, limit=_integer(query, "limit", 10)
                        ),
                    )
                elif path == "/api/search":
                    asin = query.get("asin", [""])[0]
                    if not asin:
                        raise ValueError("asin is required")
                    self._json(
                        HTTPStatus.OK,
                        store.search_by_asin(
                            asin,
                            method=query.get("method", ["m1"])[0],
                            k=_integer(query, "k", 10),
                            same_category=_boolean(query, "same_category", False),
                            min_users=_integer(query, "min_users", 0),
                            include_evidence=_integer(query, "include_evidence", 3),
                        ),
                    )
                elif path.startswith("/images/"):
                    asin = Path(path).stem
                    image = store.image_path(asin)
                    body = image.read_bytes()
                    self.send_response(HTTPStatus.OK)
                    self._headers(mimetypes.guess_type(image.name)[0] or "image/jpeg", len(body))
                    self.send_header("Cache-Control", "public, max-age=86400")
                    self.end_headers()
                    self.wfile.write(body)
                elif path == "/docs":
                    body = DOCS_HTML.encode("utf-8")
                    self.send_response(HTTPStatus.OK)
                    self._headers("text/html; charset=utf-8", len(body))
                    self.end_headers()
                    self.wfile.write(body)
                elif path in {"/tactile-demo", "/tactile-demo/"}:
                    body = (STATIC_ROOT / "index.html").read_bytes()
                    self.send_response(HTTPStatus.OK)
                    self._headers("text/html; charset=utf-8", len(body))
                    self.end_headers()
                    self.wfile.write(body)
                elif path in {"/tactile-static/app.css", "/tactile-static/app.js"}:
                    filename = path.removeprefix("/tactile-static/")
                    body = (STATIC_ROOT / filename).read_bytes()
                    content_type = (
                        "text/css; charset=utf-8"
                        if filename.endswith(".css")
                        else "text/javascript; charset=utf-8"
                    )
                    self.send_response(HTTPStatus.OK)
                    self._headers(content_type, len(body))
                    self.send_header("Cache-Control", "public, max-age=300")
                    self.end_headers()
                    self.wfile.write(body)
                elif path == "/api/openapi.json":
                    self._json(HTTPStatus.OK, OPENAPI)
                else:
                    self._error(HTTPStatus.NOT_FOUND, "not_found", "Route not found")
            except KeyError as exc:
                self._error(HTTPStatus.NOT_FOUND, "not_found", str(exc).strip("'"))
            except LookupError as exc:
                self._error(HTTPStatus.NOT_FOUND, "feature_disabled", str(exc))
            except ValueError as exc:
                self._error(HTTPStatus.BAD_REQUEST, "invalid_request", str(exc))

        def do_POST(self) -> None:
            path = urlparse(self.path).path
            try:
                if path == "/v1/products/tactile-compare":
                    if tactile_store is None:
                        raise LookupError("Tactile backend is unavailable")
                    self._json(
                        HTTPStatus.OK,
                        TactileComparisonService(tactile_store).compare_request(
                            self._body()
                        ),
                    )
                    return
                if path == "/v1/products/search":
                    if tactile_catalog is None:
                        raise LookupError("Tactile backend is unavailable")
                    self._json(
                        HTTPStatus.OK,
                        tactile_catalog.search(self._body()),
                    )
                    return
                if path == "/v1/recommendations/tactile-alternatives":
                    if tactile_store is None:
                        raise LookupError("Tactile backend is unavailable")
                    payload = self._body()
                    if not payload.get("anchor_product_id"):
                        raise ValueError("anchor_product_id is required")
                    if not payload.get("direction"):
                        raise ValueError("direction is required")
                    if not payload.get("tactile_concept"):
                        raise ValueError("tactile_concept is required")
                    self._json(
                        HTTPStatus.OK,
                        TactileRankingService(tactile_store).alternatives(
                            anchor_product_id=str(payload["anchor_product_id"]),
                            direction=str(payload["direction"]),
                            tactile_concept=str(payload["tactile_concept"]),
                            top_k=int(payload.get("top_k", 10)),
                        ),
                    )
                    return
                if path == "/v1/recommendations/tactile-rerank":
                    if tactile_store is None:
                        raise LookupError("Tactile backend is unavailable")
                    payload = self._body()
                    candidates = payload.get("candidates")
                    if not isinstance(candidates, list):
                        raise ValueError("candidates must be an array")
                    intent_payload = payload.get("intent") or {}
                    if not isinstance(intent_payload, dict):
                        raise ValueError("intent must be an object")

                    def string_tuple(name: str) -> tuple[str, ...]:
                        value = intent_payload.get(name, [])
                        if not isinstance(value, list) or any(
                            not isinstance(item, str) or not item.strip() for item in value
                        ):
                            raise ValueError(f"intent.{name} must be an array of strings")
                        return tuple(item.strip() for item in value)

                    intent = TactileIntent(
                        current_product_id=(
                            str(intent_payload["current_product_id"])
                            if intent_payload.get("current_product_id")
                            else None
                        ),
                        category=(
                            str(intent_payload["category"])
                            if intent_payload.get("category")
                            else None
                        ),
                        query_text=(
                            str(intent_payload["query_text"])
                            if intent_payload.get("query_text")
                            else None
                        ),
                        desired_more=string_tuple("desired_more"),
                        desired_less=string_tuple("desired_less"),
                        avoid=string_tuple("avoid"),
                        must_have=string_tuple("must_have"),
                        source="explicit_structured",
                        confidence=1.0,
                    )
                    history = payload.get("history_product_ids", [])
                    if not isinstance(history, list) or any(
                        not isinstance(value, str) or not value.strip() for value in history
                    ):
                        raise ValueError("history_product_ids must be an array of strings")
                    self._json(
                        HTTPStatus.OK,
                        TactileRankingService(tactile_store).rerank(
                            candidates=candidates,
                            strategy=str(payload.get("strategy", "baseline")),
                            history_product_ids=[value.strip() for value in history],
                            intent=intent,
                            top_k=int(payload.get("top_k", 10)),
                        ),
                    )
                    return
                if path == "/v1/tactile/intent":
                    if tactile_store is None:
                        raise LookupError("Tactile backend is unavailable")
                    tactile_store.require_feature("tactile_agent")
                    payload = self._body()
                    intent = parse_tactile_intent(
                        payload.get("query_text") or payload.get("message") or "",
                        current_product_id=(
                            str(payload["current_product_id"])
                            if payload.get("current_product_id")
                            else None
                        ),
                        previous=intent_from_mapping(payload.get("previous_intent")),
                    )
                    self._json(HTTPStatus.OK, intent.public_dict())
                    return
                if path == "/v1/tactile/agent":
                    if tactile_store is None:
                        raise LookupError("Tactile backend is unavailable")
                    self._json(
                        HTTPStatus.OK,
                        TactileAgentService(tactile_store).handle(self._body()),
                    )
                    return
                if path != "/api/search":
                    self._error(HTTPStatus.NOT_FOUND, "not_found", "Route not found")
                    return
                payload = self._body()
                if "asin" in payload:
                    result = store.search_by_asin(
                        str(payload["asin"]),
                        method=str(payload.get("method", "m1")),
                        k=int(payload.get("k", 10)),
                        same_category=bool(payload.get("same_category", False)),
                        min_users=int(payload.get("min_users", 0)),
                        include_evidence=int(payload.get("include_evidence", 3)),
                    )
                elif "image_vector" in payload:
                    if not isinstance(payload["image_vector"], list):
                        raise ValueError("image_vector must be an array")
                    result = store.search_by_vector(
                        payload["image_vector"],
                        method=str(payload.get("method", "m1")),
                        k=int(payload.get("k", 10)),
                        category=payload.get("category"),
                        min_users=int(payload.get("min_users", 0)),
                        include_evidence=int(payload.get("include_evidence", 3)),
                    )
                else:
                    raise ValueError("Either asin or image_vector is required")
                self._json(HTTPStatus.OK, result)
            except KeyError as exc:
                self._error(HTTPStatus.NOT_FOUND, "not_found", str(exc).strip("'"))
            except LookupError as exc:
                self._error(HTTPStatus.NOT_FOUND, "feature_disabled", str(exc))
            except (TypeError, ValueError) as exc:
                self._error(HTTPStatus.BAD_REQUEST, "invalid_request", str(exc))

    return RecommendationHandler


DOCS_HTML = """<!doctype html><html lang=\"ko\"><head><meta charset=\"utf-8\">
<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">
<title>Material Recommendation API</title><style>
body{font:16px/1.55 system-ui;max-width:900px;margin:40px auto;padding:0 20px;color:#17201b}
code,pre{background:#f1f5f2;border-radius:6px}code{padding:2px 5px}pre{padding:16px;overflow:auto}
h1,h2{line-height:1.25}small{color:#59645e}.method{font-weight:700;color:#087443}
</style></head><body><h1>Material Recommendation API</h1>
<p>기존 M0/M1 검색과 495상품 review-grounded tactile backend를 함께 제공하는 읽기 전용 API입니다.</p>
<p><a href="/tactile-demo"><strong>통합 Tactile Demo 열기</strong></a></p>
<h2>Endpoints</h2><p><span class=method>GET</span> <code>/api/health</code></p>
<p><span class=method>GET</span> <code>/api/stats</code></p>
<p><span class=method>GET</span> <code>/api/evaluation</code></p>
<p><span class=method>GET</span> <code>/api/evaluation/protocol</code></p>
<p><span class=method>GET</span> <code>/api/products?limit=20&category=top</code></p>
<p><span class=method>GET</span> <code>/api/products/{asin}</code></p>
<p><span class=method>GET</span> <code>/api/search?asin={asin}&method=m1&k=10&same_category=true</code></p>
<p><span class=method>POST</span> <code>/api/search</code> — ASIN 또는 1152차원 Qwen image vector</p>
<h2>Tactile v1</h2>
<p><span class=method>GET</span> <code>/v1/tactile/health</code>, <code>/v1/tactile/evaluation</code></p>
<p><span class=method>GET</span> <code>/v1/multimodal/health</code>, <code>/v1/multimodal/evaluation</code></p>
<p><span class=method>GET</span> <code>/v1/products?page=1&amp;page_size=30</code></p>
<p><span class=method>POST</span> <code>/v1/products/search</code> — 자연어 상품 검색</p>
<p><span class=method>GET</span> <code>/v1/products/{asin}/tactile</code>, <code>/tactile-summary</code>, <code>/tactile-concerns</code>, <code>/related</code></p>
<p><span class=method>POST</span> <code>/v1/products/tactile-compare</code></p>
<p><span class=method>POST</span> <code>/v1/recommendations/tactile-alternatives</code>, <code>/tactile-rerank</code></p>
<p><span class=method>POST</span> <code>/v1/tactile/intent</code>, <code>/v1/tactile/agent</code></p>
<pre>{\n  \"asin\": \"B0010Z6RRY\",\n  \"method\": \"m1\",\n  \"k\": 5,\n  \"same_category\": true\n}</pre>
<p><small>M0는 동결 이미지 cosine, M1은 이미지에서 예측한 소재 벡터와 실제 리뷰 target의 cosine입니다. score는 보정된 확률이 아닙니다.</small></p>
<p>Machine-readable schema: <a href=\"/api/openapi.json\">/api/openapi.json</a></p>
</body></html>"""


OPENAPI = {
    "openapi": "3.0.3",
    "info": {"title": "Material Recommendation API", "version": "1.0.0"},
    "paths": {
        "/api/health": {"get": {"summary": "Service and index health"}},
        "/v1/tactile/health": {"get": {"summary": "Tactile artifact and feature health"}},
        "/v1/tactile/evaluation": {
            "get": {"summary": "Latest tactile system evaluation and limitations"}
        },
        "/v1/multimodal/health": {
            "get": {"summary": "FashionCLIP and hybrid tactile index health"}
        },
        "/v1/multimodal/evaluation": {
            "get": {"summary": "Locked cold-start image-to-tactile evaluation"}
        },
        "/v1/products": {"get": {"summary": "Tactile prototype product catalog"}},
        "/v1/products/search": {
            "post": {"summary": "Paginated natural-language product discovery"}
        },
        "/v1/products/{asin}/tactile": {
            "get": {"summary": "Grounded product tactile profile"}
        },
        "/v1/products/{asin}/tactile-summary": {
            "get": {"summary": "Reviewer-aware tactile description"}
        },
        "/v1/products/{asin}/tactile-concerns": {
            "get": {"summary": "Repeated review-grounded tactile concerns"}
        },
        "/v1/products/{asin}/related": {
            "get": {"summary": "Ranked design/style and tactile related products"}
        },
        "/v1/products/tactile-compare": {
            "post": {"summary": "Evidence-grounded comparison of two or more products"}
        },
        "/v1/recommendations/tactile-alternatives": {
            "post": {"summary": "Same-category alternative for an explicit tactile change"}
        },
        "/v1/recommendations/tactile-rerank": {
            "post": {"summary": "Configurable context-gated reranking of existing candidates"}
        },
        "/v1/tactile/intent": {
            "post": {"summary": "Deterministic natural-language tactile intent extraction"}
        },
        "/v1/tactile/agent": {
            "post": {"summary": "Natural-language facade over real tactile retrieval and ranking"}
        },
        "/tactile-demo": {"get": {"summary": "Integrated tactile recommendation demo UI"}},
        "/api/stats": {"get": {"summary": "Catalog and model statistics"}},
        "/api/evaluation": {"get": {"summary": "Latest offline ranking metrics"}},
        "/api/evaluation/protocol": {"get": {"summary": "Temporal evaluation protocol manifest"}},
        "/api/products": {"get": {"summary": "Paginated product catalog"}},
        "/api/products/{asin}": {"get": {"summary": "Product and accepted review evidence"}},
        "/api/search": {
            "get": {"summary": "Search by catalog ASIN"},
            "post": {"summary": "Search by ASIN or 1152-dimensional image vector"},
        },
    },
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Material recommendation backend")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8877)
    parser.add_argument("--image-root", type=Path, default=None)
    parser.add_argument("--cors-origin", default="*")
    parser.add_argument("--tactile-target-root", type=Path, default=None)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    kwargs = {"image_root": args.image_root} if args.image_root else {}
    store = RecommendationStore(**kwargs)
    tactile_kwargs = (
        {"target_root": args.tactile_target_root} if args.tactile_target_root else {}
    )
    tactile_store = TactileStore(**tactile_kwargs)
    server = ThreadingHTTPServer(
        (args.host, args.port), make_handler(store, args.cors_origin, tactile_store)
    )
    print(
        f"Material recommendation API listening on http://{args.host}:{args.port} "
        f"({len(store.products)} products)",
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
