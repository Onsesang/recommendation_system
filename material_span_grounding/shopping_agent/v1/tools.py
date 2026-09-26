from __future__ import annotations

from typing import Any

from recommendation_api.store import RecommendationStore
from recommendation_api.tactile_catalog import TactileCatalogService
from recommendation_api.tactile_comparison import TactileComparisonService
from recommendation_api.tactile_concerns import TactileConcernDetector
from recommendation_api.tactile_description import TactileDescriptionService
from recommendation_api.tactile_models import TactileIntent
from recommendation_api.tactile_ranking import TactileRankingService
from recommendation_api.tactile_store import TactileStore


class CurrentTactileProvider:
    """Adapter that hides current Ridge/BGE/FashionCLIP artifacts from the Agent contract."""

    def __init__(self, store: TactileStore, catalog: TactileCatalogService) -> None:
        self.store = store
        self.catalog = catalog
        self.ranking = TactileRankingService(store)
        self.description = TactileDescriptionService(store)
        self.concerns = TactileConcernDetector(store)
        self.comparison = TactileComparisonService(store)

    @property
    def version(self) -> str:
        return "review-image-hybrid-ridge-v1"

    def search(
        self,
        query_text: str,
        *,
        limit: int,
        structured: Any = None,
        keywords: list[str] | None = None,
    ) -> dict[str, Any]:
        # The curated catalog parses open-vocabulary spans itself; Last2 structure does not apply.
        return self.catalog.search(
            {"query_text": query_text, "page": 1, "page_size": limit}
        )

    def tactile_scores(
        self,
        candidates: list[dict[str, Any]],
        intent: TactileIntent,
    ) -> dict[str, dict[str, Any]]:
        if not candidates:
            return {}
        payload = self.ranking.rerank(
            candidates=[
                {
                    "product_id": str(row["product_id"]),
                    "base_score": float(row.get("relevance_score", 0.0)),
                }
                for row in candidates
            ],
            strategy="context_gated",
            intent=intent,
            top_k=len(candidates),
        )
        return {str(row["product_id"]): row for row in payload["results"]}

    def product_detail(self, product_id: str) -> dict[str, Any]:
        if product_id not in self.catalog.product_metadata:
            raise KeyError(f"Unknown product_id: {product_id}")
        return {
            "product": self.catalog._public_product(product_id),
            "profile": self.store.profile(product_id, include_claims=False),
            "tactile_summary": self.description.describe(product_id),
            "tactile_concerns": self.concerns.detect(product_id),
            "related": self.catalog.related(product_id, limit=10),
        }

    def compare(self, product_ids: list[str]) -> dict[str, Any]:
        return self.comparison.compare(product_ids)


class ShoppingTools:
    def __init__(self) -> None:
        self.legacy_store = RecommendationStore()
        self.tactile_store = TactileStore()
        self.catalog = TactileCatalogService(
            self.tactile_store, image_root=self.legacy_store.image_root
        )
        self.tactile = CurrentTactileProvider(self.tactile_store, self.catalog)

    def health(self) -> dict[str, Any]:
        return {
            "status": "ok",
            "catalog_products": len(self.catalog.catalog_asins),
            "tactile_provider": self.tactile.version,
            "multimodal": self.catalog.multimodal_health(),
        }

    def list_products(self, *, page: int, page_size: int) -> dict[str, Any]:
        return self.catalog.catalog(page=page, page_size=page_size)

    def product_exists(self, product_id: str) -> bool:
        return product_id in self.catalog.product_metadata

    def public_product(self, product_id: str) -> dict[str, Any]:
        if not self.product_exists(product_id):
            raise KeyError(f"Unknown product_id: {product_id}")
        return self.catalog._public_product(product_id)

