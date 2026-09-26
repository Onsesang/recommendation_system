from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from shopping_agent.v1.config import AgentSettings
from shopping_agent.v1.server import AgentApplication
from shopping_agent.v1.tool_agent import TOOL_NAMES, OpenAIToolLoop


def _call(name: str, arguments: dict, call_id: str = "call_1") -> dict:
    return {"type": "function_call", "name": name, "arguments": json.dumps(arguments), "call_id": call_id}


def _answer(text: str) -> dict:
    return {"type": "message", "content": [{"type": "output_text", "text": text}]}


SEARCH_ARGUMENTS = {
    "query_text": "안 까끌하고 얇은 여름 원피스",
    "category": "dress",
    "want": ["thin", "cool"],
    "avoid": ["rough"],
    "keywords": ["summer", "dress"],
    "unsupported_concepts": [],
}


class ToolLoopContractTests(unittest.TestCase):
    def loop(self, **overrides) -> OpenAIToolLoop:
        values = dict(api_key="secret", model="gpt-test", timeout=3, max_steps=5,
                      max_output_tokens=300, reasoning_effort="low")
        values.update(overrides)
        return OpenAIToolLoop(**values)

    @patch("shopping_agent.v1.tool_agent._post_json")
    def test_tool_call_round_trip_uses_previous_response_id(self, post) -> None:
        post.side_effect = [
            {"id": "resp_1", "output": [_call("view_cart", {})]},
            {"id": "resp_2", "output": [_answer("장바구니가 비어 있습니다.")]},
        ]
        executed = []
        result = self.loop().run(
            instructions="지침",
            input_items=[{"role": "user", "content": "장바구니 보여줘"}],
            execute=lambda name, arguments: executed.append(name) or {"item_count": 0, "items": []},
        )
        self.assertEqual(result.text, "장바구니가 비어 있습니다.")
        self.assertEqual(executed, ["view_cart"])
        self.assertEqual(result.calls, [{"name": "view_cart", "arguments": {}, "ok": True}])
        first, second = (call.args[1] for call in post.call_args_list)
        self.assertEqual({tool["name"] for tool in first["tools"]}, set(TOOL_NAMES))
        self.assertTrue(all(tool["strict"] for tool in first["tools"]))
        self.assertFalse(first["parallel_tool_calls"])
        self.assertEqual(first["reasoning"], {"effort": "low"})
        self.assertNotIn("secret", json.dumps(first))
        self.assertEqual(second["previous_response_id"], "resp_1")
        self.assertEqual(second["input"][0]["type"], "function_call_output")
        self.assertEqual(second["input"][0]["call_id"], "call_1")
        self.assertEqual(second["instructions"], "지침")

    @patch("shopping_agent.v1.tool_agent._post_json")
    def test_last_step_forces_an_answer(self, post) -> None:
        post.side_effect = [
            {"id": "resp_1", "output": [_call("view_cart", {})]},
            {"id": "resp_2", "output": [_answer("답변")]},
        ]
        self.loop(max_steps=2).run(
            instructions="지침", input_items=[], execute=lambda name, arguments: {"items": []}
        )
        self.assertNotIn("tool_choice", post.call_args_list[0].args[1])
        self.assertEqual(post.call_args_list[1].args[1]["tool_choice"], "none")

    @patch("shopping_agent.v1.tool_agent._post_json")
    def test_invalid_arguments_are_returned_to_the_model(self, post) -> None:
        post.side_effect = [
            {"id": "resp_1", "output": [_call("get_product_detail", {"product_id": "NOPE"})]},
            {"id": "resp_2", "output": [_answer("그 상품은 찾을 수 없습니다.")]},
        ]

        def execute(name, arguments):
            raise KeyError("Unknown product_id: NOPE")

        result = self.loop().run(instructions="지침", input_items=[], execute=execute)
        self.assertFalse(result.calls[0]["ok"])
        output = json.loads(post.call_args_list[1].args[1]["input"][0]["output"])
        self.assertIn("Unknown product_id", output["error"])


class ToolAgentServiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temporary = tempfile.TemporaryDirectory()
        settings = replace(
            AgentSettings.load(),
            database_path=Path(cls.temporary.name) / "agent.sqlite3",
            llm_provider="openai",
            openai_api_key="test-key",
            openai_model="gpt-test",
            catalog_mode="full",
            langsmith_tracing=False,
        )
        cls.app = AgentApplication(settings)
        login = cls.app.auth.register(email="tool@example.com", password="password123", display_name="도구")
        cls.user_id = login.user["user_id"]

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temporary.cleanup()

    def session(self) -> str:
        return self.app.agent.create_session(self.user_id)["session_id"]

    @patch("shopping_agent.v1.tool_agent._post_json")
    def test_structured_search_then_cart_by_position(self, post) -> None:
        session_id = self.session()
        post.side_effect = [
            {"id": "resp_1", "output": [_call("search_products", SEARCH_ARGUMENTS)]},
            {"id": "resp_2", "output": [_answer("1번은 얇은 원피스입니다.")]},
        ]
        result = self.app.agent.message(self.user_id, session_id, "안 까끌하고 얇은 여름 원피스 찾아줘")
        self.assertEqual(result["action"], "search_products")
        self.assertEqual(result["routing"]["source"], "openai_tool_loop")
        self.assertTrue(result["products"])
        self.assertEqual(result["intent"]["category"], "dress")
        self.assertIn("thin", result["intent"]["desired_more"])
        self.assertIn("rough", result["intent"]["avoid"])
        self.assertIn("personalization_weighted", result["products"][0]["score_breakdown"])
        tool_output = json.loads(post.call_args_list[1].args[1]["input"][0]["output"])
        self.assertEqual(tool_output["products"][0]["number"], 1)
        self.assertEqual(set(tool_output["products"][0]["requested_tactile"]), {"thin", "cool", "rough"})
        self.assertEqual(tool_output["products"][0]["evidence_source"], result["products"][0]["tactile_target_source"])

        second_id = result["products"][1]["product_id"]
        post.side_effect = [
            {"id": "resp_3", "output": [_call("add_to_cart", {"product_id": second_id, "quantity": 1})]},
            {"id": "resp_4", "output": [_answer("2번 상품을 담았습니다.")]},
        ]
        cart_turn = self.app.agent.message(self.user_id, session_id, "두 번째 거 담아줘")
        self.assertTrue(cart_turn["cart_updated"])
        self.assertEqual(cart_turn["action"], "add_to_cart")
        self.assertEqual(cart_turn["products"], [])
        instructions = post.call_args_list[2].args[1]["instructions"]
        self.assertIn(second_id, instructions)
        self.assertIn('"last_search"', instructions)
        self.assertIn(second_id, [row["product_id"] for row in self.app.database.list_cart(self.user_id)])

    @patch("shopping_agent.v1.tool_agent._post_json")
    def test_cart_rejects_products_never_shown(self, post) -> None:
        session_id = self.session()
        unseen = str(self.app.tools.tactile.index.asins[-1])
        before = len(self.app.database.list_cart(self.user_id))
        post.side_effect = [
            {"id": "resp_1", "output": [_call("add_to_cart", {"product_id": unseen, "quantity": 1})]},
            {"id": "resp_2", "output": [_answer("어떤 상품인지 먼저 알려주세요.")]},
        ]
        result = self.app.agent.message(self.user_id, session_id, "아무거나 담아줘")
        self.assertFalse(result["cart_updated"])
        self.assertFalse(result["tool_calls"][0]["ok"])
        self.assertEqual(len(self.app.database.list_cart(self.user_id)), before)

    @patch("shopping_agent.v1.tool_agent._post_json")
    def test_greeting_answers_without_tools(self, post) -> None:
        post.side_effect = [{"id": "resp_1", "output": [_answer("안녕하세요. 어떤 옷을 찾으세요?")]}]
        session_id = self.session()
        result = self.app.agent.message(self.user_id, session_id, "안녕")
        self.assertEqual(result["action"], "respond")
        self.assertEqual(result["tool_calls"], [])
        self.assertFalse(result["products"])
        # A turn without a search must leave the session usable for the next turn.
        post.side_effect = [
            {"id": "resp_2", "output": [_call("search_products", SEARCH_ARGUMENTS)]},
            {"id": "resp_3", "output": [_answer("찾았습니다.")]},
        ]
        follow_up = self.app.agent.message(self.user_id, session_id, "얇은 원피스 찾아줘")
        self.assertEqual(follow_up["action"], "search_products")

    @patch("shopping_agent.v1.tool_agent._post_json")
    def test_remote_failure_falls_back_to_local_router(self, post) -> None:
        post.side_effect = RuntimeError("LLM API request failed: timeout")
        result = self.app.agent.message(self.user_id, self.session(), "부드러운 바지 찾아줘")
        self.assertEqual(result["action"], "search_products")
        self.assertTrue(result["products"])
        self.assertEqual(result["provenance"]["llm_provider"], "deterministic")
        self.assertEqual(result["routing"]["source"], "local_intent_model")

    def test_health_reports_tool_loop(self) -> None:
        features = self.app.health()["features"]
        self.assertEqual(features["agent_mode"], "openai_tool_loop")
        self.assertEqual(set(features["agent_tools"]), set(TOOL_NAMES))


if __name__ == "__main__":
    unittest.main()
