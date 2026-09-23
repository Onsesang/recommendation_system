from streamlit.testing.v1 import AppTest


def test_quick_prompt_updates_main_catalog() -> None:
    app = AppTest.from_file("demo_agent/app.py", default_timeout=30).run()
    assert not app.exception
    assert [item.value for item in app.subheader] == ["먼저 둘러볼 상품"]
    soft_knit = next(button for button in app.button if button.label == "부드러운 니트")
    soft_knit.click().run(timeout=30)
    assert not app.exception
    assert [item.value for item in app.subheader] == ["추천 상품"]
    assert app.session_state["conversation_state"]["category"] == "sweater"
    assert app.session_state["results"]["result_count"] == 12
    assert "부드러움" in app.session_state["chat_messages"][-1]["content"]
