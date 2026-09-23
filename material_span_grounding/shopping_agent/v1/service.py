from __future__ import annotations

from typing import Any

from recommendation_api.tactile_agent import intent_from_mapping

from .agent_tools import ConversationToolRegistry, SHOPPING_TOOL
from .contracts import AgentToolCall
from .database import AgentDatabase
from .llm import ResilientLLMProvider
from .personalization import PersonalizedRanker
from .preferences import PreferenceService
from .tools import ShoppingTools
from .tracing import Trace, TraceRecorder


class ShoppingAgentService:
    def __init__(
        self,
        database: AgentDatabase,
        tools: ShoppingTools,
        preferences: PreferenceService,
        ranker: PersonalizedRanker,
        llm: ResilientLLMProvider,
        tracer: TraceRecorder,
        config: dict[str, Any],
    ) -> None:
        self.database = database
        self.tools = tools
        self.preferences = preferences
        self.ranker = ranker
        self.llm = llm
        self.tracer = tracer
        self.config = config
        self.conversation_tools = ConversationToolRegistry(config)

    def create_session(self, user_id: str) -> dict[str, Any]:
        return self.database.create_agent_session(user_id)

    def session(self, user_id: str, session_id: str) -> dict[str, Any]:
        value = self.database.get_agent_session(session_id, user_id)
        if value is None:
            raise KeyError("Agent session not found")
        value["messages"] = self.database.list_messages(session_id)
        return value

    def message(
        self,
        user_id: str,
        session_id: str,
        message: str,
        *,
        limit: int | None = None,
    ) -> dict[str, Any]:
        text = str(message).strip()
        if not text:
            raise ValueError("message must be a non-empty string")
        if len(text) > 4000:
            raise ValueError("message must be at most 4000 characters")
        session = self.database.get_agent_session(session_id, user_id)
        if session is None:
            raise KeyError("Agent session not found")
        state = session["state"]
        previous = intent_from_mapping(state.get("intent")) if state.get("intent") else None
        trace = self.tracer.start(
            name="shopping_agent_v1",
            session_id=session_id,
            inputs={"message": text, "turn_count": int(state.get("turn_count", 0)) + 1},
        )
        try:
            self.database.add_message(session_id, role="user", content=text)
            tool_call = self.llm.select_tool(
                message=text,
                conversation_context={
                    "previous_intent": state.get("intent") or None,
                    "previous_action": state.get("last_action"),
                    "turn_count": int(state.get("turn_count", 0)) + 1,
                },
            )
            self.tracer.tool(
                trace,
                name="select_conversation_tool",
                inputs={"available_tools": list(self.conversation_tools.names)},
                output_summary={
                    "selected_tool": tool_call.name,
                    "source": tool_call.source,
                    "confidence": tool_call.confidence,
                    "fallback_used": bool(self.llm.last_route_error),
                },
            )
            routed = self.conversation_tools.execute(tool_call, user_message=text)
            self.tracer.tool(
                trace,
                name=tool_call.name,
                inputs=tool_call.arguments,
                output_summary={"should_search": routed["should_search"]},
            )
            if not routed["should_search"]:
                return self._finish_conversation_response(
                    user_id=user_id,
                    session_id=session_id,
                    state=state,
                    previous_intent=previous.public_dict() if previous else self._empty_intent(),
                    trace=trace,
                    tool_call=tool_call,
                    answer=str(routed["message"]),
                )

            extracted = self.preferences.extract_and_save(
                user_id, str(routed["query_text"]), previous_intent=previous
            )
            current = extracted.intent
            combined_intent = self.preferences.tactile_intent_for_category(
                user_id, category=current.category, current=current
            )
            search_text = str(routed["query_text"])
            if current.category and current.category.casefold() not in text.casefold():
                search_text = f"{current.category} {text}"
            pool_size = int(self.config["ranking"]["candidate_pool_size"])
            search = self.tools.tactile.search(search_text, limit=pool_size)
            self.tracer.tool(
                trace,
                name="catalog_tactile_search",
                inputs={"query_text": search_text, "limit": pool_size},
                output_summary={"candidates": len(search["items"]), "intent": current.public_dict()},
            )
            result_size = limit or int(self.config["ranking"]["default_result_size"])
            ranked = self.ranker.rank(
                user_id,
                search["items"],
                intent=combined_intent,
                limit=result_size,
            )
            self.tracer.tool(
                trace,
                name="personalized_rerank",
                inputs={"candidate_count": len(search["items"])},
                output_summary={
                    "result_count": len(ranked["results"]),
                    **ranked["profile_summary"],
                },
            )
            compact_products = [
                {
                    "product_id": row["product_id"],
                    "title": row["title"],
                    "category": row["category"],
                    "reasons": row["personalization_reasons"],
                    "target_source": row.get("tactile_target_source"),
                    "evidence": [
                        {
                            "original_span": evidence.get("original_span"),
                            "source": evidence.get("source"),
                        }
                        for evidence in row.get("matched_evidence", [])[:2]
                    ],
                }
                for row in ranked["results"][:5]
            ]
            grounded_context = {
                "products": compact_products,
                "preferences_saved": len(extracted.saved),
                "personalization_applied": ranked["profile_summary"]["personalization_applied"],
                "intent": combined_intent.public_dict(),
            }
            answer = self.llm.compose(message=text, grounded_context=grounded_context)
            state.update(
                {
                    "intent": combined_intent.public_dict(),
                    "last_product_ids": [row["product_id"] for row in ranked["results"]],
                    "turn_count": int(state.get("turn_count", 0)) + 1,
                    "last_trace_id": trace.trace_id,
                    "last_action": SHOPPING_TOOL,
                }
            )
            self.database.update_agent_state(session_id, user_id, state)
            self.database.add_message(
                session_id,
                role="assistant",
                content=answer,
                metadata={
                    "trace_id": trace.trace_id,
                    "result_product_ids": state["last_product_ids"],
                    "llm_provider": self.llm.info.provider,
                },
            )
            response = {
                "status": "complete" if ranked["results"] else "insufficient_results",
                "action": SHOPPING_TOOL,
                "session_id": session_id,
                "trace_id": trace.trace_id,
                "message": answer,
                "intent": combined_intent.public_dict(),
                "preferences_saved": [
                    {
                        "preference_id": row["preference_id"],
                        "scope_category": row["scope_category"],
                        "attribute_type": row["attribute_type"],
                        "attribute": row["attribute"],
                        "direction": row["direction"],
                    }
                    for row in extracted.saved
                ],
                "profile_summary": ranked["profile_summary"],
                "products": ranked["results"],
                "routing": {
                    "tool": tool_call.name,
                    "source": tool_call.source,
                    "confidence": tool_call.confidence,
                },
                "provenance": {
                    "tools": [
                        "select_conversation_tool",
                        SHOPPING_TOOL,
                        "catalog_tactile_search",
                        "personalized_rerank",
                    ],
                    "agent_version": "v1",
                    "tactile_provider": self.tools.tactile.version,
                    "llm_provider": self.llm.info.provider,
                    "llm_model": self.llm.info.model_id,
                    "llm_fallback_used": bool(self.llm.last_error),
                    "router_fallback_used": bool(self.llm.last_route_error),
                },
            }
            self.tracer.finish(
                trace,
                outputs={
                    "status": response["status"],
                    "result_count": len(response["products"]),
                    "product_ids": state["last_product_ids"],
                    "model_versions": response["provenance"],
                },
            )
            return response
        except Exception as exc:
            self.tracer.finish(trace, error=str(exc))
            raise

    @staticmethod
    def _empty_intent() -> dict[str, Any]:
        return {
            "current_product_id": None,
            "category": None,
            "query_text": "",
            "desired_more": [],
            "desired_less": [],
            "avoid": [],
            "must_have": [],
            "source": "conversation_router",
            "confidence": 0.0,
        }

    def _finish_conversation_response(
        self,
        *,
        user_id: str,
        session_id: str,
        state: dict[str, Any],
        previous_intent: dict[str, Any],
        trace: Trace,
        tool_call: AgentToolCall,
        answer: str,
    ) -> dict[str, Any]:
        state.update(
            {
                "turn_count": int(state.get("turn_count", 0)) + 1,
                "last_trace_id": trace.trace_id,
                "last_action": tool_call.name,
            }
        )
        self.database.update_agent_state(session_id, user_id, state)
        self.database.add_message(
            session_id,
            role="assistant",
            content=answer,
            metadata={
                "trace_id": trace.trace_id,
                "result_product_ids": [],
                "router_tool": tool_call.name,
                "router_source": tool_call.source,
            },
        )
        profile_summary = {
            "preference_count": len(self.database.list_preferences(user_id)),
            "behavior_event_count": len(self.database.list_events(user_id)),
            "cart_item_count": len(self.database.list_cart(user_id)),
            "personalization_applied": False,
        }
        response = {
            "status": "complete",
            "action": tool_call.name,
            "session_id": session_id,
            "trace_id": trace.trace_id,
            "message": answer,
            "intent": previous_intent,
            "preferences_saved": [],
            "profile_summary": profile_summary,
            "products": [],
            "routing": {
                "tool": tool_call.name,
                "source": tool_call.source,
                "confidence": tool_call.confidence,
            },
            "provenance": {
                "tools": ["select_conversation_tool", tool_call.name],
                "agent_version": "v1",
                "tactile_provider": self.tools.tactile.version,
                "llm_provider": self.llm.info.provider,
                "llm_model": self.llm.info.model_id,
                "llm_fallback_used": False,
                "router_fallback_used": bool(self.llm.last_route_error),
            },
        }
        self.tracer.finish(
            trace,
            outputs={
                "status": response["status"],
                "action": response["action"],
                "result_count": 0,
                "product_ids": [],
                "model_versions": response["provenance"],
            },
        )
        return response
