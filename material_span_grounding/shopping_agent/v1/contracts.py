from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from recommendation_api.tactile_models import TactileIntent


@dataclass(frozen=True)
class ModelInfo:
    provider: str
    model_id: str
    contract_version: str = "shopping-agent-llm-v1"


@dataclass
class AgentRun:
    trace_id: str
    session_id: str
    user_id: str
    message: str
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    model_versions: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class AgentToolCall:
    name: str
    arguments: dict[str, Any]
    source: str
    confidence: float | None = None


class LLMProvider(Protocol):
    @property
    def info(self) -> ModelInfo: ...

    def compose(self, *, message: str, grounded_context: dict[str, Any]) -> str: ...

    def select_tool(self, *, message: str, conversation_context: dict[str, Any]) -> AgentToolCall: ...


class TactileProvider(Protocol):
    @property
    def version(self) -> str: ...

    def search(self, query_text: str, *, limit: int) -> dict[str, Any]: ...

    def tactile_scores(
        self,
        candidates: list[dict[str, Any]],
        intent: TactileIntent,
    ) -> dict[str, dict[str, Any]]: ...

    def product_detail(self, product_id: str) -> dict[str, Any]: ...
