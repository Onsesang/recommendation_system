"""Full Amazon Fashion catalog tools for the agent (825,840 items).

The curated `ShoppingTools` path serves 465 products whose tactile evidence comes
from real review spans. This module serves the whole catalog instead, where the
tactile signal is the frozen Last2 classifier cache predicted from product
images. The two sources stay distinguishable on every row: `tactile_target_source`
is `review_grounded_overlay` only for products that also exist in the curated
review-backed catalog, and `image_predicted_last2` everywhere else.

The 14 Last2 classes are a fixed taxonomy. They do not replace the curated
open-vocabulary representation; they are an additional, separately labelled
signal that exists for the whole catalog.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any, Iterator, Mapping

import numpy as np
import pandas as pd

from demo_agent.models import StructuredQuery
from demo_agent.recommender import CATEGORY_SPECS, TACTILE_LABELS_KO
from demo_agent.tactile_parser import parse_message
from recommendation_api.tactile_models import TactileIntent

from .config import PROJECT_ROOT
from .preferences import COLOR_PATTERNS, STYLE_PATTERNS


DEFAULT_CONFIG = PROJECT_ROOT / "shopping_agent/configs/full_catalog.json"

TACTILE_CLASSES = (
    "soft",
    "firm",
    "smooth",
    "rough",
    "non_elastic",
    "elastic",
    "thin",
    "thick",
    "flexible",
    "stiff",
    "warm",
    "cool",
    "spongy",
    "crisp",
)

# Open-vocabulary concepts from the curated intent parser mapped onto Last2 classes.
# `direct` means the two names denote the same property. `proxy` means the Last2
# class is the closest available signal but is not the same property, so it is
# down-weighted and reported as a proxy rather than presented as a measurement.
CONCEPT_TO_LAST2: dict[str, tuple[str, str]] = {
    "softness": ("soft", "direct"),
    "roughness": ("rough", "direct"),
    "stretchiness": ("elastic", "direct"),
    "stiffness": ("stiff", "direct"),
    "thickness": ("thick", "direct"),
    "thinness": ("thin", "direct"),
    "warmth": ("warm", "direct"),
    "coolness": ("cool", "direct"),
    "scratchiness": ("rough", "proxy"),
    "itchiness": ("rough", "proxy"),
    "flowiness": ("flexible", "proxy"),
    "heaviness": ("thick", "proxy"),
    "weight_lightness": ("thin", "proxy"),
}

# Concepts the Last2 taxonomy carries no signal for. They are reported back to the
# caller instead of being silently dropped or approximated.
UNSUPPORTED_CONCEPTS = ("sheerness", "breathability", "linting", "pilling")

_TOKEN_PATTERN = re.compile(r"[a-z0-9]+")

# Number of leading title tokens that identify a product family for deduplication.
_TITLE_KEY_TOKENS = 8


# Who a listing is for, from title words ("Women's", "Men's", "Girls", "Unisex"). Kids'
# listings count with their side. Dresses and skirts with no such word are treated as
# women's. The catalog has no department field, so about 29% of listings stay unknown.
GENDERS = ("women", "men")
GENDER_UNKNOWN, GENDER_WOMEN, GENDER_MEN, GENDER_UNISEX = 0, 1, 2, 3
_WOMEN_TITLE = r"\b(?:women|woman|womens|ladies|lady|girls?|female|maternity|juniors?)\b"
_MEN_TITLE = r"\b(?:men|mens|man|boys?|male|gentlemen)\b"
_UNISEX_TITLE = r"\bunisex\b"
_WOMEN_ONLY_CATEGORIES = ("dress", "skirt")


def _title_genders(lowered_titles: pd.Series, categories: np.ndarray) -> np.ndarray:
    titles = lowered_titles
    women = titles.str.contains(_WOMEN_TITLE, regex=True, na=False).to_numpy()
    men = titles.str.contains(_MEN_TITLE, regex=True, na=False).to_numpy()
    unisex = titles.str.contains(_UNISEX_TITLE, regex=True, na=False).to_numpy() | (women & men)
    genders = np.full(len(titles), GENDER_UNKNOWN, dtype=np.int8)
    genders[women] = GENDER_WOMEN
    genders[men] = GENDER_MEN
    genders[unisex] = GENDER_UNISEX
    genders[(genders == GENDER_UNKNOWN) & np.isin(categories, _WOMEN_ONLY_CATEGORIES)] = GENDER_WOMEN
    return genders


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _resolve(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else PROJECT_ROOT / path


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, float(value)))


# English title spellings per canonical colour; "navy" titles often say "dark blue".
COLOR_TITLE_PATTERNS = {
    "navy": r"\bnavy\b|\bdark[\s-]*blue\b",
    "gray": r"\bgr[ae]y\b|\bcharcoal\b",
    "white": r"\bwhite\b|\bivory\b|\boff[\s-]*white\b",
    "beige": r"\bbeige\b|\bkhaki\b|\bcamel\b|\btan\b",
    "red": r"\bred\b|\bburgundy\b|\bwine\b",
}


def title_keywords(text: str) -> list[str]:
    """Latin tokens a title can actually be matched against.

    Korean colour and style words are translated through the same lexicons the
    preference extractor uses, because catalog titles are English.
    """
    lowered = text.casefold()
    tokens: list[str] = []
    for canonical, patterns in (*COLOR_PATTERNS.items(), *STYLE_PATTERNS.items()):
        if any(re.search(pattern, lowered, re.IGNORECASE) for pattern in patterns):
            tokens.append(canonical)
    for token in _TOKEN_PATTERN.findall(lowered):
        if len(token) >= 3:
            tokens.append(token)
    return list(dict.fromkeys(tokens))


class FullCatalogIndex:
    """In-memory index over the whole catalog: metadata plus the Last2 cache."""

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        started = time.perf_counter()
        self.config = config or _read_json(DEFAULT_CONFIG)
        data = self.config["data"]
        self.image_root = _resolve(data["image_root"])

        metadata = pd.read_parquet(
            _resolve(data["metadata_path"]),
            columns=["iid", "parent_asin", "train_count", "title", "category", "image_url"],
        ).sort_values("iid").reset_index(drop=True)
        if not np.array_equal(metadata["iid"].to_numpy(), np.arange(len(metadata))):
            raise ValueError("item metadata iid must be contiguous and row-aligned")

        profiles = pd.read_parquet(
            _resolve(data["profiles_path"]),
            columns=["iid", "parent_asin", *TACTILE_CLASSES],
        ).sort_values("iid").reset_index(drop=True)

        ids = profiles["iid"].to_numpy(dtype=np.int32, copy=True)
        if ids.size == 0 or ids.min() < 0 or ids.max() >= len(metadata):
            raise ValueError("Last2 profile iid falls outside the metadata catalog")
        aligned_asins = metadata["parent_asin"].to_numpy()[ids].astype(str)
        if not np.array_equal(aligned_asins, profiles["parent_asin"].astype(str).to_numpy()):
            raise ValueError("metadata and Last2 profile ASINs are not aligned")

        self.iids = ids
        self.asins = aligned_asins
        self.titles = metadata["title"].fillna("제목 정보 없음").astype(str).to_numpy()[ids]
        self.categories = metadata["category"].fillna("other").astype(str).to_numpy()[ids]
        self.image_urls = metadata["image_url"].fillna("").astype(str).to_numpy()[ids]
        # Amazon serves one transparent GIF for listings without a photo; such products show
        # an empty card and cannot be judged by a user, so search and the product list skip them.
        placeholder = str(self.config["retrieval"].get("placeholder_image_pattern") or "")
        self.has_image = (
            ~pd.Series(self.image_urls, copy=False).str.contains(placeholder, case=False, regex=True, na=True).to_numpy()
            if placeholder
            else np.ones(len(self.image_urls), dtype=bool)
        )
        self.rows_with_image = np.flatnonzero(self.has_image).astype(np.int32)
        self.train_counts = metadata["train_count"].fillna(0).to_numpy(dtype=np.int32)[ids]
        self.matrix = profiles[list(TACTILE_CLASSES)].to_numpy(dtype=np.float32, copy=True)
        if not np.isfinite(self.matrix).all() or (self.matrix < 0).any() or (self.matrix > 1).any():
            raise ValueError("Last2 probabilities must be finite and within [0, 1]")

        self.lowered_titles = pd.Series(self.titles, copy=False).str.casefold()
        self.genders = _title_genders(self.lowered_titles, self.categories)
        self._class_index = {name: i for i, name in enumerate(TACTILE_CLASSES)}
        self._asin_to_row = {asin: row for row, asin in enumerate(self.asins.tolist())}
        self._category_cache: dict[str, tuple[np.ndarray, bool]] = {}
        self._title_keys: dict[int, str] = {}

        popularity = np.log1p(self.train_counts.astype(np.float32))
        peak = float(popularity.max()) or 1.0
        self.popularity = popularity / peak

        self._image_features: np.ndarray | None = None
        self._image_feature_path = _resolve(data["image_feature_path"])
        self.load_seconds = time.perf_counter() - started

    # -- lookups -----------------------------------------------------------

    def __len__(self) -> int:
        return len(self.asins)

    def exists(self, product_id: str) -> bool:
        return product_id in self._asin_to_row

    def row_of(self, product_id: str) -> int:
        row = self._asin_to_row.get(product_id)
        if row is None:
            raise KeyError(f"Unknown product_id: {product_id}")
        return row

    def image_path(self, product_id: str) -> Path:
        return self.image_root / f"{int(self.iids[self.row_of(product_id)])}.jpg"

    def tactile_row(self, product_id: str) -> np.ndarray:
        return self.matrix[self.row_of(product_id)]

    def image_vector(self, product_id: str) -> np.ndarray:
        if self._image_features is None:
            self._image_features = np.load(self._image_feature_path, mmap_mode="r")
        vector = np.asarray(
            self._image_features[int(self.iids[self.row_of(product_id)])], dtype=np.float32
        )
        norm = float(np.linalg.norm(vector))
        return vector / norm if norm else vector

    def title_key(self, row: int) -> str:
        """Collapse variant listings (same product, different size/colour ASIN)."""
        cached = self._title_keys.get(row)
        if cached is None:
            tokens = _TOKEN_PATTERN.findall(str(self.titles[row]).casefold())
            cached = " ".join(tokens[:_TITLE_KEY_TOKENS])
            self._title_keys[row] = cached
        return cached

    def predictions(self, row: int) -> dict[str, float]:
        return {
            name: float(self.matrix[row, column])
            for column, name in enumerate(TACTILE_CLASSES)
        }

    # -- candidate selection ------------------------------------------------

    def candidate_rows(self, category: str | None) -> tuple[np.ndarray, bool]:
        """Rows for a parsed category, with a flag for a relaxed garment filter."""
        if category is None:
            return self.rows_with_image, False
        cached = self._category_cache.get(category)
        if cached is not None:
            return cached
        spec = CATEGORY_SPECS.get(category)
        if spec is None:
            result = (self.rows_with_image, True)
            self._category_cache[category] = result
            return result
        broad_rows = np.flatnonzero(np.isin(self.categories, spec.broad_categories) & self.has_image).astype(np.int32)
        rows = broad_rows
        relaxed = False
        if spec.title_pattern and broad_rows.size:
            minimum = int(self.config["retrieval"]["specific_category_min_candidates"])
            matches = (
                self.lowered_titles.to_numpy()[broad_rows]
            )
            specific = pd.Series(matches, copy=False).str.contains(
                spec.title_pattern, case=False, regex=True, na=False
            ).to_numpy()
            specific_rows = broad_rows[specific]
            if specific_rows.size >= minimum:
                rows = specific_rows
            else:
                relaxed = True
        rows = self._drop_other_types(rows, category)
        result = (rows, relaxed)
        self._category_cache[category] = result
        return result

    def _drop_other_types(self, rows: np.ndarray, category: str) -> np.ndarray:
        """Remove listings whose title names a different product type than the request.

        The source taxonomy is noisy: socks and masquerade masks sit under `dress`
        ("Dress Socks", "Fancy Dress Masks"), panties under `pants`, scarves under
        `sweater`. Each rule in `retrieval.type_exclusion_rules` drops titles matching
        its pattern for the categories it applies to. A "with ..." phrase is ignored
        first, so "Trench Coat with Belt" stays a coat.
        """
        retrieval = self.config["retrieval"]
        rules = [
            rule for rule in retrieval.get("type_exclusion_rules", [])
            if category not in rule.get("except_categories", [])
            and ("categories" not in rule or category in rule["categories"])
        ]
        if not rules or not rows.size:
            return rows
        titles = pd.Series(self.lowered_titles.to_numpy()[rows], copy=False)
        ignore = retrieval.get("type_exclusion_ignore_phrase")
        if ignore:
            titles = titles.str.replace(ignore, " ", case=False, regex=True)
        drop = np.zeros(len(rows), dtype=bool)
        for rule in rules:
            drop |= titles.str.contains(rule["pattern"], case=False, regex=True, na=False).to_numpy()
        kept = rows[~drop]
        minimum = int(retrieval.get("type_exclusion_min_candidates", 0))
        return kept if kept.size >= minimum else rows

    def for_gender(self, rows: np.ndarray, gender: str | None) -> np.ndarray:
        """Drop listings marked for the other gender; unisex and unknown ones stay."""
        if gender not in GENDERS:
            return rows
        other = GENDER_MEN if gender == "women" else GENDER_WOMEN
        return rows[self.genders[rows] != other]

    def color_match(self, rows: np.ndarray, colors: list[str]) -> np.ndarray:
        """1.0 when a candidate title names any requested colour (English title words), else 0."""
        patterns = [COLOR_TITLE_PATTERNS.get(color, rf"\b{re.escape(color)}\b") for color in colors]
        subset = pd.Series(self.lowered_titles.to_numpy()[rows], copy=False)
        return subset.str.contains("|".join(patterns), regex=True, na=False).to_numpy(dtype=np.float32)

    def any_title_term(self, rows: np.ndarray, terms: list[str]) -> np.ndarray:
        """1.0 when a candidate title contains any of `terms` as a word, else 0."""
        pattern = "|".join(rf"\b{re.escape(term.casefold())}\b" for term in dict.fromkeys(terms))
        subset = pd.Series(self.lowered_titles.to_numpy()[rows], copy=False)
        return subset.str.contains(pattern, regex=True, na=False).to_numpy(dtype=np.float32)

    def title_match(self, rows: np.ndarray, keywords: list[str]) -> np.ndarray:
        """Fraction of query keywords present in each candidate title."""
        if not keywords or not rows.size:
            return np.zeros(len(rows), dtype=np.float32)
        subset = pd.Series(self.lowered_titles.to_numpy()[rows], copy=False)
        hits = np.zeros(len(rows), dtype=np.float32)
        for keyword in keywords:
            hits += subset.str.contains(keyword, regex=False, na=False).to_numpy(dtype=np.float32)
        return hits / float(len(keywords))


class FullCatalogMultimodal:
    """Behaviour-similarity vectors for the personalized ranker."""

    def __init__(self, index: FullCatalogIndex) -> None:
        self.index = index

    def image_vector(self, product_id: str) -> np.ndarray:
        return self.index.image_vector(product_id)

    def tactile_vector(self, product_id: str) -> np.ndarray:
        """Last2 probabilities centred to [-1, 1] so cosine has a usable sign."""
        return (self.index.tactile_row(product_id) * 2.0 - 1.0).astype(np.float32)


class _CategoryView(Mapping[str, dict[str, Any]]):
    """Lazy `product_metadata`-shaped view; the ranker only reads `category`."""

    def __init__(self, index: FullCatalogIndex) -> None:
        self.index = index

    def __getitem__(self, product_id: str) -> dict[str, Any]:
        row = self.index.row_of(product_id)
        return {
            "product_id": product_id,
            "category": str(self.index.categories[row]),
            "title": str(self.index.titles[row]),
        }

    def __contains__(self, product_id: object) -> bool:
        return isinstance(product_id, str) and self.index.exists(product_id)

    def __iter__(self) -> Iterator[str]:
        return iter(self.index.asins.tolist())

    def __len__(self) -> int:
        return len(self.index)


def intent_terms(intent: TactileIntent) -> tuple[list[tuple[str, str, str, float]], list[str]]:
    """Map an open-vocabulary intent onto weighted Last2 terms.

    Returns the terms as `(direction, concept, last2_class, fidelity_weight)` and
    the list of requested concepts the Last2 taxonomy cannot express.
    """
    config = _read_json(DEFAULT_CONFIG)["concept_fidelity"]
    weights = {"direct": float(config["direct_weight"]), "proxy": float(config["proxy_weight"])}
    terms: list[tuple[str, str, str, float]] = []
    unsupported: list[str] = []
    groups = (
        ("positive", (*intent.desired_more, *intent.must_have)),
        ("negative", (*intent.desired_less, *intent.avoid)),
    )
    for direction, concepts in groups:
        for concept in concepts:
            # A model-structured intent names Last2 classes directly.
            mapped = (concept, "direct") if concept in TACTILE_CLASSES else CONCEPT_TO_LAST2.get(concept)
            if mapped is None:
                if concept not in unsupported:
                    unsupported.append(concept)
                continue
            last2_class, fidelity = mapped
            terms.append((direction, concept, last2_class, weights[fidelity]))
    return terms, unsupported


class FullCatalogTactileProvider:
    """Search and scoring over the whole catalog using the Last2 cache."""

    DEDUPLICATION_OVERSAMPLE = 6

    def __init__(self, index: FullCatalogIndex) -> None:
        self.index = index
        self.config = index.config
        self.curated_asins: frozenset[str] = frozenset()

    @property
    def version(self) -> str:
        return f"last2-image-predicted-{self.config['version']}"

    # -- search -------------------------------------------------------------

    def search(
        self,
        query_text: str,
        *,
        limit: int,
        structured: StructuredQuery | None = None,
        keywords: list[str] | None = None,
        gender: str | None = None,
    ) -> dict[str, Any]:
        """Rank the catalog for a query.

        `structured` replaces the deterministic parser when a model has already
        resolved the request into Last2 constraints. `keywords` replaces the title
        tokens taken from `query_text`, which lets a Korean request match the
        English catalog titles. `gender` ("women"/"men") drops the other side's listings
        and ranks listings whose title does not say slightly lower.
        """
        parsed = structured or parse_message(query_text)
        rows, category_relaxed = self.index.candidate_rows(parsed.category)
        rows = self.index.for_gender(rows, gender)
        if not rows.size:
            return {
                "items": [],
                "total_candidates": 0,
                "category": parsed.category,
                "category_relaxed": category_relaxed,
                "ranking_mode": "no_category_candidates",
            }

        weights = self.config["relevance"]
        overrides = self.config.get("class_weight_overrides", {})
        tactile_numerator = np.zeros(len(rows), dtype=np.float32)
        total_weight = 0.0
        terms: list[tuple[str, str, float]] = []
        for direction, constraints in (
            ("positive", parsed.constraints),
            ("negative", parsed.negative_constraints),
        ):
            for constraint in constraints:
                weight = float(constraint.weight) * float(
                    overrides.get(constraint.tactile_class, 1.0)
                )
                values = self.index.matrix[rows, self.index._class_index[constraint.tactile_class]]
                tactile_numerator += weight * (values if direction == "positive" else 1.0 - values)
                total_weight += weight
                terms.append((direction, constraint.tactile_class, weight))

        tactile_component = (
            tactile_numerator / total_weight
            if total_weight
            else np.zeros(len(rows), dtype=np.float32)
        )
        keywords = title_keywords(" ".join(keywords) if keywords is not None else query_text)
        # Optional colour component: when `color_match_weight` is set and the request names a
        # colour, colour is scored on its own instead of being one keyword among several, so
        # "navy pants" cannot be satisfied by any pants whose title says nothing about navy.
        colors = [word for word in keywords if word in COLOR_PATTERNS]
        color_weight = float(weights.get("color_match_weight", 0.0))
        color_component = None
        if color_weight > 0 and colors:
            color_component = self.index.color_match(rows, colors)
            keywords = [word for word in keywords if word not in colors]
        title_component = self.index.title_match(rows, keywords)
        popularity_component = self.index.popularity[rows]
        # Optional material-word component: image predictions are often flat across a category
        # (every skirt looks ~0.7 flexible), so a title that names a matching material or cut
        # ("chiffon", "fleece", "stretch") is used as extra evidence for a wanted class.
        texture_weight = float(weights.get("tactile_title_weight", 0.0))
        texture_terms = [
            term
            for constraint in parsed.constraints
            for term in weights.get("tactile_title_terms", {}).get(constraint.tactile_class, [])
        ]
        texture_component = (
            self.index.any_title_term(rows, texture_terms) if texture_weight > 0 and texture_terms else None
        )

        # Only components that carry a signal for this query take part in the
        # weighted average. A component the query said nothing about must not
        # consume weight, or it would silently dilute the ones that did.
        active: list[tuple[str, np.ndarray, float]] = []
        if total_weight:
            active.append(("tactile_match", tactile_component, float(weights["tactile_match_weight"])))
        if keywords:
            active.append(("title_match", title_component, float(weights["title_match_weight"])))
        if color_component is not None:
            active.append(("color_match", color_component, color_weight))
        if texture_component is not None:
            active.append(("tactile_title", texture_component, texture_weight))
        active.append(("popularity", popularity_component, float(weights["popularity_weight"])))

        denominator = sum(weight for _, _, weight in active)
        relevance = np.zeros(len(rows), dtype=np.float32)
        for _, component, weight in active:
            relevance += weight * component
        relevance = (relevance / denominator).astype(np.float32)
        if gender in GENDERS:
            unknown = self.index.genders[rows] == GENDER_UNKNOWN
            relevance[unknown] *= float(weights.get("gender_unknown_factor", 1.0))
        ranking_mode = "last2_explicit_tactile" if total_weight else "title_and_popularity"
        active_weights = {name: weight / denominator for name, _, weight in active}

        # Variant products (same title, different ASIN) would otherwise fill the
        # page, so oversample and keep the best-ranked row per title.
        limit = max(1, int(limit))
        oversample = int(min(len(rows), limit * self.DEDUPLICATION_OVERSAMPLE))
        top = np.argpartition(-relevance, oversample - 1)[:oversample]
        ordered = top[
            np.lexsort(
                (self.index.asins[rows[top]], -self.index.popularity[rows[top]], -relevance[top])
            )
        ]

        seen: set[str] = set()
        order: list[int] = []
        for position in ordered:
            key = self.index.title_key(int(rows[position]))
            if key in seen:
                continue
            seen.add(key)
            order.append(int(position))
            if len(order) >= limit:
                break

        items = [
            self._item(
                int(rows[position]),
                rank=rank,
                relevance=float(relevance[position]),
                tactile_component=float(tactile_component[position]),
                title_component=float(title_component[position]),
                popularity_component=float(popularity_component[position]),
                active_weights=active_weights,
                terms=terms,
                total_weight=total_weight,
                ranking_mode=ranking_mode,
            )
            for rank, position in enumerate(order, 1)
        ]
        return {
            "items": items,
            "total_candidates": int(len(rows)),
            "category": parsed.category,
            "category_relaxed": category_relaxed,
            "ranking_mode": ranking_mode,
            "gender": gender if gender in GENDERS else None,
            "title_keywords": keywords,
            "catalog_size": len(self.index),
        }

    def _item(
        self,
        row: int,
        *,
        rank: int,
        relevance: float,
        tactile_component: float,
        title_component: float,
        popularity_component: float,
        active_weights: dict[str, float],
        terms: list[tuple[str, str, float]],
        total_weight: float,
        ranking_mode: str,
    ) -> dict[str, Any]:
        product_id = str(self.index.asins[row])
        predictions = self.index.predictions(row)
        breakdown_terms = []
        reason_parts = []
        for direction, tactile_class, weight in terms:
            raw = predictions[tactile_class]
            component = raw if direction == "positive" else 1.0 - raw
            breakdown_terms.append(
                {
                    "direction": direction,
                    "class": tactile_class,
                    "raw_probability": raw,
                    "match_component": component,
                    "weight": weight,
                    "weighted_component": weight * component,
                }
            )
            label = TACTILE_LABELS_KO[tactile_class]
            reason_parts.append(
                f"{label} {raw:.2f}"
                if direction == "positive"
                else f"{label} 예측 {raw:.2f}(낮을수록 조건에 부합)"
            )

        review_grounded = product_id in self.curated_asins
        return {
            "product_id": product_id,
            "title": str(self.index.titles[row]),
            "category": str(self.index.categories[row]),
            "image_url": f"/images/{product_id}.jpg",
            "remote_image_url": str(self.index.image_urls[row]),
            "rank": rank,
            "relevance_score": _clamp(relevance),
            "tactile_target_source": (
                "review_grounded_overlay" if review_grounded else "image_predicted_last2"
            ),
            "review_grounded_evidence_available": review_grounded,
            "train_interaction_count": int(self.index.train_counts[row]),
            "last2_predictions": predictions,
            "recommendation_reason": (
                "Last2 이미지 예측 " + ", ".join(reason_parts)
                if reason_parts
                else "촉감 조건이 없어 제목 일치와 학습 상호작용 수로 정렬했습니다."
            ),
            "matched_evidence": [],
            "score_breakdown": {
                "ranking_mode": ranking_mode,
                "relevance_inputs": {
                    "tactile_match": tactile_component,
                    "title_match": title_component,
                    "popularity": popularity_component,
                },
                "relevance_weights": active_weights,
                "configured_weights": dict(self.config["relevance"]),
                "tactile_terms": breakdown_terms,
                "tactile_total_weight": total_weight,
                "evidence_source": (
                    "review_grounded_overlay" if review_grounded else "image_predicted_last2"
                ),
            },
        }

    # -- scoring for the personalized ranker ---------------------------------

    def tactile_scores(
        self, candidates: list[dict[str, Any]], intent: TactileIntent
    ) -> dict[str, dict[str, Any]]:
        if not candidates:
            return {}
        terms, unsupported = intent_terms(intent)
        scores: dict[str, dict[str, Any]] = {}
        for candidate in candidates:
            product_id = str(candidate["product_id"])
            try:
                row = self.index.row_of(product_id)
            except KeyError:
                continue
            predictions = self.index.predictions(row)
            numerator = 0.0
            weight_total = 0.0
            contributions = []
            for direction, concept, last2_class, weight in terms:
                raw = predictions[last2_class]
                signed = (2.0 * raw - 1.0) if direction == "positive" else (1.0 - 2.0 * raw)
                numerator += weight * signed
                weight_total += weight
                contributions.append(
                    {
                        "direction": direction,
                        "concept": concept,
                        "last2_class": last2_class,
                        "fidelity_weight": weight,
                        "raw_probability": raw,
                        "signed_component": signed,
                    }
                )
            scores[product_id] = {
                "product_id": product_id,
                "tactile_score": float(numerator / weight_total) if weight_total else 0.0,
                "tactile_terms": contributions,
                "unsupported_concepts": unsupported,
                "source": "image_predicted_last2",
            }
        return scores

    # -- detail --------------------------------------------------------------

    def product_detail(self, product_id: str) -> dict[str, Any]:
        row = self.index.row_of(product_id)
        predictions = self.index.predictions(row)
        ranked = sorted(predictions.items(), key=lambda item: -item[1])
        review_grounded = product_id in self.curated_asins
        return {
            "product": {
                "product_id": product_id,
                "title": str(self.index.titles[row]),
                "category": str(self.index.categories[row]),
                "image_url": f"/images/{product_id}.jpg",
                "remote_image_url": str(self.index.image_urls[row]),
                "train_interaction_count": int(self.index.train_counts[row]),
            },
            "tactile_profile": {
                "source": "image_predicted_last2",
                "model": "fashionclip_last2",
                "classes": predictions,
                "strongest": [
                    {"class": name, "label_ko": TACTILE_LABELS_KO[name], "probability": value}
                    for name, value in ranked[:5]
                ],
                "review_grounded_evidence_available": review_grounded,
                "note": (
                    "이 상품은 리뷰 근거 catalog에도 존재합니다. 리뷰 기반 소재 근거는 "
                    "curated 모드에서 확인할 수 있습니다."
                    if review_grounded
                    else "이 확률은 상품 이미지에서 예측한 값이며 구매자 리뷰 근거가 아닙니다."
                ),
            },
            "tactile_concerns": [],
            "related": [],
        }

    def compare(self, product_ids: list[str]) -> dict[str, Any]:
        rows = []
        for product_id in product_ids:
            row = self.index.row_of(product_id)
            rows.append(
                {
                    "product_id": product_id,
                    "title": str(self.index.titles[row]),
                    "category": str(self.index.categories[row]),
                    "last2_predictions": self.index.predictions(row),
                }
            )
        return {
            "items": rows,
            "source": "image_predicted_last2",
            "note": "비교값은 이미지 예측 확률이며 리뷰 근거가 아닙니다.",
        }


class _LegacyStoreShim:
    """Only `image_path` is used by the HTTP layer."""

    def __init__(self, index: FullCatalogIndex) -> None:
        self.index = index
        self.image_root = index.image_root

    def image_path(self, product_id: str) -> Path:
        path = self.index.image_path(product_id)
        # A server without the image cache answers 404; clients fall back to remote_image_url.
        if not path.is_file():
            raise KeyError(f"Image not found: {product_id}")
        return path


class _CatalogShim:
    """Mirrors the attributes `PersonalizedRanker` and the server read."""

    def __init__(self, index: FullCatalogIndex) -> None:
        self.index = index
        self.product_metadata = _CategoryView(index)
        self.multimodal = FullCatalogMultimodal(index)
        self.catalog_asins = index.asins


class FullCatalogTools:
    """Drop-in replacement for `ShoppingTools` backed by the full catalog."""

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.index = FullCatalogIndex(config)
        self.catalog = _CatalogShim(self.index)
        self.legacy_store = _LegacyStoreShim(self.index)
        self.tactile = FullCatalogTactileProvider(self.index)
        if self.index.config["evidence"]["expose_review_grounded_overlay"]:
            self.tactile.curated_asins = self._curated_asins()

    @staticmethod
    def _curated_asins() -> frozenset[str]:
        """ASINs that also have review-grounded evidence, for provenance labelling.

        Loading the curated catalog is optional; the full catalog still serves if
        those artifacts are unavailable.
        """
        try:
            from recommendation_api.store import RecommendationStore
            from recommendation_api.tactile_catalog import TactileCatalogService
            from recommendation_api.tactile_store import TactileStore

            store = TactileStore()
            catalog = TactileCatalogService(store, image_root=RecommendationStore().image_root)
            return frozenset(str(asin) for asin in catalog.catalog_asins)
        except Exception:
            return frozenset()

    def health(self) -> dict[str, Any]:
        return {
            "catalog_products": len(self.index),
            "catalog_mode": "full",
            "tactile_provider": self.tactile.version,
            "multimodal": {
                "status": "ok",
                "service": "full-catalog-last2-index",
                "catalog_products": len(self.index),
                "tactile_target": {
                    "model": "fashionclip_last2",
                    "classes": len(TACTILE_CLASSES),
                    "source": "image_predicted",
                },
                "review_grounded_overlay_products": len(self.tactile.curated_asins & set(self.index.asins.tolist()))
                if self.tactile.curated_asins
                else 0,
                "unsupported_concepts": list(UNSUPPORTED_CONCEPTS),
                "load_seconds": round(self.index.load_seconds, 3),
            },
        }

    def list_products(self, *, page: int, page_size: int, gender: str | None = None) -> dict[str, Any]:
        page = max(1, int(page))
        page_size = max(1, min(int(page_size), 100))
        rows = self.index.for_gender(self.index.rows_with_image, gender)
        score = self.index.popularity[rows]
        if gender in GENDERS:
            # Same rule as search: listings whose title does not say whose they are rank a little lower.
            factor = float(self.index.config["relevance"].get("gender_unknown_factor", 1.0))
            score = np.where(self.index.genders[rows] == GENDER_UNKNOWN, score * factor, score)
        order = rows[np.lexsort((self.index.asins[rows], -score))]
        total = len(order)
        start = (page - 1) * page_size
        window = order[start : start + page_size]
        items = [
            {
                "product_id": str(self.index.asins[row]),
                "title": str(self.index.titles[row]),
                "category": str(self.index.categories[row]),
                "image_url": f"/images/{self.index.asins[row]}.jpg",
                "remote_image_url": str(self.index.image_urls[row]),
                "train_interaction_count": int(self.index.train_counts[row]),
            }
            for row in window
        ]
        total_pages = (total + page_size - 1) // page_size
        return {
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": total_pages,
            "has_previous": page > 1,
            "has_next": page < total_pages,
            "gender": gender if gender in GENDERS else None,
        }

    def product_exists(self, product_id: str) -> bool:
        return self.index.exists(product_id)

    def public_product(self, product_id: str) -> dict[str, Any]:
        row = self.index.row_of(product_id)
        return {
            "product_id": product_id,
            "title": str(self.index.titles[row]),
            "category": str(self.index.categories[row]),
            "image_url": f"/images/{product_id}.jpg",
            "remote_image_url": str(self.index.image_urls[row]),
            "train_interaction_count": int(self.index.train_counts[row]),
            "tactile_target_source": (
                "review_grounded_overlay"
                if product_id in self.tactile.curated_asins
                else "image_predicted_last2"
            ),
        }
