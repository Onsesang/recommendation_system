from demo_agent.tactile_parser import parse_message


def classes(query):
    return [item.tactile_class for item in query.constraints]


def negative_classes(query):
    return [item.tactile_class for item in query.negative_constraints]


def test_required_korean_examples() -> None:
    cases = (
        ("부드러운 니트 추천해줘", "sweater", ["soft"], []),
        ("얇고 시원한 셔츠 사고 싶어", "shirt", ["thin", "cool"], []),
        ("두껍고 따뜻한 자켓 보여줘", "jacket", ["thick", "warm"], []),
        ("까슬하지 않고 유연한 옷을 추천해줘", None, ["flexible"], ["rough"]),
        ("신축성 있는 바지를 찾고 있어", "pants", ["elastic"], []),
    )
    for message, category, positive, negative in cases:
        query = parse_message(message)
        assert query.category == category
        assert classes(query) == positive
        assert negative_classes(query) == negative


def test_non_elastic_is_not_double_counted_as_elastic() -> None:
    query = parse_message("신축성 없는 바지")
    assert classes(query) == ["non_elastic"]
    assert negative_classes(query) == []


def test_category_free_followup_keeps_context_and_replaces_opposite() -> None:
    first = parse_message("부드럽고 얇은 셔츠")
    second = parse_message("조금 더 따뜻한 걸로", previous=first)
    assert second.category == "shirt"
    assert classes(second) == ["soft", "thin", "warm"]
    third = parse_message("시원한 걸로 바꿔줘", previous=second)
    assert classes(third) == ["soft", "thin", "cool"]


def test_new_explicit_category_and_tactile_starts_new_query() -> None:
    previous = parse_message("부드럽고 얇은 셔츠")
    current = parse_message("두꺼운 코트로 보여줘", previous=previous)
    assert current.category == "coat"
    assert classes(current) == ["thick"]
