#!/usr/bin/env python3
from __future__ import annotations

import streamlit as st

from common import ARTIFACTS
from recommend import get_service


st.set_page_config(page_title="Amazon Fashion Tactile Reranker", layout="wide")
st.title("Amazon Fashion: Two-stage Tactile Reranking")
st.caption("Offline targets and tactile pseudo-labels are intentionally not displayed.")


@st.cache_resource
def service():
    return get_service()


engine = service()
user_id = st.selectbox("User ID", engine.known_users)
categories = ["(all)"] + sorted(engine.products["category"].unique().tolist())
category = st.selectbox("Optional category filter", categories)
desired = st.multiselect("Desired tactile properties", engine.classes)
top_k = st.radio("Top-K", [5, 10], horizontal=True, index=1)

if st.button("Recommend", type="primary"):
    result = engine.recommend(user_id, desired, None if category == "(all)" else category, top_k)
    st.info(f"Locked validation weights: beta={result['beta_star']:.2f}, alpha={result['alpha_star']:.2f}. " + result["explicit_alpha_note"])
    tabs = st.tabs(["Vanilla", "Category-aware", "Proposed"])
    for tab, method in zip(tabs, ["vanilla", "category_aware", "proposed"]):
        with tab:
            columns = st.columns(min(5, top_k))
            for rank, item in enumerate(result["methods"][method], 1):
                with columns[(rank-1) % len(columns)]:
                    st.image(item["image_path"], use_container_width=True)
                    st.markdown(f"**#{rank} · {item['item_id']}**")
                    st.write(item["category"], f"score={item['score']:.3f}")
                    with st.expander("Score / tactile detail"):
                        st.json({key: item[key] for key in ("vanilla_score_norm", "category_score_norm", "tactile_score_norm", "tactile_match_detail")})

st.divider()
st.subheader("Validation alpha search")
st.image(str(ARTIFACTS / "alpha_validation_curve.png"))
