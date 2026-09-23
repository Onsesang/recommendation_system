import re
import pandas as pd
import streamlit as st

from pilot import ART,ROOT,FIELDS,CLASSES,STATES,ATTITUDES
from human_audit import save_human

st.set_page_config(page_title='Tactile preference audit',layout='wide')
st.title('촉감 선호 검토 — 속성의 존재와 좋아함을 구별하기')
st.caption('모델 답변은 표시하지 않습니다. 먼저 문맥을 읽고 독립적으로 판단해 주세요.')
samples=pd.read_parquet(ART/'pilot_samples.parquet')
annotator=st.text_input('평가자 ID (영문·숫자·_·-)')
role=st.selectbox('표본 묶음',['development','audit_holdout'])
pool=samples[samples.split_role==role]
if not re.fullmatch(r'[A-Za-z0-9_-]{1,40}',annotator):
    st.info('평가자 ID를 입력하면 시작할 수 있습니다.');st.stop()
path=ROOT/'annotations'/f'{annotator}.csv'
existing=pd.read_csv(path,keep_default_na=False) if path.exists() else pd.DataFrame()
done=set(existing.sample_id) if len(existing) else set()
st.write(f'저장됨: {sum(s in done for s in pool.sample_id)} / {len(pool)}')
sid=st.selectbox('표본',pool.sample_id.tolist(),format_func=lambda x:('✓ ' if x in done else '')+x)
row=pool[pool.sample_id==sid].iloc[0].to_dict()
st.write('검토할 표현:',row['focal_phrase'])
st.text(row['context'])
with st.expander('전체 원문'):
    st.text(row['text'])
st.caption('attitude는 표현된 상태에 대한 평가입니다. “not soft”만으로 dislike를 선택하지 마세요. “cool design”은 not_tactile입니다.')
prior=existing[existing.sample_id==sid].iloc[0].to_dict() if sid in done else {}
with st.form(sid):
    values={}
    values['property_phrase']=st.text_input('원문의 촉감 표현',value=prior.get('property_phrase',row['focal_phrase']))
    for field,options in [('class_id',CLASSES),('property_state',STATES),('attitude',ATTITUDES)]:
        choices=['-- 선택 --']+options
        values[field]=st.selectbox(field,choices,index=choices.index(prior[field]) if prior.get(field) in choices else 0)
    values['scope']=st.text_input('부위(scope), 명시 없으면 unknown',value=prior.get('scope',''))
    values['condition']=st.text_input('상황·계절(condition), 명시 없으면 unknown',value=prior.get('condition',''))
    values['evidence_quote']=st.text_area('근거 문장을 위 문맥에서 그대로 복사',value=prior.get('evidence_quote',''))
    values['notes']=st.text_area('메모',value=prior.get('notes',''))
    if st.form_submit_button('저장'):
        try:
            save_human({'sample_id':sid,'annotator_id':annotator,**values},row)
            st.success('저장했습니다.');st.rerun()
        except ValueError as exc:st.error(str(exc))
if path.exists():st.download_button('내 판정 CSV 다운로드',path.read_bytes(),file_name=path.name)

