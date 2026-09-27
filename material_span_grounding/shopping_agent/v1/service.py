from __future__ import annotations

import json
import uuid
from typing import Any

from demo_agent.models import SUPPORTED_CATEGORIES, Constraint, StructuredQuery
from recommendation_api.tactile_agent import intent_from_mapping
from recommendation_api.tactile_models import TactileIntent

from .agent_tools import ConversationToolRegistry, SHOPPING_TOOL
from . import tactile_phrases
from .contracts import AgentToolCall
from .database import AgentDatabase
from .llm import ResilientLLMProvider
from .personalization import PersonalizedRanker
from .preferences import PreferenceService
from .tool_agent import AGENT_INSTRUCTIONS, OpenAIToolLoop
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
        tool_agent: OpenAIToolLoop | None = None,
    ) -> None:
        self.database = database
        self.tools = tools
        self.preferences = preferences
        self.ranker = ranker
        self.llm = llm
        self.tracer = tracer
        self.config = config
        self.conversation_tools = ConversationToolRegistry(config)
        self.tool_agent = tool_agent

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
        llm: Any = self.llm
        try:
            self.database.add_message(session_id, role="user", content=text)
            if self.tool_agent is not None:
                try:
                    return self._tool_agent_turn(
                        user_id=user_id,
                        session_id=session_id,
                        text=text,
                        state=state,
                        previous=previous,
                        trace=trace,
                        limit=limit,
                    )
                except Exception as exc:
                    # Retrieval must never depend on the remote model; answer with the local router.
                    self.tracer.tool(
                        trace,
                        name="openai_tool_loop",
                        inputs={"model": self.tool_agent.info.model_id},
                        output_summary={"error": str(exc)[:500], "fallback": "router_pipeline"},
                    )
                    llm = self.llm.fallback
            tool_call = llm.select_tool(
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
                    "fallback_used": bool(getattr(llm, "last_route_error", None)),
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
                    llm=llm,
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
                "result_count": len(ranked["results"]),
                "preferences_saved": len(extracted.saved),
                "personalization_applied": ranked["profile_summary"]["personalization_applied"],
                "intent": combined_intent.public_dict(),
            }
            answer = llm.compose(message=text, grounded_context=grounded_context)
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
                    "llm_provider": llm.info.provider,
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
                    "llm_provider": llm.info.provider,
                    "llm_model": llm.info.model_id,
                    "llm_fallback_used": bool(getattr(llm, "last_error", None)),
                    "router_fallback_used": bool(getattr(llm, "last_route_error", None)),
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

    # -- OpenAI tool loop -----------------------------------------------------

    def _cart_title(self, product_id: str) -> str:
        try:
            return str(self.tools.public_product(product_id).get("title", ""))[:80]
        except KeyError:
            return ""

    def _tool_agent_turn(
        self,
        *,
        user_id: str,
        session_id: str,
        text: str,
        state: dict[str, Any],
        previous: TactileIntent | None,
        trace: Trace,
        limit: int | None,
    ) -> dict[str, Any]:
        assert self.tool_agent is not None
        settings = self.config["tool_agent"]
        turn = _ToolTurn(self, user_id=user_id, session_id=session_id, text=text, state=state,
                         previous=previous, limit=limit)
        history = self.database.list_messages(session_id, limit=int(settings["history_messages"]))
        input_items = [
            {"role": row["role"], "content": row["content"]}
            for row in history
            if row["role"] in {"user", "assistant"}
        ]
        cart = self.database.list_cart(user_id)
        session_context = {
            "shown_products": turn.shown_products(),
            "last_search": state.get("last_search"),
            "cart_item_count": len(cart),
            # Lets "방금 담은 거" resolve without an extra view_cart round trip.
            "cart": [
                {"product_id": row["product_id"], "title": self._cart_title(row["product_id"]),
                 "quantity": row["quantity"]}
                for row in cart[:10]
            ],
            "last_cart_change": state.get("last_cart_change"),
        }
        instructions = (
            AGENT_INSTRUCTIONS
            + "\n\n현재 세션 상태(JSON):\n"
            + json.dumps(session_context, ensure_ascii=False, separators=(",", ":"))
        )

        def execute(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
            output = turn.execute(name, arguments)
            self.tracer.tool(
                trace,
                name=name,
                inputs=arguments,
                output_summary={key: value for key, value in output.items() if key != "products"},
            )
            return output

        run = self.tool_agent.run(instructions=instructions, input_items=input_items, execute=execute)
        if not run.calls:
            # A plain statement such as "검은색 좋아" calls no tool; remember it anyway. Turns
            # about a shown product or the cart are skipped: "1번 부드러워?" is a question.
            turn.remember_preferences()
        if run.rewritten:
            self.tracer.tool(
                trace,
                name="answer_rewrite",
                inputs={"reason": "foreign_script"},
                output_summary={"removed": run.removed_foreign},
            )
        if run.fallback_used:
            self.tracer.tool(
                trace,
                name="model_fallback",
                inputs={"primary": self.tool_agent.model, "fallback": self.tool_agent.fallback_model},
                output_summary={"error": run.fallback_error},
            )
        answer = run.text
        searched = turn.ranked is not None
        products = turn.ranked["results"] if turn.ranked else []
        action = run.calls[-1]["name"] if run.calls else "respond"
        if searched:
            action = "search_products"
        intent = (
            turn.intent.public_dict()
            if turn.intent
            else previous.public_dict() if previous else self._empty_intent()
        )
        state.update(
            {
                "turn_count": int(state.get("turn_count", 0)) + 1,
                "last_trace_id": trace.trace_id,
                "last_action": action,
            }
        )
        if turn.last_cart_change is not None:
            state["last_cart_change"] = turn.last_cart_change
        if searched:
            # Only a search changes the stored intent, as in the router pipeline.
            state["intent"] = intent
            state["last_product_ids"] = [row["product_id"] for row in products]
            state["shown_products"] = turn.shown_products()
            state["last_search"] = turn.search_arguments
        self.database.update_agent_state(session_id, user_id, state)
        self.database.add_message(
            session_id,
            role="assistant",
            content=answer,
            metadata={
                "trace_id": trace.trace_id,
                "result_product_ids": [row["product_id"] for row in products],
                "llm_provider": self.tool_agent.info.provider,
                "tool_calls": run.calls,
            },
        )
        profile_summary = (
            turn.ranked["profile_summary"]
            if turn.ranked
            else {
                "preference_count": len(self.database.list_preferences(user_id)),
                "behavior_event_count": len(self.database.list_events(user_id)),
                "cart_item_count": len(self.database.list_cart(user_id)),
                "personalization_applied": False,
            }
        )
        response = {
            "status": "insufficient_results" if searched and not products else "complete",
            "action": action,
            "session_id": session_id,
            "trace_id": trace.trace_id,
            "message": answer,
            "intent": intent,
            "preferences_saved": [
                {
                    "preference_id": row["preference_id"],
                    "scope_category": row["scope_category"],
                    "attribute_type": row["attribute_type"],
                    "attribute": row["attribute"],
                    "direction": row["direction"],
                }
                for row in turn.saved_preferences
            ],
            "profile_summary": profile_summary,
            "products": products,
            "tool_calls": run.calls,
            "cart_updated": turn.cart_updated,
            "referenced_product_ids": turn.referenced_ids,
            "unsupported_concepts": turn.unsupported_concepts,
            "routing": {"tool": action, "source": "openai_tool_loop", "confidence": None},
            "provenance": {
                "tools": [call["name"] for call in run.calls],
                "agent_version": "v1",
                "agent_mode": "openai_tool_loop",
                "tactile_provider": self.tools.tactile.version,
                "llm_provider": self.tool_agent.info.provider,
                "llm_model": run.model or self.tool_agent.info.model_id,
                "llm_model_fallback_used": run.fallback_used,
                "answer_rewritten": run.rewritten,
                "llm_requests": run.model_requests,
                "llm_fallback_used": False,
                "router_fallback_used": False,
            },
        }
        self.tracer.finish(
            trace,
            outputs={
                "status": response["status"],
                "action": action,
                "result_count": len(products),
                "product_ids": response["referenced_product_ids"],
                "model_versions": response["provenance"],
            },
        )
        return response

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
        llm: Any,
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
                "llm_provider": llm.info.provider,
                "llm_model": llm.info.model_id,
                "llm_fallback_used": False,
                "router_fallback_used": bool(getattr(llm, "last_route_error", None)),
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


class _ToolTurn:
    """Execute the model's tool calls for one user turn against grounded services."""

    def __init__(
        self,
        service: ShoppingAgentService,
        *,
        user_id: str,
        session_id: str,
        text: str,
        state: dict[str, Any],
        previous: TactileIntent | None,
        limit: int | None,
    ) -> None:
        self.service = service
        self.user_id = user_id
        self.session_id = session_id
        self.text = text
        self.state = state
        self.previous = previous
        self.limit = limit
        self.settings = service.config["tool_agent"]
        self.ranked: dict[str, Any] | None = None
        self.intent: TactileIntent | None = None
        self.search_arguments: dict[str, Any] | None = None
        self.saved_preferences: list[dict[str, Any]] = []
        self.unsupported_concepts: list[str] = []
        self.referenced_ids: list[str] = []
        self.cart_updated = False
        self.last_cart_change: dict[str, Any] | None = None
        self._preferences_extracted = False

    # -- session memory -------------------------------------------------------

    def shown_products(self) -> list[dict[str, Any]]:
        size = int(self.settings["shown_products_memory"])
        if self.ranked is not None:
            rows = self.ranked["results"][:size]
            return [
                {"number": number, "product_id": row["product_id"], "title": str(row["title"])[:90]}
                for number, row in enumerate(rows, 1)
            ]
        stored = self.state.get("shown_products")
        if stored:
            return list(stored)[:size]
        shown = []
        for number, product_id in enumerate(self.state.get("last_product_ids", [])[:size], 1):
            try:
                title = str(self.service.tools.public_product(product_id).get("title", ""))[:90]
            except KeyError:
                continue
            shown.append({"number": number, "product_id": product_id, "title": title})
        return shown

    def _known_ids(self) -> set[str]:
        return {str(row["product_id"]) for row in self.shown_products()} | set(
            self.state.get("last_product_ids", [])
        )

    def _reference(self, product_id: str) -> None:
        if product_id not in self.referenced_ids:
            self.referenced_ids.append(product_id)

    def remember_preferences(self, structured: dict[str, Any] | None = None) -> None:
        """Save this message's preferences once per turn (tactile from `structured` when given)."""
        if self._preferences_extracted:
            return
        self._preferences_extracted = True
        self.saved_preferences = self.service.preferences.extract_and_save(
            self.user_id, self.text, structured=structured
        ).saved

    # -- dispatch ------------------------------------------------------------

    def execute(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        handler = {
            "search_products": self.search_products,
            "get_product_detail": self.get_product_detail,
            "compare_products": self.compare_products,
            "add_to_cart": self.add_to_cart,
            "remove_from_cart": self.remove_from_cart,
            "view_cart": self.view_cart,
        }[name]
        return handler(**arguments)

    def search_products(
        self,
        *,
        query_text: str,
        category: str | None,
        want: list[str],
        avoid: list[str],
        keywords: list[str],
        unsupported_concepts: list[str],
    ) -> dict[str, Any]:
        service = self.service
        category = category if category in SUPPORTED_CATEGORIES else None
        avoid = list(dict.fromkeys(avoid))
        want = [value for value in dict.fromkeys(want) if value not in avoid]
        self.remember_preferences({"category": category, "want": want, "avoid": avoid})
        keywords = [str(value) for value in keywords if str(value).strip()][:8]
        self.unsupported_concepts = [str(value) for value in unsupported_concepts][:5]
        query_text = str(query_text).strip() or self.text
        structured = StructuredQuery(
            category=category,
            constraints=tuple(Constraint(value) for value in want),
            negative_constraints=tuple(Constraint(value) for value in avoid),
            source="openai_tool_loop",
            original_message=self.text,
        )
        current = TactileIntent(
            category=category,
            query_text=query_text,
            desired_more=tuple(want),
            avoid=tuple(avoid),
            source="explicit_structured",
            confidence=float(self.settings["structured_intent_confidence"]),
        )
        self.intent = service.preferences.tactile_intent_for_category(
            self.user_id, category=category, current=current
        )
        pool_size = int(service.config["ranking"]["candidate_pool_size"])
        search = service.tools.tactile.search(
            query_text, limit=pool_size, structured=structured, keywords=keywords
        )
        result_size = self.limit or int(service.config["ranking"]["default_result_size"])
        self.ranked = service.ranker.rank(
            self.user_id, search["items"], intent=self.intent, limit=result_size
        )
        self.search_arguments = {
            "query_text": query_text,
            "category": category,
            "want": want,
            "avoid": avoid,
            "keywords": keywords,
        }
        requested = [*want, *avoid]
        rows = self.ranked["results"][: int(self.settings["tool_result_products"])]
        for row in rows:
            self._reference(str(row["product_id"]))
        # Phrases, not probabilities: the model must not read numbers or grades aloud.
        common, tactile = tactile_phrases.split_common(
            [tactile_phrases.phrases(row.get("last2_predictions", {}), requested) for row in rows]
        )
        return {
            "result_count": len(self.ranked["results"]),
            "category": category,
            "category_relaxed": bool(search.get("category_relaxed", False)),
            "unsupported_concepts": self.unsupported_concepts,
            "common_tactile_top3": common,
            "products": [
                {
                    "number": number,
                    "product_id": row["product_id"],
                    "title": str(row["title"])[:120],
                    "category": row["category"],
                    "evidence_source": row.get("tactile_target_source"),
                    "requested_tactile": tactile[number - 1],
                }
                for number, row in enumerate(rows, 1)
            ],
        }

    def get_product_detail(self, *, product_id: str) -> dict[str, Any]:
        detail = self.service.tools.tactile.product_detail(product_id)
        self._reference(product_id)
        profile = detail.get("tactile_profile")
        if profile:
            tactile = {
                "evidence_source": profile.get("source"),
                "strongest": tactile_phrases.strongest(profile.get("classes") or {
                    item["class"]: float(item["probability"]) for item in profile.get("strongest", [])
                }),
                "review_grounded_evidence_available": profile.get("review_grounded_evidence_available"),
                "note": profile.get("note"),
            }
        else:
            tactile = {
                "evidence_source": "review_grounded",
                "summary": detail.get("tactile_summary"),
                "concerns": detail.get("tactile_concerns"),
            }
        product = detail.get("product", {})
        return {
            "product_id": product_id,
            "title": str(product.get("title", ""))[:160],
            "category": product.get("category"),
            "tactile": _truncate(tactile, int(self.settings["tool_output_max_chars"])),
        }

    def compare_products(self, *, product_ids: list[str]) -> dict[str, Any]:
        ids = list(dict.fromkeys(str(value) for value in product_ids))
        if not 2 <= len(ids) <= 4:
            raise ValueError("compare_products needs 2 to 4 distinct product_ids")
        comparison = self.service.tools.tactile.compare(ids)
        for product_id in ids:
            self._reference(product_id)
        if comparison.get("source") == "image_predicted_last2":
            comparison = {
                **tactile_phrases.compare(comparison["items"]),
                "evidence_source": "image_predicted_last2",
            }
        return _truncate(comparison, int(self.settings["tool_output_max_chars"]))

    def add_to_cart(self, *, product_id: str, quantity: int) -> dict[str, Any]:
        service = self.service
        if product_id not in self._known_ids() and product_id not in self.referenced_ids:
            raise ValueError("Only products already shown in this conversation can be added")
        if not service.tools.product_exists(product_id):
            raise KeyError(f"Unknown product_id: {product_id}")
        if not 1 <= int(quantity) <= 20:
            raise ValueError("한 상품은 1~20개까지만 담을 수 있습니다. 나눠 담아도 20개를 넘길 수 없습니다.")
        service.database.add_cart_item(self.user_id, product_id, int(quantity))
        service.database.record_event(
            self.user_id,
            event_id=f"evt_{uuid.uuid4().hex}",
            event_type="cart_add",
            product_id=product_id,
            session_id=self.session_id,
            context={"quantity": int(quantity), "source": "openai_tool_loop"},
        )
        self.cart_updated = True
        self._reference(product_id)
        title = str(service.tools.public_product(product_id).get("title", ""))[:120]
        self.last_cart_change = {"action": "added", "product_id": product_id, "title": title[:80],
                                 "quantity": int(quantity)}
        return {"status": "added", "product_id": product_id, "title": title, "quantity": int(quantity),
                "note": "장바구니 수량은 이 값으로 설정됨(합산 아님), 한 상품당 최대 20개"}

    def remove_from_cart(self, *, product_id: str, quantity: int | None) -> dict[str, Any]:
        service = self.service
        item = next(
            (row for row in service.database.list_cart(self.user_id) if row["product_id"] == product_id), None
        )
        if item is None:
            raise KeyError(f"Not in cart: {product_id}")
        current = int(item["quantity"])
        if quantity is not None and not 1 <= int(quantity) <= 20:
            raise ValueError("quantity must be between 1 and 20 or null")
        remaining = 0 if quantity is None else max(0, current - int(quantity))
        if remaining:
            service.database.add_cart_item(self.user_id, product_id, remaining)
        else:
            service.database.remove_cart_item(self.user_id, product_id)
        service.database.record_event(
            self.user_id,
            event_id=f"evt_{uuid.uuid4().hex}",
            event_type="cart_remove",
            product_id=product_id,
            session_id=self.session_id,
            context={"removed_quantity": current - remaining, "source": "openai_tool_loop"},
        )
        self.cart_updated = True
        self._reference(product_id)
        try:
            title = str(service.tools.public_product(product_id).get("title", ""))[:120]
        except KeyError:
            title = ""
        self.last_cart_change = {"action": "decreased" if remaining else "removed", "product_id": product_id,
                                 "title": title[:80], "quantity": remaining}
        return {
            "status": "decreased" if remaining else "removed",
            "product_id": product_id,
            "title": title,
            "removed_quantity": current - remaining,
            "remaining_quantity": remaining,
        }

    def view_cart(self) -> dict[str, Any]:
        service = self.service
        items = []
        for row in service.database.list_cart(self.user_id):
            try:
                title = str(service.tools.public_product(row["product_id"]).get("title", ""))[:120]
            except KeyError:
                title = ""
            items.append({"product_id": row["product_id"], "title": title, "quantity": row["quantity"]})
        return {"item_count": len(items), "items": items}


def _truncate(value: Any, max_chars: int) -> Any:
    """Keep tool results inside a fixed prompt budget."""
    raw = json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)
    if len(raw) <= max_chars:
        return value
    return {"truncated_json": raw[:max_chars]}
