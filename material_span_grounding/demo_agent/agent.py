from __future__ import annotations

from typing import Any, Callable, Mapping

from .config import DemoConfig
from .models import StructuredQuery
from .recommender import CATEGORY_LABELS_KO, TACTILE_LABELS_KO, ExplicitTactileRecommender
from .tactile_parser import parse_message


RemoteParser = Callable[[str, StructuredQuery | None], Mapping[str, Any]]


class TactileAgent:
    """Conversation state + optional LLM parse with deterministic failover."""

    def __init__(
        self,
        recommender: ExplicitTactileRecommender,
        *,
        config: DemoConfig | None = None,
        remote_parser: RemoteParser | None = None,
    ) -> None:
        self.recommender = recommender
        self.config = config or recommender.config
        self.remote_parser = remote_parser

    def handle(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, Mapping):
            raise ValueError("payload must be an object")
        message = str(payload.get("message") or "").strip()
        if not message:
            raise ValueError("message must be a non-empty string")
        if len(message) > self.config.maximum_message_characters:
            raise ValueError(
                f"message must be at most {self.config.maximum_message_characters} characters"
            )
        previous_raw = payload.get("conversation_state") or {}
        if not isinstance(previous_raw, Mapping):
            raise ValueError("conversation_state must be an object")
        previous = (
            StructuredQuery.from_mapping(previous_raw, source="agent_context")
            if previous_raw and (previous_raw.get("category") or previous_raw.get("constraints") or previous_raw.get("negative_constraints"))
            else None
        )

        parser_fallback_reason = None
        if self.remote_parser is not None:
            try:
                remote = dict(self.remote_parser(message, previous))
                remote["original_message"] = message
                query = StructuredQuery.from_mapping(remote, source="llm_structured")
            except Exception as exc:
                parser_fallback_reason = type(exc).__name__
                query = parse_message(
                    message,
                    previous=previous,
                    default_weight=self.config.default_constraint_weight,
                )
        else:
            query = parse_message(
                message,
                previous=previous,
                default_weight=self.config.default_constraint_weight,
            )

        result = self.recommender.recommend(
            query, top_k=int(payload.get("top_k", self.config.default_top_k))
        )
        result["assistant_message"] = self._assistant_message(query, result)
        result["conversation_state"] = query.public_dict()
        result["parser"] = {
            "source": query.source,
            "fallback_used": parser_fallback_reason is not None,
            "fallback_reason_type": parser_fallback_reason,
        }
        return result

    @staticmethod
    def _assistant_message(query: StructuredQuery, result: Mapping[str, Any]) -> str:
        category = CATEGORY_LABELS_KO.get(query.category or "", "옷")
        terms = [TACTILE_LABELS_KO[item.tactile_class] for item in query.constraints]
        terms.extend(
            f"{TACTILE_LABELS_KO[item.tactile_class]} 제외"
            for item in query.negative_constraints
        )
        if not query.has_tactile_constraints:
            if query.category:
                return f"{category} 조건은 확인했어요. 원하는 촉감을 더 말씀해 주세요."
            return "원하는 옷 종류와 촉감을 함께 말씀해 주세요."
        description = "·".join(terms)
        count = int(result.get("result_count", 0))
        if not count:
            return f"{category} 중 {description} 조건에 맞는 상품을 찾지 못했어요. 조건을 조금 넓혀주세요."
        relaxed = bool(result.get("retrieval", {}).get("specific_category_relaxed"))
        suffix = " 세부 종류 후보가 적어 상위 카테고리까지 넓혔어요." if relaxed else ""
        return f"{description} 특징을 기준으로 {category} {count}개를 찾았어요.{suffix}"
