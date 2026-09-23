from __future__ import annotations

import html
from pathlib import Path
import sys

import streamlit as st

# Streamlit puts the script directory, not necessarily the repository root, on sys.path.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from demo_agent.agent import TactileAgent
from demo_agent.models import StructuredQuery
from demo_agent.recommender import (
    CATEGORY_LABELS_KO,
    TACTILE_LABELS_KO,
    ExplicitTactileRecommender,
)


PLACEHOLDER = Path(__file__).with_name("assets") / "placeholder.svg"
QUICK_PROMPTS = (
    "부드러운 니트",
    "얇고 시원한 셔츠",
    "두껍고 따뜻한 자켓",
    "매끄럽고 유연한 옷",
)


st.set_page_config(
    page_title="온세상 — 촉감으로 찾는 옷",
    page_icon="◌",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown(
    """
<style>
  :root { --ink:#22231f; --muted:#6e7168; --paper:#fbfaf7; --sage:#dce7dd; --accent:#315c43; }
  .stApp { background: linear-gradient(150deg, #fbfaf7 0%, #f4f1e9 100%); color: var(--ink); }
  [data-testid="stHeader"] { background: transparent; }
  .block-container { max-width: 1480px; padding: 2rem 2.3rem 6rem; }
  h1, h2, h3 { letter-spacing: -0.035em; }
  .brand-kicker { color:var(--accent); font-size:.82rem; font-weight:800; letter-spacing:.16em; }
  .brand-title { font-size:2.55rem; line-height:1.06; font-weight:800; margin:.2rem 0 .55rem; }
  .hero-copy { color:var(--muted); font-size:1.02rem; margin-bottom:1.35rem; }
  .query-line { padding:1rem 1.15rem; border:1px solid #ddd9cf; border-radius:18px; background:rgba(255,255,255,.75); margin:.6rem 0 1.3rem; }
  .query-chip { display:inline-block; background:var(--sage); color:#244531; border-radius:999px; padding:.32rem .68rem; margin:0 .32rem .35rem 0; font-size:.84rem; font-weight:700; }
  .result-meta { color:var(--muted); font-size:.88rem; }
  div[data-testid="stVerticalBlockBorderWrapper"] { background:rgba(255,255,255,.76); border-radius:20px; }
  div[data-testid="stVerticalBlockBorderWrapper"] img { border-radius:14px; aspect-ratio:4/5; object-fit:cover; }
  .product-title { min-height:3.2rem; font-size:.96rem; font-weight:750; line-height:1.35; margin:.35rem 0 .55rem; }
  .score-badge { display:inline-block; border:1px solid #d4ded5; color:#315c43; background:#eef4ee; border-radius:999px; padding:.22rem .48rem; margin:0 .2rem .25rem 0; font-size:.76rem; }
  .reason { color:#555950; font-size:.84rem; line-height:1.5; min-height:4.9rem; margin-top:.35rem; }
  .prediction-note { color:#7a776f; font-size:.82rem; border-left:3px solid #c8bfae; padding-left:.65rem; }
  div[data-testid="stVerticalBlockBorderWrapper"]:has(#agent-chat-marker) {
    position:fixed; right:1.35rem; bottom:1.35rem; width:auto; z-index:9999;
    padding:0 !important; border:0 !important; background:transparent !important;
    box-shadow:0 14px 38px rgba(31,37,29,.18);
  }
  #agent-chat-marker { display:none; }
  div[data-testid="stPopoverBody"] { width:min(410px, calc(100vw - 2rem)); max-height:590px; overflow-y:auto; }
  @media (max-width: 700px) {
    .block-container { padding:1.2rem 1rem 6rem; }
    .brand-title { font-size:2rem; }
    div[data-testid="stVerticalBlockBorderWrapper"]:has(#agent-chat-marker) { right:.75rem; bottom:.75rem; }
  }
</style>
""",
    unsafe_allow_html=True,
)


@st.cache_resource(show_spinner="825,840개 Last2 촉각 프로필을 불러오는 중…")
def services() -> tuple[ExplicitTactileRecommender, TactileAgent]:
    recommender = ExplicitTactileRecommender()
    return recommender, TactileAgent(recommender)


def current_query() -> StructuredQuery | None:
    state = st.session_state.get("conversation_state")
    if not state:
        return None
    return StructuredQuery.from_mapping(state, source=str(state.get("source") or "agent_context"))


def run_message(message: str) -> dict:
    response = agent.handle(
        {
            "message": message,
            "conversation_state": st.session_state.get("conversation_state", {}),
        }
    )
    st.session_state.chat_messages.append({"role": "user", "content": message})
    st.session_state.chat_messages.append(
        {"role": "assistant", "content": response["assistant_message"]}
    )
    st.session_state.conversation_state = response["conversation_state"]
    st.session_state.results = response
    return response


def render_query_header(payload: dict) -> None:
    query = current_query()
    if query is None:
        st.markdown(
            '<div class="query-line"><div class="result-meta">오른쪽 아래의 촉감 에이전트에게 원하는 옷을 말해보세요.</div></div>',
            unsafe_allow_html=True,
        )
        return
    chips = []
    if query.category:
        chips.append(CATEGORY_LABELS_KO[query.category])
    chips.extend(TACTILE_LABELS_KO[item.tactile_class] for item in query.constraints)
    chips.extend(
        f"{TACTILE_LABELS_KO[item.tactile_class]} 제외"
        for item in query.negative_constraints
    )
    chip_html = "".join(
        f'<span class="query-chip">{html.escape(value)}</span>' for value in chips
    )
    message = st.session_state.chat_messages[-1]["content"]
    candidate_count = payload["retrieval"]["candidate_count"]
    st.markdown(
        f'<div class="query-line">{chip_html}<div class="result-meta">{html.escape(message)} · 후보 {candidate_count:,}개를 벡터화 정렬</div></div>',
        unsafe_allow_html=True,
    )
    if payload["retrieval"].get("specific_category_relaxed"):
        st.info("세부 상품 후보가 적어 저장소의 상위 카테고리로 조건을 완화했습니다.")


def render_detail(product: dict) -> None:
    with st.popover("자세히 보기", use_container_width=True):
        st.image(product["image_url"] or str(PLACEHOLDER), use_column_width=True)
        st.markdown(f"### {product['title']}")
        st.caption(f"{product['item_id']} · {product['category']}")
        if product["tactile_match"] is not None:
            st.metric("종합 촉각 일치 점수", f"{product['tactile_match']:.3f}")
        st.markdown("**Last2 14D 이미지 기반 예측**")
        predictions = product["all_tactile_predictions"]
        table_rows = [
            {"촉각 class": name, "표시": TACTILE_LABELS_KO[name], "예측 확률": round(predictions[name], 4)}
            for name in predictions
        ]
        st.dataframe(table_rows, hide_index=True, use_container_width=True)
        st.markdown("**추천 이유**")
        st.write(product["reason"])
        with st.expander("점수 계산 디버그 정보"):
            st.json(product["score_breakdown"])


def render_products(payload: dict) -> None:
    products = payload["products"]
    if not products:
        st.warning("현재 조건에 맞는 상품이 없습니다. 카테고리나 촉감 조건을 조금 넓혀주세요.")
        return
    columns = st.columns(4)
    for index, product in enumerate(products):
        with columns[index % 4]:
            with st.container(border=True):
                st.image(product["image_url"] or str(PLACEHOLDER), use_column_width=True)
                st.markdown(
                    f'<div class="product-title">{html.escape(product["title"])}</div>',
                    unsafe_allow_html=True,
                )
                if product["tactile_scores"]:
                    badges = "".join(
                        f'<span class="score-badge">{html.escape(TACTILE_LABELS_KO[name])} {value:.2f}</span>'
                        for name, value in product["tactile_scores"].items()
                    )
                    st.markdown(badges, unsafe_allow_html=True)
                st.markdown(
                    f'<div class="reason">{html.escape(product["reason"])}</div>',
                    unsafe_allow_html=True,
                )
                render_detail(product)


def render_chat() -> None:
    shell = st.container()
    with shell:
        st.markdown('<span id="agent-chat-marker"></span>', unsafe_allow_html=True)
        with st.popover("💬 촉감 에이전트"):
            st.markdown("### 촉감 에이전트")
            st.caption("원하는 옷과 촉감을 말씀해 주세요.")
            for message in st.session_state.chat_messages[-8:]:
                with st.chat_message(message["role"]):
                    st.write(message["content"])
            st.markdown("**빠른 질문**")
            quick_cols = st.columns(2)
            for index, prompt in enumerate(QUICK_PROMPTS):
                if quick_cols[index % 2].button(prompt, key=f"quick-{index}", use_container_width=True):
                    response = run_message(prompt)
                    st.success(response["assistant_message"])
            with st.form("agent-message-form", clear_on_submit=True):
                message = st.text_input(
                    "메시지",
                    placeholder="예: 까슬하지 않고 따뜻한 니트",
                    label_visibility="collapsed",
                )
                submitted = st.form_submit_button("추천 받기", type="primary", use_container_width=True)
                if submitted:
                    if message.strip():
                        response = run_message(message)
                        st.success(response["assistant_message"])
                    else:
                        st.warning("원하는 옷과 촉감을 입력해 주세요.")


recommender, agent = services()
if "chat_messages" not in st.session_state:
    st.session_state.chat_messages = [
        {
            "role": "assistant",
            "content": "안녕하세요! 원하는 옷과 촉감을 말씀해 주세요. 예: ‘부드럽고 얇은 셔츠를 사고 싶어요.’",
        }
    ]
if "results" not in st.session_state:
    st.session_state.results = recommender.initial_recommendations()
if "conversation_state" not in st.session_state:
    st.session_state.conversation_state = {}

# Execute chat controls before the catalog so a submitted turn updates the main
# grid in the same Streamlit run. CSS keeps this container floating at bottom-right.
render_chat()

st.markdown('<div class="brand-kicker">ONSESANG · LAST2 TACTILE</div>', unsafe_allow_html=True)
st.markdown('<div class="brand-title">온세상<br>촉감으로 찾는 옷</div>', unsafe_allow_html=True)
st.markdown(
    '<div class="hero-copy">말로 표현한 촉감을 825K Amazon Fashion 상품의 이미지 기반 예측과 연결합니다.</div>',
    unsafe_allow_html=True,
)
render_query_header(st.session_state.results)

left, right = st.columns([4, 1])
with left:
    heading = "추천 상품" if current_query() else "먼저 둘러볼 상품"
    st.subheader(heading)
with right:
    st.caption(f"{st.session_state.results['result_count']}개 표시")

render_products(st.session_state.results)
st.markdown(
    '<p class="prediction-note">안내: 표시된 촉각 수치는 사람이 만져 측정한 물리적 정답이 아니라, 상품 이미지에서 Last2 모델이 추정한 연속 확률입니다.</p>',
    unsafe_allow_html=True,
)
