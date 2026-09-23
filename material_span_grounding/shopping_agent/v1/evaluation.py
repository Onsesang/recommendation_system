from __future__ import annotations

import argparse
import json
import math
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from .config import AgentSettings
from .database import iso_now
from .server import AgentApplication


def evaluate() -> dict[str, Any]:
    """Deterministic structural evaluation path for every personalization ranking change."""
    with TemporaryDirectory() as temporary:
        settings = replace(
            AgentSettings.load(),
            database_path=Path(temporary) / "evaluation.sqlite3",
            llm_provider="deterministic",
            openai_api_key="",
            gemini_api_key="",
        )
        app = AgentApplication(settings)
        login = app.auth.register(
            email="offline-eval@example.com",
            password="offline-eval-password",
            display_name="Offline Eval",
        )
        user_id = login.user["user_id"]
        session = app.agent.create_session(user_id)
        first = app.agent.message(
            user_id,
            session["session_id"],
            "부드럽고 비치지 않는 바지를 찾아줘",
            limit=10,
        )
        anchor_id = first["products"][0]["product_id"]
        created = app.database.record_event(
            user_id,
            event_id="offline-eval-event",
            event_type="explicit_like",
            product_id=anchor_id,
            session_id=session["session_id"],
            context={"fixture": True},
        )
        duplicate_created = app.database.record_event(
            user_id,
            event_id="offline-eval-event",
            event_type="explicit_like",
            product_id=anchor_id,
            session_id=session["session_id"],
            context={"fixture": True},
        )
        app.database.add_cart_item(user_id, anchor_id)
        second = app.agent.message(
            user_id,
            session["session_id"],
            "최근 취향을 반영해서 다시 추천해줘",
            limit=10,
        )
        routing_session = app.agent.create_session(user_id)
        preferences_before_routing = len(app.database.list_preferences(user_id))
        greeting = app.agent.message(
            user_id, routing_session["session_id"], "안녕", limit=10
        )
        off_topic = app.agent.message(
            user_id, routing_session["session_id"], "오늘 날씨 어때?", limit=10
        )
        preferences_after_routing = len(app.database.list_preferences(user_id))
        products = second["products"]
        finite = [math.isfinite(float(row["personalized_score"])) for row in products]
        breakdown = [
            "personalization_weighted" in row.get("score_breakdown", {}) for row in products
        ]
        catalog_ids = set(app.tools.catalog.catalog_asins)
        result_ids = [row["product_id"] for row in products]
        category = second["intent"]["category"]
        category_rate = sum(row["category"] == category for row in products) / max(1, len(products))
        return {
            "status": "complete",
            "generated_at": iso_now(),
            "protocol": "deterministic real-catalog structural personalization evaluation v1",
            "warning": "Structural checks are not human relevance or online A/B metrics.",
            "cases": 4,
            "metrics": {
                "finite_score_rate": sum(finite) / max(1, len(finite)),
                "score_breakdown_rate": sum(breakdown) / max(1, len(breakdown)),
                "catalog_consistency_rate": sum(value in catalog_ids for value in result_ids) / max(1, len(result_ids)),
                "same_category_constraint_rate": category_rate,
                "event_idempotency_pass": created and not duplicate_created,
                "chat_preference_saved": bool(app.database.list_preferences(user_id)),
                "behavior_personalization_applied": second["profile_summary"]["behavior_event_count"] > 0,
                "cart_personalization_applied": second["profile_summary"]["cart_item_count"] > 0,
                "hallucinated_product_count": sum(value not in catalog_ids for value in result_ids),
                "checkout_enabled": False,
                "greeting_tool_pass": greeting["action"] == "respond_greeting",
                "out_of_scope_tool_pass": off_topic["action"] == "respond_out_of_scope",
                "non_shopping_search_suppressed": not greeting["products"] and not off_topic["products"],
                "non_shopping_preference_unchanged": preferences_before_routing == preferences_after_routing,
            },
        }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("shopping_agent/evaluation/v1.json"),
    )
    args = parser.parse_args()
    result = evaluate()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
