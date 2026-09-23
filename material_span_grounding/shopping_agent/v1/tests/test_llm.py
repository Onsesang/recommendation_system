from __future__ import annotations

import unittest
from unittest.mock import patch

from shopping_agent.v1.llm import (
    GeminiGenerateContentProvider,
    OpenAIResponsesProvider,
    ResilientLLMProvider,
)


class LLMProviderTests(unittest.TestCase):
    @patch("shopping_agent.v1.llm._post_json")
    def test_openai_responses_contract(self, post) -> None:
        post.return_value = {"output": [{"type": "message", "content": [{"type": "output_text", "text": "추천 결과입니다."}]}]}
        provider = OpenAIResponsesProvider(api_key="secret", model="gpt-test", timeout=3)
        text = provider.compose(message="추천", grounded_context={"products": []})
        self.assertEqual(text, "추천 결과입니다.")
        url, payload, headers, timeout = post.call_args.args
        self.assertEqual(url, "https://api.openai.com/v1/responses")
        self.assertEqual(payload["model"], "gpt-test")
        self.assertEqual(headers["Authorization"], "Bearer secret")
        self.assertNotIn("secret", str(payload))

    @patch("shopping_agent.v1.llm._post_json")
    def test_openai_required_tool_call_contract(self, post) -> None:
        post.return_value = {
            "output": [
                {
                    "type": "function_call",
                    "name": "respond_out_of_scope",
                    "arguments": "{}",
                    "call_id": "call_1",
                }
            ]
        }
        provider = OpenAIResponsesProvider(api_key="secret", model="gpt-test", timeout=3)
        call = provider.select_tool(message="날씨 알려줘", conversation_context={})
        self.assertEqual(call.name, "respond_out_of_scope")
        url, payload, headers, timeout = post.call_args.args
        self.assertEqual(payload["tool_choice"], "required")
        self.assertFalse(payload["parallel_tool_calls"])
        self.assertEqual({tool["name"] for tool in payload["tools"]}, {
            "respond_greeting", "respond_out_of_scope", "search_products"
        })
        self.assertTrue(all(tool["strict"] for tool in payload["tools"]))

    @patch("shopping_agent.v1.llm._post_json")
    def test_gemini_generate_content_contract(self, post) -> None:
        post.return_value = {"candidates": [{"content": {"parts": [{"text": "Gemini 추천"}]}}]}
        provider = GeminiGenerateContentProvider(api_key="secret", model="gemini-test", timeout=3)
        self.assertEqual(provider.compose(message="추천", grounded_context={}), "Gemini 추천")
        url, payload, headers, timeout = post.call_args.args
        self.assertIn("gemini-test:generateContent", url)
        self.assertEqual(headers["x-goog-api-key"], "secret")
        self.assertNotIn("secret", str(payload))

    @patch("shopping_agent.v1.llm._post_json")
    def test_gemini_required_tool_call_contract(self, post) -> None:
        post.return_value = {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {
                                "functionCall": {
                                    "name": "search_products",
                                    "args": {"query_text": "검정 원피스"},
                                }
                            }
                        ]
                    }
                }
            ]
        }
        provider = GeminiGenerateContentProvider(api_key="secret", model="gemini-test", timeout=3)
        call = provider.select_tool(message="검정 원피스", conversation_context={})
        self.assertEqual(call.name, "search_products")
        url, payload, headers, timeout = post.call_args.args
        function_config = payload["toolConfig"]["functionCallingConfig"]
        self.assertEqual(function_config["mode"], "ANY")
        self.assertIn("search_products", function_config["allowedFunctionNames"])

    def test_remote_failure_uses_grounded_fallback(self) -> None:
        class Broken:
            info = type("Info", (), {"provider": "broken", "model_id": "broken"})()
            def compose(self, **kwargs):
                raise RuntimeError("offline")
        provider = ResilientLLMProvider(Broken())
        text = provider.compose(message="추천", grounded_context={"products": [{"product_id": "A"}]})
        self.assertIn("1개", text)
        self.assertEqual(provider.last_error, "offline")

    def test_remote_router_failure_uses_local_tool_model(self) -> None:
        class Broken:
            info = type("Info", (), {"provider": "broken", "model_id": "broken"})()

            def compose(self, **kwargs):
                raise RuntimeError("offline")

            def select_tool(self, **kwargs):
                raise RuntimeError("router offline")

        provider = ResilientLLMProvider(Broken())
        call = provider.select_tool(message="오늘 날씨 알려줘", conversation_context={})
        self.assertEqual(call.name, "respond_out_of_scope")
        self.assertEqual(call.source, "local_intent_model")
        self.assertEqual(provider.last_route_error, "router offline")


if __name__ == "__main__":
    unittest.main()
