from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from .agent_tools import (
    ROUTER_INSTRUCTIONS,
    TOOL_DEFINITIONS,
    gemini_function_declarations,
    openai_tool_definitions,
)
from .config import DEFAULT_CONFIG, AgentSettings
from .contracts import AgentToolCall, LLMProvider, ModelInfo
from .routing import LocalConversationRouter


SYSTEM_INSTRUCTIONS = """당신은 근거 기반 패션 쇼핑 도우미다.
제공된 상품과 개인화 근거만 사용한다. 상품명, 가격, 재고, 소재 의견을 만들지 않는다.
이미지 예측은 구매자 리뷰라고 표현하지 않는다. 결과가 없으면 없다고 말한다.
한국어로 2~4문장의 간결한 답을 작성하고 상품 순서는 바꾸지 않는다."""


def _post_json(url: str, payload: dict[str, Any], headers: dict[str, str], timeout: int) -> dict[str, Any]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = Request(
        url,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json", **headers},
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read(2 * 1024 * 1024)
    except HTTPError as exc:
        detail = exc.read(4096).decode("utf-8", errors="replace")
        raise RuntimeError(f"LLM API returned HTTP {exc.code}: {detail}") from exc
    except (URLError, TimeoutError) as exc:
        raise RuntimeError(f"LLM API request failed: {exc}") from exc
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise RuntimeError("LLM API response must be a JSON object")
    return value


def _context_text(message: str, grounded_context: dict[str, Any]) -> str:
    return (
        "사용자 메시지:\n"
        + message
        + "\n\n추천 시스템의 확정된 결과(JSON):\n"
        + json.dumps(grounded_context, ensure_ascii=False, separators=(",", ":"))
    )


class DeterministicLLMProvider:
    def __init__(self, config: dict[str, Any] | None = None) -> None:
        if config is None:
            config = json.loads(DEFAULT_CONFIG.read_text(encoding="utf-8"))
        self.router = LocalConversationRouter(config)

    @property
    def info(self) -> ModelInfo:
        return ModelInfo(provider="deterministic", model_id="grounded-template-v1")

    def compose(self, *, message: str, grounded_context: dict[str, Any]) -> str:
        products = grounded_context.get("products", [])
        if not products:
            return "현재 조건에 맞는 상품을 찾지 못했습니다. 상품 종류나 원하는 조건을 조금 넓혀주세요."
        saved = int(grounded_context.get("preferences_saved", 0))
        prefix = "말씀하신 조건"
        if grounded_context.get("personalization_applied"):
            prefix += "과 저장된 취향"
        text = f"{prefix}을 반영해 관련도가 높은 상품 {len(products)}개를 찾았습니다."
        if saved:
            text += f" 이번 대화에서 확인된 취향 {saved}개도 자동으로 기억했습니다."
        text += " 각 카드의 추천 이유와 소재 근거를 확인해보세요."
        return text

    def select_tool(
        self, *, message: str, conversation_context: dict[str, Any]
    ) -> AgentToolCall:
        return self.router.select(message)


class OpenAIResponsesProvider:
    def __init__(self, *, api_key: str, model: str, timeout: int) -> None:
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    @property
    def info(self) -> ModelInfo:
        return ModelInfo(provider="openai", model_id=self.model)

    def compose(self, *, message: str, grounded_context: dict[str, Any]) -> str:
        response = _post_json(
            "https://api.openai.com/v1/responses",
            {
                "model": self.model,
                "instructions": SYSTEM_INSTRUCTIONS,
                "input": _context_text(message, grounded_context),
            },
            {"Authorization": f"Bearer {self.api_key}"},
            self.timeout,
        )
        if isinstance(response.get("output_text"), str):
            return response["output_text"].strip()
        parts: list[str] = []
        for item in response.get("output", []):
            if not isinstance(item, dict) or item.get("type") != "message":
                continue
            for content in item.get("content", []):
                if isinstance(content, dict) and content.get("type") == "output_text":
                    parts.append(str(content.get("text") or ""))
        text = "\n".join(value for value in parts if value).strip()
        if not text:
            raise RuntimeError("OpenAI response did not contain output text")
        return text

    def select_tool(
        self, *, message: str, conversation_context: dict[str, Any]
    ) -> AgentToolCall:
        response = _post_json(
            "https://api.openai.com/v1/responses",
            {
                "model": self.model,
                "instructions": ROUTER_INSTRUCTIONS,
                "input": (
                    "대화 상태(JSON):\n"
                    + json.dumps(conversation_context, ensure_ascii=False, separators=(",", ":"))
                    + "\n\n현재 사용자 메시지:\n"
                    + message
                ),
                "tools": openai_tool_definitions(),
                "tool_choice": "required",
                "parallel_tool_calls": False,
            },
            {"Authorization": f"Bearer {self.api_key}"},
            self.timeout,
        )
        for item in response.get("output", []):
            if not isinstance(item, dict) or item.get("type") != "function_call":
                continue
            raw_arguments = item.get("arguments") or "{}"
            arguments = json.loads(raw_arguments) if isinstance(raw_arguments, str) else raw_arguments
            if not isinstance(arguments, dict):
                raise RuntimeError("OpenAI tool arguments must be a JSON object")
            return AgentToolCall(
                name=str(item.get("name") or ""),
                arguments=arguments,
                source="openai_function_call",
            )
        raise RuntimeError("OpenAI response did not contain a function call")


class GeminiGenerateContentProvider:
    def __init__(self, *, api_key: str, model: str, timeout: int) -> None:
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    @property
    def info(self) -> ModelInfo:
        return ModelInfo(provider="gemini", model_id=self.model)

    def compose(self, *, message: str, grounded_context: dict[str, Any]) -> str:
        model = quote(self.model, safe="-_.")
        response = _post_json(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
            {
                "systemInstruction": {"parts": [{"text": SYSTEM_INSTRUCTIONS}]},
                "contents": [
                    {"role": "user", "parts": [{"text": _context_text(message, grounded_context)}]}
                ],
                "generationConfig": {"maxOutputTokens": 700, "temperature": 0.1},
            },
            {"x-goog-api-key": self.api_key},
            self.timeout,
        )
        parts: list[str] = []
        for candidate in response.get("candidates", []):
            content = candidate.get("content", {}) if isinstance(candidate, dict) else {}
            for part in content.get("parts", []):
                if isinstance(part, dict) and isinstance(part.get("text"), str):
                    parts.append(part["text"])
        text = "\n".join(parts).strip()
        if not text:
            raise RuntimeError("Gemini response did not contain output text")
        return text

    def select_tool(
        self, *, message: str, conversation_context: dict[str, Any]
    ) -> AgentToolCall:
        model = quote(self.model, safe="-_.")
        response = _post_json(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
            {
                "systemInstruction": {"parts": [{"text": ROUTER_INSTRUCTIONS}]},
                "contents": [
                    {
                        "role": "user",
                        "parts": [
                            {
                                "text": (
                                    "대화 상태(JSON):\n"
                                    + json.dumps(
                                        conversation_context,
                                        ensure_ascii=False,
                                        separators=(",", ":"),
                                    )
                                    + "\n\n현재 사용자 메시지:\n"
                                    + message
                                )
                            }
                        ],
                    }
                ],
                "tools": [
                    {"functionDeclarations": gemini_function_declarations()}
                ],
                "toolConfig": {
                    "functionCallingConfig": {
                        "mode": "ANY",
                        "allowedFunctionNames": [item["name"] for item in TOOL_DEFINITIONS],
                    }
                },
                "generationConfig": {"temperature": 0.0},
            },
            {"x-goog-api-key": self.api_key},
            self.timeout,
        )
        for candidate in response.get("candidates", []):
            content = candidate.get("content", {}) if isinstance(candidate, dict) else {}
            for part in content.get("parts", []):
                call = part.get("functionCall") if isinstance(part, dict) else None
                if not isinstance(call, dict):
                    continue
                arguments = call.get("args") or {}
                if not isinstance(arguments, dict):
                    raise RuntimeError("Gemini tool arguments must be a JSON object")
                return AgentToolCall(
                    name=str(call.get("name") or ""),
                    arguments=arguments,
                    source="gemini_function_call",
                )
        raise RuntimeError("Gemini response did not contain a function call")


class ResilientLLMProvider:
    """Use the selected remote provider, but never make product retrieval depend on it."""

    def __init__(self, primary: LLMProvider, fallback: LLMProvider | None = None) -> None:
        self.primary = primary
        self.fallback = fallback or DeterministicLLMProvider()
        self.last_error: str | None = None
        self.last_route_error: str | None = None

    @property
    def info(self) -> ModelInfo:
        return self.primary.info

    def compose(self, *, message: str, grounded_context: dict[str, Any]) -> str:
        try:
            self.last_error = None
            return self.primary.compose(message=message, grounded_context=grounded_context)
        except Exception as exc:
            self.last_error = str(exc)
            return self.fallback.compose(message=message, grounded_context=grounded_context)

    def select_tool(
        self, *, message: str, conversation_context: dict[str, Any]
    ) -> AgentToolCall:
        try:
            self.last_route_error = None
            call = self.primary.select_tool(
                message=message, conversation_context=conversation_context
            )
            allowed = {str(item["name"]) for item in TOOL_DEFINITIONS}
            if call.name not in allowed:
                raise RuntimeError(f"Model selected an unregistered tool: {call.name}")
            return call
        except Exception as exc:
            self.last_route_error = str(exc)
            call = self.fallback.select_tool(
                message=message, conversation_context=conversation_context
            )
            allowed = {str(item["name"]) for item in TOOL_DEFINITIONS}
            if call.name not in allowed:
                raise RuntimeError(f"Fallback selected an unregistered tool: {call.name}")
            return call


def build_llm_provider(settings: AgentSettings) -> ResilientLLMProvider:
    timeout = int(settings.config["llm"]["timeout_seconds"])
    fallback = DeterministicLLMProvider(settings.config)
    if settings.llm_provider == "openai":
        primary: LLMProvider = OpenAIResponsesProvider(
            api_key=settings.openai_api_key,
            model=settings.openai_model,
            timeout=timeout,
        )
    elif settings.llm_provider == "gemini":
        primary = GeminiGenerateContentProvider(
            api_key=settings.gemini_api_key,
            model=settings.gemini_model,
            timeout=timeout,
        )
    else:
        primary = fallback
    return ResilientLLMProvider(primary, fallback=fallback)
