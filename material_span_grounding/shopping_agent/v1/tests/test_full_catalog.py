from __future__ import annotations

import json
import re
import tempfile
import threading
import unittest
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path

import numpy as np
import pandas as pd

from recommendation_api.tactile_models import TactileIntent

from shopping_agent.v1.config import AgentSettings
from shopping_agent.v1.full_catalog import (
    CONCEPT_TO_LAST2,
    GENDER_MEN,
    GENDER_UNISEX,
    GENDER_UNKNOWN,
    GENDER_WOMEN,
    TACTILE_CLASSES,
    UNSUPPORTED_CONCEPTS,
    FullCatalogTools,
    GARMENT_CATEGORIES,
    _kids_titles,
    _title_genders,
    intent_terms,
    title_keywords,
)
from shopping_agent.v1.server import AgentApplication, make_handler


class FullCatalogToolsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tools = FullCatalogTools()

    def test_catalog_covers_the_whole_last2_cache(self) -> None:
        health = self.tools.health()
        self.assertEqual(health["catalog_mode"], "full")
        self.assertGreater(health["catalog_products"], 800_000)
        self.assertEqual(health["multimodal"]["tactile_target"]["classes"], len(TACTILE_CLASSES))

    def test_search_filters_to_the_parsed_category(self) -> None:
        payload = self.tools.tactile.search("부드러운 니트 추천해줘", limit=20)
        self.assertEqual(payload["category"], "sweater")
        self.assertTrue(payload["items"])
        self.assertLess(payload["total_candidates"], self.tools.health()["catalog_products"])
        for item in payload["items"]:
            self.assertEqual(item["category"], "sweater")

    def test_type_exclusion_drops_other_product_types_but_keeps_modifiers(self) -> None:
        index = self.tools.index

        def kept(category: str, titles: list[str]) -> list[bool]:
            rows = [index.row_of(asin) for asin in index.asins[:len(titles)]]
            original = index.lowered_titles.copy()
            try:
                for row, title in zip(rows, titles):
                    index.lowered_titles.iloc[row] = title.lower()
                index.config["retrieval"]["type_exclusion_min_candidates"] = 0
                survivors = set(index._drop_other_types(np.array(rows, dtype=np.int32), category).tolist())
            finally:
                index.lowered_titles = original
                index.config["retrieval"]["type_exclusion_min_candidates"] = 200
            return [row in survivors for row in rows]

        # Reviewed as wrong type in the 2026-09-26 recommendation review.
        self.assertEqual(kept("dress", ["Crew Socks Casual Dress Socks", "Lace Mask Masquerade Fancy Dress Masks",
                                        "Floral Wrap Midi Dress with Belt", "Cap Sleeve Summer Dress"]),
                         [False, False, True, True])
        self.assertEqual(kept("pants", ["Cotton Hipster Panties Comfortable Briefs", "Leather Belt for Jeans",
                                        "Jogger Pants with Belt Loops", "Wide Leg Pants with Belt"]),
                         [False, False, True, True])
        self.assertEqual(kept("coat", ["Heated Vest Jacket Sleeveless Coat", "Faux Fur Cowl Scarf Neck Warmer",
                                       "Wool Trench Coat with Belt"]), [False, False, True])
        self.assertEqual(kept("skirt", ["Chiffon Robe Beach Skirt Swimsuit Cover Up", "Pleated Midi Skirt"]), [False, True])
        self.assertEqual(kept("jeans", ["Gothic Yoga Leggings Tights Pants Jeans", "Denim Jeans Legging Curvy Fit",
                                        "Bootcut Stretch Jeans", "Boot Leg Jeans"]), [False, True, True, True])
        self.assertEqual(kept("sweater", ["Knit Hooded Scarf Pullover Hat", "Elbow Patch Cardigan Sweater",
                                          "Chain Stitch Crewneck Sweater"]), [False, True, True])
        self.assertEqual(kept("tshirt", ["Padded T-Shirt Bra Underwire", "Tank with Built-in Bra"]), [False, True])
        # Categories that are the excluded type keep them.
        self.assertEqual(kept("underwear", ["Cotton Hipster Panties"]), [True])

    def test_products_without_a_photo_are_skipped(self) -> None:
        index = self.tools.index
        placeholder = int((~index.has_image).sum())
        self.assertGreater(placeholder, 10_000)  # Amazon's shared "no image" GIF
        listing = self.tools.list_products(page=1, page_size=100)
        # The list shows adult clothing only (AgeAndBrowseTests), and never a photo-less listing.
        self.assertTrue(index.has_image[index.browse_rows()].all())
        self.assertLessEqual(listing["total"], len(index.asins) - placeholder)
        self.assertFalse(any(item["remote_image_url"].endswith(".gif") for item in listing["items"]))
        for category in (None, "pants", "dress"):
            rows, _ = index.candidate_rows(category)
            self.assertTrue(index.has_image[rows].all())

    def test_search_results_are_deduplicated_by_product_family(self) -> None:
        payload = self.tools.tactile.search("검정색 신축성 있는 바지", limit=25)
        titles = [item["title"] for item in payload["items"]]
        self.assertEqual(len(titles), len(set(titles)))

    def test_negated_term_prefers_low_probability_items(self) -> None:
        """Relevance also carries popularity, so check the direction, not a strict sort."""
        negated = self.tools.tactile.search("까슬거리지 않는 니트", limit=30)
        wanted = self.tools.tactile.search("까슬한 니트", limit=30)
        negated_mean = sum(i["last2_predictions"]["rough"] for i in negated["items"]) / 30
        wanted_mean = sum(i["last2_predictions"]["rough"] for i in wanted["items"]) / 30
        self.assertLess(negated_mean, wanted_mean)

    def test_every_item_exposes_a_score_breakdown(self) -> None:
        payload = self.tools.tactile.search("두껍고 따뜻한 자켓", limit=5)
        for item in payload["items"]:
            breakdown = item["score_breakdown"]
            self.assertIn("relevance_inputs", breakdown)
            self.assertIn("tactile_terms", breakdown)
            self.assertIn("evidence_source", breakdown)
            self.assertAlmostEqual(sum(breakdown["relevance_weights"].values()), 1.0, places=6)

    def test_weights_only_count_components_the_query_activated(self) -> None:
        without_keyword = self.tools.tactile.search("부드러운 니트", limit=3)
        with_keyword = self.tools.tactile.search("검정색 부드러운 니트", limit=3)
        self.assertNotIn("title_match", without_keyword["items"][0]["score_breakdown"]["relevance_weights"])
        self.assertIn("title_match", with_keyword["items"][0]["score_breakdown"]["relevance_weights"])

    def test_untactile_query_does_not_invent_a_tactile_term(self) -> None:
        payload = self.tools.tactile.search("원피스 보여줘", limit=5)
        self.assertEqual(payload["ranking_mode"], "title_and_popularity")
        for item in payload["items"]:
            self.assertEqual(item["score_breakdown"]["tactile_terms"], [])

    def test_image_predicted_items_are_never_labelled_review_grounded(self) -> None:
        payload = self.tools.tactile.search("부드러운 니트", limit=30)
        curated = self.tools.tactile.curated_asins
        for item in payload["items"]:
            expected = (
                "review_grounded_overlay"
                if item["product_id"] in curated
                else "image_predicted_last2"
            )
            self.assertEqual(item["tactile_target_source"], expected)
            self.assertEqual(item["matched_evidence"], [])

    def test_product_detail_states_the_prediction_is_not_review_evidence(self) -> None:
        product_id = self.tools.tactile.search("부드러운 니트", limit=1)["items"][0]["product_id"]
        detail = self.tools.tactile.product_detail(product_id)
        self.assertEqual(detail["tactile_profile"]["source"], "image_predicted_last2")
        self.assertIn("리뷰", detail["tactile_profile"]["note"])

    def test_accessories_are_excluded_from_garment_categories(self) -> None:
        payload = self.tools.tactile.search("부드러운 니트", limit=30)
        for item in payload["items"]:
            self.assertNotIn("necklace", item["title"].casefold())

    def test_unknown_product_id_raises(self) -> None:
        self.assertFalse(self.tools.product_exists("NOT-A-REAL-ASIN"))
        with self.assertRaises(KeyError):
            self.tools.public_product("NOT-A-REAL-ASIN")

    def test_image_path_resolves_to_a_local_file(self) -> None:
        product_id = self.tools.tactile.search("부드러운 니트", limit=1)["items"][0]["product_id"]
        if not self.tools.legacy_store.image_root.is_dir():
            # The backup server serves remote_image_url and keeps no local image cache.
            with self.assertRaises(KeyError):
                self.tools.legacy_store.image_path(product_id)
            return
        self.assertTrue(self.tools.legacy_store.image_path(product_id).is_file())

    def test_pagination_is_consistent(self) -> None:
        first = self.tools.list_products(page=1, page_size=5)
        second = self.tools.list_products(page=2, page_size=5)
        self.assertEqual(first["total"], second["total"])
        self.assertTrue(first["has_next"])
        self.assertFalse(first["has_previous"])
        self.assertTrue(second["has_previous"])
        overlap = {row["product_id"] for row in first["items"]} & {
            row["product_id"] for row in second["items"]
        }
        self.assertEqual(overlap, set())


class GenderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tools = FullCatalogTools()

    def test_title_words_decide_gender(self) -> None:
        titles = pd.Series([
            "women's soft knit", "womens cardigan", "men's hoodie", "boys fleece",
            "unisex beanie", "men and women tee", "floral midi", "plain tee",
        ]).str.casefold()
        categories = np.array(["sweater", "sweater", "top", "top", "accessory", "top", "dress", "top"])
        self.assertEqual(
            _title_genders(titles, categories).tolist(),
            [GENDER_WOMEN, GENDER_WOMEN, GENDER_MEN, GENDER_MEN,
             GENDER_UNISEX, GENDER_UNISEX, GENDER_WOMEN, GENDER_UNKNOWN],
        )

    def _genders_of(self, items) -> set[int]:
        index = self.tools.index
        return {int(index.genders[index.row_of(item["product_id"])]) for item in items}

    def test_search_drops_the_other_genders_listings(self) -> None:
        for gender, other in (("men", GENDER_WOMEN), ("women", GENDER_MEN)):
            payload = self.tools.tactile.search("니트", limit=50, keywords=["sweater"], gender=gender)
            self.assertEqual(payload["gender"], gender)
            self.assertTrue(payload["items"])
            self.assertNotIn(other, self._genders_of(payload["items"]))
        both = self.tools.tactile.search("니트", limit=50, keywords=["sweater"])
        self.assertIsNone(both["gender"])
        self.assertTrue({GENDER_WOMEN, GENDER_MEN} <= self._genders_of(both["items"]))

    def test_unlabelled_listings_rank_a_little_lower(self) -> None:
        index = self.tools.index
        factor = index.config["relevance"]["gender_unknown_factor"]
        both = self.tools.tactile.search("티셔츠", limit=300, keywords=["shirt"])
        men = {item["product_id"]: item["relevance_score"]
               for item in self.tools.tactile.search("티셔츠", limit=300, keywords=["shirt"], gender="men")["items"]}
        checked = set()
        for item in both["items"]:
            label = int(index.genders[index.row_of(item["product_id"])])
            if item["product_id"] not in men or label not in (GENDER_MEN, GENDER_UNKNOWN):
                continue
            expected = item["relevance_score"] * (factor if label == GENDER_UNKNOWN else 1.0)
            self.assertAlmostEqual(men[item["product_id"]], expected, places=5)
            checked.add(label)
        self.assertEqual(checked, {GENDER_MEN, GENDER_UNKNOWN})

    def test_product_list_filters_by_gender(self) -> None:
        everything = self.tools.list_products(page=1, page_size=100)
        men = self.tools.list_products(page=1, page_size=100, gender="men")
        self.assertIsNone(everything["gender"])
        self.assertEqual(men["gender"], "men")
        self.assertLess(men["total"], everything["total"])
        self.assertNotIn(GENDER_WOMEN, self._genders_of(men["items"]))


class AgeAndBrowseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tools = FullCatalogTools()

    def test_kids_titles_unless_an_adult_audience_is_named(self) -> None:
        titles = pd.Series([
            "toddler baby girl outfit", "girls' crop top hoodie", "kids sweatshirt",
            "necklace for women girls", "men's hoodie", "floral midi dress",
        ])
        self.assertEqual(_kids_titles(titles).tolist(), [True, True, True, False, False, False])

    def test_searches_leave_kids_out_unless_asked(self) -> None:
        index = self.tools.index
        adult = self.tools.tactile.search("니트", limit=60, keywords=["sweater"])
        kids = self.tools.tactile.search("니트", limit=60, keywords=["sweater"], for_kids=True)
        self.assertFalse(any(index.kids[index.row_of(item["product_id"])] for item in adult["items"]))
        self.assertTrue(kids["items"])
        self.assertTrue(all(index.kids[index.row_of(item["product_id"])] for item in kids["items"]))

    def test_product_list_shows_adult_clothing_only(self) -> None:
        index = self.tools.index
        page = self.tools.list_products(page=1, page_size=100)
        rows = [index.row_of(item["product_id"]) for item in page["items"]]
        self.assertTrue(all(index.categories[row] in GARMENT_CATEGORIES for row in rows))
        self.assertFalse(any(index.kids[row] for row in rows))
        jewelry = re.compile(r"\b(?:earrings?|rings?|necklaces?|bracelets?|polishing cloth|septum)\b")
        self.assertEqual([index.titles[row] for row in rows if jewelry.search(index.titles[row].casefold())], [])
        self.assertLess(page["total"], len(index.rows_with_image))

    def test_accessory_rule_catches_plurals_but_not_garment_details(self) -> None:
        pattern = self.tools.index.config["retrieval"]["type_exclusion_rules"][0]["pattern"]
        for title in ("stud earrings set", "septum nose rings", "band ring for women", "polishing cloth for silver"):
            self.assertRegex(title, pattern)
        for title in ("men's ring spun cotton t-shirt", "o-ring bikini set", "ringer tee"):
            self.assertNotRegex(title, pattern)


class TitleMatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tools = FullCatalogTools()

    def _hits(self, mode: str, keyword: str, titles: list[str]) -> list[bool]:
        index = self.tools.index
        relevance = index.config["relevance"]
        before = relevance.get("title_match_mode")
        relevance["title_match_mode"] = mode
        try:
            # Score real rows whose titles are swapped for the test titles.
            rows = np.arange(len(titles))
            saved = index.lowered_titles
            index.lowered_titles = pd.Series([t.casefold() for t in titles])
            try:
                return [bool(value) for value in index.title_match(rows, [keyword])]
            finally:
                index.lowered_titles = saved
        finally:
            relevance["title_match_mode"] = before

    def test_word_mode_keeps_endings_but_not_other_words(self) -> None:
        titles = ["Men's Workout Shorts", "Work Pants for Men", "Workwear Jacket", "Knitted Cardigan",
                  "Cotton Sweatshirt", "Basic T-Shirt", "Cable Knit Sweater", "Linen Dresses"]
        self.assertEqual(self._hits("word", "work", titles[:3]), [False, True, True])
        self.assertEqual(self._hits("word", "knit", [titles[3], titles[6]]), [True, True])
        self.assertEqual(self._hits("word", "shirt", [titles[4], titles[5]]), [False, True])
        self.assertEqual(self._hits("word", "dress", [titles[7]]), [True])
        self.assertEqual(self._hits("word", "fit", ["Slim Fitted Blazer", "Outfit Set"]), [True, False])

    def test_service_uses_word_mode_and_substring_stays_available(self) -> None:
        # Chosen 2026-09-27 (evaluation/results/20260927_step14a/b); substring is kept for comparison runs.
        self.assertEqual(self.tools.index.config["relevance"]["title_match_mode"], "word")
        self.assertEqual(self._hits("substring", "work", ["Men's Workout Shorts"]), [True])


class ConceptMappingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tools = FullCatalogTools()

    def test_every_mapped_concept_targets_a_real_last2_class(self) -> None:
        for concept, (last2_class, fidelity) in CONCEPT_TO_LAST2.items():
            with self.subTest(concept=concept):
                self.assertIn(last2_class, TACTILE_CLASSES)
                self.assertIn(fidelity, {"direct", "proxy"})

    def test_unsupported_concepts_are_reported_not_approximated(self) -> None:
        intent = TactileIntent(desired_more=("sheerness", "softness"))
        terms, unsupported = intent_terms(intent)
        self.assertEqual(unsupported, ["sheerness"])
        self.assertEqual([term[1] for term in terms], ["softness"])

    def test_no_unsupported_concept_has_a_mapping(self) -> None:
        for concept in UNSUPPORTED_CONCEPTS:
            self.assertNotIn(concept, CONCEPT_TO_LAST2)

    def test_proxy_concepts_weigh_less_than_direct_ones(self) -> None:
        direct = intent_terms(TactileIntent(desired_more=("roughness",)))[0][0][3]
        proxy = intent_terms(TactileIntent(desired_more=("scratchiness",)))[0][0][3]
        self.assertLess(proxy, direct)

    def test_negative_direction_flips_the_score_sign(self) -> None:
        tools = self.tools
        candidates = tools.tactile.search("부드러운 니트", limit=3)["items"]
        more = tools.tactile.tactile_scores(candidates, TactileIntent(desired_more=("softness",)))
        less = tools.tactile.tactile_scores(candidates, TactileIntent(desired_less=("softness",)))
        for product_id, row in more.items():
            self.assertAlmostEqual(row["tactile_score"], -less[product_id]["tactile_score"], places=5)

    def test_korean_colour_words_become_english_title_keywords(self) -> None:
        self.assertIn("black", title_keywords("검정색 니트"))
        self.assertIn("navy", title_keywords("네이비 원피스"))


class FullCatalogServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.directory = tempfile.TemporaryDirectory()
        settings = AgentSettings.load()
        cls.settings = AgentSettings(
            **{
                **settings.__dict__,
                "catalog_mode": "full",
                "database_path": Path(cls.directory.name) / "full.sqlite3",
                "llm_provider": "deterministic",
            }
        )
        cls.app = AgentApplication(cls.settings)
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(cls.app))
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)
        cls.directory.cleanup()

    def _request(self, method: str, path: str, body: dict | None = None, cookie: str = "") -> tuple[int, dict, str]:
        connection = HTTPConnection("127.0.0.1", self.port, timeout=60)
        headers = {"Content-Type": "application/json"}
        if cookie:
            headers["Cookie"] = cookie
        connection.request(method, path, json.dumps(body) if body is not None else None, headers)
        response = connection.getresponse()
        payload = json.loads(response.read() or b"{}")
        set_cookie = response.getheader("Set-Cookie") or ""
        connection.close()
        return response.status, payload, set_cookie.split(";")[0]

    def test_health_reports_the_full_catalog(self) -> None:
        status, payload, _ = self._request("GET", "/agent/v1/health")
        self.assertEqual(status, 200)
        self.assertEqual(payload["catalog_mode"], "full")
        self.assertGreater(payload["catalog_products"], 800_000)

    def test_login_memory_and_cart_work_on_the_full_catalog(self) -> None:
        status, _, cookie = self._request(
            "POST",
            "/agent/v1/auth/register",
            {"email": "full-catalog@example.com", "password": "DemoPass1234!", "display_name": "T"},
        )
        self.assertEqual(status, 201, msg=str(status))

        status, session, _ = self._request("POST", "/agent/v1/sessions", {}, cookie)
        self.assertEqual(status, 201)
        session_id = session["session_id"]

        status, reply, _ = self._request(
            "POST",
            f"/agent/v1/sessions/{session_id}/messages",
            {"message": "까슬거리지 않고 부드러운 니트 추천해줘"},
            cookie,
        )
        self.assertEqual(status, 200)
        self.assertEqual(reply["action"], "search_products")
        self.assertTrue(reply["products"])

        status, preferences, _ = self._request("GET", "/agent/v1/preferences", None, cookie)
        self.assertEqual(status, 200)
        self.assertTrue(preferences["items"])

        product_id = reply["products"][0]["product_id"]
        status, _, _ = self._request(
            "POST", "/agent/v1/cart/items", {"product_id": product_id, "quantity": 1}, cookie
        )
        self.assertEqual(status, 201)
        status, cart, _ = self._request("GET", "/agent/v1/cart", None, cookie)
        self.assertEqual(status, 200)
        self.assertEqual([row["product_id"] for row in cart["items"]], [product_id])

    def test_unauthenticated_search_is_rejected(self) -> None:
        status, _, _ = self._request("POST", "/agent/v1/sessions", {})
        self.assertEqual(status, 401)


if __name__ == "__main__":
    unittest.main()
