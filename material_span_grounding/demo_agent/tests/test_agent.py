from demo_agent.agent import TactileAgent
from demo_agent.tests.test_recommender import fixture_recommender


def test_agent_contract_and_main_result_update_payload() -> None:
    agent = TactileAgent(fixture_recommender())
    response = agent.handle({"message": "부드럽고 얇은 셔츠", "top_k": 2})
    assert response["interpreted_query"]["category"] == "shirt"
    assert response["conversation_state"] == response["interpreted_query"]
    assert len(response["products"]) == 2
    assert response["assistant_message"]
    assert response["parser"]["source"] == "deterministic_fallback"


def test_invalid_remote_parser_falls_back_deterministically() -> None:
    def invalid_remote(message, previous):
        return {"category": "shirt", "constraints": [{"class": "invented"}]}

    agent = TactileAgent(fixture_recommender(), remote_parser=invalid_remote)
    response = agent.handle({"message": "부드러운 셔츠"})
    assert response["parser"]["fallback_used"] is True
    assert response["parser"]["fallback_reason_type"] == "ValueError"
    assert response["interpreted_query"]["constraints"][0]["tactile_class"] == "soft"
