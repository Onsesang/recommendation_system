from __future__ import annotations

import json
import threading
import unittest
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer

from recommendation_api.server import make_handler
from recommendation_api.store import RecommendationStore
from recommendation_api.tactile_store import TactileStore


class TactileStoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.store = TactileStore()

    def test_health_and_target_contract(self) -> None:
        health = self.store.health()
        self.assertEqual(health["source_products"], 500)
        self.assertEqual(health["profile_products"], 495)
        self.assertEqual(health["accepted_claims"], 4527)
        self.assertEqual(health["target_dimension"], 384)

    def test_profile_is_grounded_and_private_reviewer_is_omitted(self) -> None:
        asin = next(asin for asin in self.store.source_asins if self.store.claims_by_asin.get(asin))
        profile = self.store.profile(asin)
        self.assertEqual(profile["status"], "available")
        self.assertTrue(profile["claims"])
        self.assertNotIn("reviewer_id", profile["claims"][0])
        self.assertTrue(profile["claims"][0]["original_span"])

    def test_five_products_have_explicit_empty_state(self) -> None:
        empty = [
            asin
            for asin in self.store.source_asins
            if self.store.profile(asin, include_claims=False)["status"]
            == "insufficient_evidence"
        ]
        self.assertEqual(
            empty,
            ["B000Y0JDU4", "B00681PVHC", "B0140VPCKC", "B017GPFFHO", "B01CZT4XJC"],
        )
        self.assertIsNone(self.store.profile(empty[0])["embedding_ref"])

    def test_unknown_product_and_pagination_validation(self) -> None:
        with self.assertRaises(KeyError):
            self.store.profile("B000000000")
        with self.assertRaises(ValueError):
            self.store.list_products(limit=0)


class TactileApiIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tactile = TactileStore()
        cls.server = ThreadingHTTPServer(
            ("127.0.0.1", 0),
            make_handler(RecommendationStore(), tactile_store=cls.tactile),
        )
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.port = cls.server.server_address[1]

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)

    def get(self, path: str) -> tuple[int, dict]:
        connection = HTTPConnection("127.0.0.1", self.port, timeout=5)
        connection.request("GET", path)
        response = connection.getresponse()
        payload = json.loads(response.read())
        connection.close()
        return response.status, payload

    def get_text(self, path: str) -> tuple[int, str, str]:
        connection = HTTPConnection("127.0.0.1", self.port, timeout=5)
        connection.request("GET", path)
        response = connection.getresponse()
        body = response.read().decode("utf-8")
        content_type = response.getheader("Content-Type") or ""
        connection.close()
        return response.status, content_type, body

    def post(self, path: str, payload: dict) -> tuple[int, dict]:
        connection = HTTPConnection("127.0.0.1", self.port, timeout=5)
        body = json.dumps(payload)
        connection.request(
            "POST", path, body=body, headers={"Content-Type": "application/json"}
        )
        response = connection.getresponse()
        result = json.loads(response.read())
        connection.close()
        return response.status, result

    def test_health_catalog_and_profile_routes(self) -> None:
        status, health = self.get("/v1/tactile/health")
        self.assertEqual(status, 200)
        self.assertEqual(health["profile_products"], 495)
        status, catalog = self.get("/v1/products?limit=2")
        self.assertEqual((status, len(catalog["items"])), (200, 2))
        asin = catalog["items"][0]["product_id"]
        status, profile = self.get(f"/v1/products/{asin}/tactile?include_claims=false")
        self.assertEqual(status, 200)
        self.assertNotIn("claims", profile)
        status, evaluation = self.get("/v1/tactile/evaluation")
        self.assertEqual(status, 200)
        self.assertEqual(evaluation["status"], "complete")
        self.assertEqual(evaluation["recommendation"]["cases"], 332)

    def test_paginated_catalog_natural_search_and_related_routes(self) -> None:
        status, catalog = self.get("/v1/products?page=1&page_size=30")
        self.assertEqual(status, 200)
        self.assertEqual(len(catalog["items"]), 30)
        self.assertEqual(catalog["total"], 465)
        self.assertEqual(catalog["total_pages"], 16)
        self.assertTrue(all(row["image_url"] and row["title"] for row in catalog["items"]))
        self.assertTrue(all(row["tactile_target_source"] for row in catalog["items"]))

        status, search = self.post(
            "/v1/products/search",
            {
                "query_text": "세탁 후 잘 늘어나지 않는 치마를 찾아줘.",
                "page": 1,
                "page_size": 30,
            },
        )
        self.assertEqual(status, 200)
        self.assertEqual(search["intent"]["category"], "skirt")
        self.assertIn("stretchiness", search["intent"]["desired_less"])
        self.assertTrue(search["items"])
        self.assertTrue(all(row["category"] == "skirt" for row in search["items"]))

        anchor = self.tactile.target_asins[0]
        status, related = self.get(f"/v1/products/{anchor}/related?limit=6")
        self.assertEqual(status, 200)
        self.assertEqual(len(related["design_similar"]), 6)
        self.assertEqual(len(related["tactile_similar"]), 6)
        self.assertEqual(
            related["design_similar"][0]["method"],
            "same_category_fashionclip_image_plus_title",
        )
        self.assertIn("score_breakdown", related["design_similar"][0])
        self.assertIn("target_source", related["tactile_similar"][0])
        self.assertIn("score_breakdown", related["tactile_similar"][0])
        self.assertNotIn(anchor, [row["product_id"] for row in related["design_similar"]])

    def test_multimodal_health_and_locked_evaluation_routes(self) -> None:
        status, health = self.get("/v1/multimodal/health")
        self.assertEqual(status, 200)
        self.assertEqual(health["catalog_products"], 465)
        self.assertEqual(health["design_embedding"]["coverage"], 1.0)
        self.assertEqual(
            health["tactile_target"]["source_counts"]["image_predicted"], 4
        )
        status, evaluation = self.get("/v1/multimodal/evaluation")
        self.assertEqual(status, 200)
        self.assertEqual(evaluation["selected_model"], "ridge")
        self.assertTrue(
            evaluation["ridge_improves_over_category_and_raw_image_retrieval"]
        )

    def test_unknown_product_returns_structured_404(self) -> None:
        status, payload = self.get("/v1/products/B000000000/tactile")
        self.assertEqual(status, 404)
        self.assertEqual(payload["error"]["code"], "not_found")

    def test_tactile_summary_route_is_grounded(self) -> None:
        asin = next(
            asin for asin in self.tactile.source_asins if self.tactile.claims_by_asin.get(asin)
        )
        status, payload = self.get(f"/v1/products/{asin}/tactile-summary")
        self.assertEqual(status, 200)
        self.assertEqual(payload["status"], "available")
        self.assertTrue(payload["summary"])
        self.assertTrue(payload["summary"][0]["evidence_details"])
        self.assertNotIn("reviewer_id", str(payload))

    def test_tactile_compare_post_route(self) -> None:
        product_ids = self.tactile.target_asins[:2]
        status, payload = self.post(
            "/v1/products/tactile-compare", {"product_ids": product_ids}
        )
        self.assertEqual(status, 200)
        self.assertEqual(payload["products"], product_ids)
        self.assertNotIn("medium", str(payload).casefold())
        self.assertNotIn("reviewer_id", str(payload))

    def test_tactile_concerns_route_is_grounded_and_actionable(self) -> None:
        from recommendation_api.tactile_concerns import TactileConcernDetector

        detector = TactileConcernDetector(self.tactile)
        asin = next(
            asin
            for asin in self.tactile.source_asins
            if detector.detect(asin)["concerns"]
        )
        status, payload = self.get(f"/v1/products/{asin}/tactile-concerns")
        self.assertEqual(status, 200)
        self.assertTrue(payload["concerns"])
        concern = payload["concerns"][0]
        self.assertGreaterEqual(concern["reviewer_count"], 2)
        self.assertTrue(concern["evidence"])
        self.assertEqual(concern["alternative_action"]["type"], "tactile_alternatives")
        self.assertNotIn("reviewer_id", str(payload))

    def test_tactile_alternative_route_has_breakdown_and_same_category(self) -> None:
        from recommendation_api.tactile_ranking import TactileRankingService

        ranking = TactileRankingService(self.tactile)
        anchor = next(
            asin
            for asin in self.tactile.source_asins
            if ranking.concept_signal(asin, "scratchy")
            and ranking.alternatives(
                anchor_product_id=asin,
                direction="less",
                tactile_concept="scratchy",
                top_k=1,
            )["results"]
        )
        status, payload = self.post(
            "/v1/recommendations/tactile-alternatives",
            {
                "anchor_product_id": anchor,
                "direction": "less",
                "tactile_concept": "scratchy",
                "top_k": 3,
            },
        )
        self.assertEqual(status, 200)
        self.assertTrue(payload["results"])
        category = self.tactile.product_metadata[anchor]["category"]
        self.assertTrue(all(row["category"] == category for row in payload["results"]))
        self.assertIn("tactile_improvement", payload["results"][0]["score_breakdown"])
        self.assertTrue(payload["results"][0]["reason"]["evidence"])

    def test_tactile_rerank_route_exposes_gate_and_score_breakdown(self) -> None:
        category = self.tactile.product_metadata[self.tactile.target_asins[0]]["category"]
        candidates = [
            {"product_id": asin, "base_score": score}
            for asin, score in zip(self.tactile.target_asins[:6], [0.9, 0.8, 0.7, 0.6, 0.5, 0.4])
        ]
        status, payload = self.post(
            "/v1/recommendations/tactile-rerank",
            {
                "candidates": candidates,
                "strategy": "context_gated",
                "intent": {"category": category, "desired_more": ["soft"]},
                "top_k": 4,
            },
        )
        self.assertEqual(status, 200)
        self.assertEqual(payload["strategy"], "context_gated")
        self.assertEqual(len(payload["results"]), 4)
        breakdown = payload["results"][0]["score_breakdown"]
        self.assertIn("tactile_gate", breakdown)
        self.assertIn("conflict_penalty", breakdown)
        self.assertIn("diversity_score", breakdown)

    def test_tactile_rerank_rejects_malformed_intent(self) -> None:
        status, payload = self.post(
            "/v1/recommendations/tactile-rerank",
            {
                "candidates": [
                    {"product_id": self.tactile.target_asins[0], "base_score": 1.0}
                ],
                "intent": {"avoid": "sheer"},
            },
        )
        self.assertEqual(status, 400)
        self.assertEqual(payload["error"]["code"], "invalid_request")

    def test_tactile_intent_and_agent_routes(self) -> None:
        status, intent = self.post(
            "/v1/tactile/intent",
            {"query_text": "얇은 바지지만 비치는 건 싫어"},
        )
        self.assertEqual(status, 200)
        self.assertEqual(intent["category"], "pants")
        self.assertIn("thinness", intent["desired_more"])
        self.assertIn("sheerness", intent["avoid"])

        status, agent = self.post(
            "/v1/tactile/agent",
            {"message": "부드럽고 비치지 않는 바지를 찾아줘", "top_k": 3},
        )
        self.assertEqual(status, 200)
        self.assertEqual(agent["status"], "complete")
        self.assertEqual(len(agent["results"]), 3)
        self.assertTrue(
            all(row["product_id"] in self.tactile.product_metadata for row in agent["results"])
        )
        self.assertFalse(agent["retrieval"]["invented_product_allowed"])

    def test_integrated_demo_and_static_assets(self) -> None:
        status, content_type, html = self.get_text("/tactile-demo")
        self.assertEqual(status, 200)
        self.assertIn("text/html", content_type)
        for label in (
            "모든 상품",
            "구매자들이 말하는 소재",
            "소재 관련 의견",
            "디자인이 비슷한 상품",
            "촉감이 비슷한 상품",
        ):
            self.assertIn(label, html)
        self.assertIn("promptInput", html)
        status, content_type, script = self.get_text("/tactile-static/app.js")
        self.assertEqual(status, 200)
        self.assertIn("javascript", content_type)
        for endpoint in (
            "/v1/products?page=",
            "/v1/products/search",
            "/related?limit=",
            "/tactile-summary",
            "/tactile-concerns",
            "/v1/recommendations/tactile-alternatives",
        ):
            self.assertIn(endpoint, script)
        self.assertIn("FashionCLIP 이미지", script)
        self.assertIn("이미지 기반 촉감 예상", script)


if __name__ == "__main__":
    unittest.main()
