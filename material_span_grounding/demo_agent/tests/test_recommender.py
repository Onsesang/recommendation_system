from dataclasses import replace

import pandas as pd
import pytest

from demo_agent.config import DemoConfig
from demo_agent.models import Constraint, StructuredQuery, TACTILE_CLASSES
from demo_agent.recommender import ExplicitTactileRecommender


def fixture_recommender() -> ExplicitTactileRecommender:
    metadata = pd.DataFrame(
        {
            "iid": [0, 1, 2, 3, 4],
            "parent_asin": ["A", "B", "C", "D", "E"],
            "train_count": [3, 5, 8, 2, 1],
            "title": ["Soft Shirt", "Cool Shirt", "Warm Jacket", "Knit Sweater", "Jeans Pants"],
            "category": ["top", "top", "outerwear", "sweater", "pants"],
            "image_url": ["https://example.test/image.jpg"] * 5,
        }
    )
    values = {name: [0.5] * 5 for name in TACTILE_CLASSES}
    values.update(
        {
            "soft": [0.9, 0.4, 0.2, 0.8, 0.3],
            "thin": [0.8, 0.9, 0.2, 0.4, 0.5],
            "rough": [0.1, 0.7, 0.4, 0.2, 0.6],
        }
    )
    profiles = pd.DataFrame({"iid": metadata.iid, "parent_asin": metadata.parent_asin, **values})
    config = replace(
        DemoConfig.load(),
        default_top_k=3,
        maximum_top_k=5,
        specific_category_min_candidates=1,
        initial_catalog_size=3,
    )
    return ExplicitTactileRecommender(config, metadata=metadata, profiles=profiles)


def test_vectorized_positive_and_negative_formula_and_category() -> None:
    recommender = fixture_recommender()
    query = StructuredQuery(
        category="shirt",
        constraints=(Constraint("soft"), Constraint("thin")),
        negative_constraints=(Constraint("rough"),),
    )
    response = recommender.recommend(query, top_k=2)
    assert response["retrieval"]["candidate_count"] == 2
    assert [row["item_id"] for row in response["products"]] == ["A", "B"]
    assert response["products"][0]["score"] == pytest.approx((0.9 + 0.8 + 0.9) / 3)


def test_reason_numbers_are_checked_against_original_matrix() -> None:
    recommender = fixture_recommender()
    response = recommender.recommend(
        StructuredQuery(constraints=(Constraint("soft"),)), top_k=2
    )
    for product in response["products"]:
        recommender.validate_reason(product)
    response["products"][0]["reason_evidence"][0]["raw_probability"] = 0.123
    with pytest.raises(AssertionError, match="reason probability mismatch"):
        recommender.validate_reason(response["products"][0])


def test_initial_screen_uses_popularity_without_claiming_tactile_match() -> None:
    response = fixture_recommender().initial_recommendations()
    assert [row["item_id"] for row in response["products"]] == ["C", "B", "A"]
    assert all(row["tactile_match"] is None for row in response["products"])
    assert response["retrieval"]["ranking_mode"] == "initial_popularity"
