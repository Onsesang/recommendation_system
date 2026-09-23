"""Streamlit demo; research metrics are read-only and never recomputed here."""
import streamlit as st
from common import CLASSES,DATA,ART,load_json
from recommend import RecommendationService
import pandas as pd

st.set_page_config(page_title='Amazon Fashion Tactile Recommender',layout='wide')
st.title('Amazon Fashion tactile-aware recommendation')
st.caption('전체 Amazon Fashion catalog · 고정 Last2 추론 · validation-locked 추천 설정')

@st.cache_resource(show_spinner='추천 모델과 전체 촉각 프로필을 불러오는 중…')
def service():return RecommendationService()

metadata=pd.read_parquet(DATA/'item_metadata.parquet',columns=['category'])
with st.sidebar:
    user_id=st.text_input('User ID (optional)') or None
    category=st.selectbox('Category (optional)',['All',*sorted(metadata.category.unique())])
    desired=st.multiselect('Desired tactile',CLASSES)
    top_k=st.radio('Top-K',[5,10],horizontal=True,index=1)
    compare=st.toggle('Compare systems',value=False)
    lock=load_json(ART/'selection_lock.json');research_alpha=float(lock.get('alpha',0))
    use_slider=st.toggle('Demo-only alpha slider',value=False)
    alpha=st.slider('Tactile weight α',0.0,1.0,research_alpha,0.05,disabled=not use_slider)
    st.caption(f'Research default α={research_alpha:.2f}; slider output is not used in offline metrics.')
    run=st.button('Recommend',type='primary')

def render(payload,title):
    st.subheader(title);st.caption(f"System: {payload['system']} · candidate K={payload['candidate_k']} · fallback={payload['fallback'] or 'personalized'}")
    cols=st.columns(min(5,len(payload['results'])))
    for i,row in enumerate(payload['results']):
        with cols[i%len(cols)]:
            if isinstance(row['image_url'],str):st.image(row['image_url'],use_container_width=True)
            st.markdown(f"**{row['rank']}. {row['title']}**")
            st.caption(f"{row['parent_asin']} · {row['category']}")
            st.metric('Final score',f"{row['final_score']:.4f}")
            st.write('Tactile match:', 'N/A' if row['tactile_match'] is None else f"{row['tactile_match']:.4f}")
            with st.expander('Score breakdown'):
                st.json({'base_raw':row['base_raw_score'],'base_rank_percentile':row['base_rank_percentile'],'tactile_available':row['tactile_available'],**row['selected_tactile_probabilities']})

if run:
    s=service();kwargs=dict(user_id=user_id,category=None if category=='All' else category,desired=desired,top_k=top_k,alpha=alpha if use_slider else None)
    if compare:
        left,right=st.columns(2)
        with left:render(s.recommend(**kwargs,system='strong'),'Strong + tactile' if desired else 'Strong vanilla')
        with right:
            if s.smore_scorer is None:st.warning('Multimodal model is unavailable; see experiment report.')
            else:render(s.recommend(**kwargs,system='multimodal'),'Multimodal + tactile' if desired else 'Generic multimodal')
    else:render(s.recommend(**kwargs,system='strong'),'Recommendations')
else:
    st.info('조건을 선택한 뒤 Recommend를 누르세요. Category는 사용자가 명시할 때만 hard filter로 적용됩니다.')
