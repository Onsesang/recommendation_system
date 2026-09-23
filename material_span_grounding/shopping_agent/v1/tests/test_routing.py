from __future__ import annotations

import json
import unittest

from shopping_agent.v1.agent_tools import ConversationToolRegistry
from shopping_agent.v1.config import DEFAULT_CONFIG
from shopping_agent.v1.contracts import AgentToolCall
from shopping_agent.v1.routing import LocalConversationRouter


class ConversationRoutingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.config = json.loads(DEFAULT_CONFIG.read_text(encoding="utf-8"))
        cls.router = LocalConversationRouter(cls.config)

    def test_local_model_selects_each_registered_tool(self) -> None:
        cases = {
            "안녕": "respond_greeting",
            "오늘 날씨 어때?": "respond_out_of_scope",
            "부드럽고 비치지 않는 바지를 찾아줘": "search_products",
        }
        for message, expected in cases.items():
            with self.subTest(message=message):
                call = self.router.select(message)
                self.assertEqual(call.name, expected)
                self.assertGreater(call.confidence or 0.0, 0.5)

    def test_shopping_request_wins_when_greeting_is_mixed(self) -> None:
        call = self.router.select("안녕, 검정색 원피스를 찾아줘")
        self.assertEqual(call.name, "search_products")

    def test_registry_uses_exact_user_message_and_rejects_unknown_tool(self) -> None:
        registry = ConversationToolRegistry(self.config)
        call = AgentToolCall(
            name="search_products",
            arguments={"query_text": "모델이 바꾼 문장"},
            source="test",
        )
        result = registry.execute(call, user_message="사용자의 정확한 요청")
        self.assertEqual(result["query_text"], "사용자의 정확한 요청")
        with self.assertRaises(ValueError):
            registry.execute(
                AgentToolCall(name="get_weather", arguments={}, source="test"),
                user_message="서울 날씨",
            )


if __name__ == "__main__":
    unittest.main()
