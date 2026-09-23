import json
from pathlib import Path

import pandas as pd

from pilot import ROOT,PROJECT,ART


def main():
    exp17=PROJECT/'experiments/17_tactile_preference_feasibility'
    r=json.loads((exp17/'artifacts/feasibility_results.json').read_text())
    p=json.loads((ART/'pilot_results.json').read_text())
    protocol=json.loads((ART/'pilot_protocol.json').read_text())
    lines=['# 촉감 선호 Feasibility — 전체 원문 조사', '',
        '## 실행 범위와 해석', '',
        '로컬 Amazon Fashion 원문 전체를 조사했다. 기존 v3 AXIS_PATTERNS를 그대로 재사용한 high-recall lexical screen이다. 키워드 일치는 속성 정확성이나 like/dislike의 정답이 아니다. 기존 선택 리뷰의 grounded 표본 수와 직접적인 semantic coverage 비교를 하지 않는다.', '',
        f"- 원문: {r['raw_reviews']:,} reviews / {r['raw_users']:,} users / {r['raw_items']:,} parent items",
        f"- 공식 leave-last-out: {r['official_events']:,} events; 원문과 정확히 연결된 공식 event {r['raw_to_official_unique_events_matched']:,}",
        f"- 키워드 포함 고유 event: {r['lexical_unique_events']:,}",
        f"- 키워드 리뷰 2개 이상 사용자: {r['lexical_user_density']['at_least']['2']:,}; 3개 이상: {r['lexical_user_density']['at_least']['3']:,}", '',
        '연결 키는 user_id + parent_asin + timestamp이다. 같은 키의 raw 중복은 첫 레코드를 사용한다. 선택된 원문 text/title, child ASIN, rating, verified_purchase, timestamp를 parquet에 보존했다. 전체 원문은 그대로 남아 있다.', '',
        '## 기존 추천 cohort 안의 지원 표본', '',
        '| 조건 | Validation | Test |','|---|---:|---:|']
    for label,key in [('평가 사용자','cohort_users'),('미래 target에 키워드','future_lexical'),('과거·미래 모두 키워드 (전체 상품 history)','past_and_future_lexical_all_history'),('과거·미래 모두 키워드 (eligible history)','past_and_future_lexical_eligible_history'),('과거 키워드 리뷰 2개 이상 + 미래 키워드','past_at_least_2_and_future'),('과거·미래 동일 키워드 계열','shared_lexical_axis_past_future'),('과거·미래 키워드 + v3 test-family target','joint_lexical_v3_test_family')]:
        lines.append(f"| {label} | {r['cohorts']['validation'][key]:,} | {r['cohorts']['test'][key]:,} |")
    lines += ['', '전체 상품 history에는 이미지 촉감 카탈로그 밖 상품의 리뷰도 포함된다. 이 확장은 사용자 리뷰에서 직접 선호를 추출할 때 가능하며, 해당 상품의 이미지 벡터가 있다는 뜻은 아니다.', '',
              '## Same-category 후보 가용성 진단', '',
              'parent family 중복 제거 및 seen-item 제거 후 같은 category 후보 수를 계산했다. 상품 첫 리뷰가 추천 시점보다 앞서는 경우만 남겼다. 첫 리뷰는 실제 판매 시작 시점의 대용 지표이며, 상품 availability를 완벽하게 복원하지 못한다.', '',
              '| 최소 후보 수 | Validation | Test |','|---|---:|---:|']
    for k in ['20','30','50']:
        lines.append(f"| {k} | {r['cohorts']['validation']['same_category_candidates_proxy'][k]} | {r['cohorts']['test']['same_category_candidates_proxy'][k]} |")
    lines += ['', 'Target category는 이 후보 개수 진단에만 사용했다. 실제 일반 추천의 oracle filter로 사용하지 않았다.', '',
              '## GO / NO-GO', '',
              '**조건부 GO: 소규모 preference annotation의 실행 가능성은 확인됐다. 대규모 개인화 추천 및 cold-start 성능 주장은 아직 보류한다.**', '',
              'Test 444명은 명확한 선호가 확인된 사용자가 아니라 lexical 후보 사용자다. 같은 계열을 과거·미래에 언급한 경우는 237명이며, v3 locked-test target family의 공동 lexical 표본은 51명뿐이다. 사람 검증 후 지원 표본이 더 줄 수 있다.', '',
              'Official leave-last-out은 사용자별 시간 순서이다. 다른 사용자의 미래 리뷰로 학습된 모델을 배제하는 global temporal protocol은 별도 설계가 필요하다. 기존 test를 설계 탐색에 활용했으므로 후속 확증 평가에는 새 holdout 또는 독립적인 human evaluation이 필요하다.', '',
              '다음 단계: 실험 18에서 property existence / local attitude / scope / condition을 구별하는 추출의 정확성을 사람에게 검증받는다. 이 결과와 표본 수를 확인한 뒤 실험 19 이후를 진행한다.', '',
              '## 재실행', '', '```bash',f'cd {exp17}', '/home/user/onsesang/miniconda3/envs/texture/bin/python run_feasibility.py', '/home/user/onsesang/miniconda3/envs/texture/bin/python -m unittest -v test_feasibility.py','```', '',
              '상세 통계와 입력 Arrow SHA-256은 artifacts/feasibility_results.json에 있다. 실행 산출물은 실험 17 내부에만 기록한다.']
    dest=exp17/'notion/FEASIBILITY_RESULTS.md';dest.parent.mkdir(exist_ok=True);dest.write_text('\n'.join(lines)+'\n')
    lines=['# 촉감 선호 추출 소규모 Pilot', '',
           '## 현재 상태', '',
           f"모델 추출 {p['model_records']}/{p['samples']}건. Schema와 원문 인용 자동 검증 통과 {p['schema_and_verbatim_pass']}건. 사람 판정 {p['human_completed']}건.", '',
           '**사람 검증 대기: 모델 출력의 semantic accuracy, F1, 사람 간 일치도는 아직 측정되지 않았다. 자동 검증 통과율을 정확도로 해석하지 않는다.**', '',
           '## 표본 및 모델', '',
           '실험 16의 validation 사용자에 해당하는 공식 train/validation 리뷰에서만 고른 64개 표본이다. 사용자 hash로 development 32개와 audit holdout 32개를 분리했다. 공식 test 리뷰는 사용하지 않았다. 표본 추출·prompt는 모델 출력 확인 전에 고정했다.', '',
           'Opinion cue, negation, rare-property, unmarked stratum에서 hash로 표본을 골랐다. 부족한 stratum은 남은 pool에서 hash 순서로 보충했다. 층화 표본이므로 전체 데이터의 선호 비율을 추정하는 데 사용하면 안 된다.', '',
           'Qwen/Qwen3-VL-32B-Instruct revision 0cfaf48183f594c314753d30a4c4974bc75f3ccb, 4-bit NF4 + BF16. 신규 preference pilot 추론만 수행했고 기존 v3 grounding이나 Last2 학습은 재실행하지 않았다.', '',
           '## 출력의 의미', '',
           '- property_phrase: 원문의 표현을 그대로 보존한 open-vocabulary 속성',
           '- class_id: 기존 14-class와 연결 가능한 경우의 mapping; 나머지는 unmapped',
           '- property_state: present / absent / uncertain / not_tactile',
           '- attitude: like / dislike / unknown / mixed; 표현된 속성 상태에 대한 평가',
           '- scope / condition: 부위와 상황; 명시되지 않으면 unknown',
           '- evidence_quote: 제공된 문맥에서 그대로 복사한 근거', '',
           '“I like that it is not thick”의 absent+like를 thick 선호 +1로 바로 바꾸지 않는다. 상황별 의견을 전역의 영구 선호로 전환하지 않는다. 현재는 annotation feasibility만 검사하며 signed user vector나 추천 score를 생성하지 않았다.', '',
           '## 자동 출력 통계 (사람 검증 전)', '',
           '```json',json.dumps({'attitudes':p['model_attitude_counts'],'property_states':p['model_property_state_counts'],'rejected':p['errors']},indent=2),'```', '',
           'Rejected output도 raw_output과 함께 보존한다. 원문과 맞지 않는 인용을 임의로 수정해 통과 처리하지 않았다.', '',
           '## Human audit 수행', '',
           '가능하면 두 사람이 동일 표본을 독립 판정한다. 먼저 development를 검토하여 오류 유형을 정리한다. Prompt를 바꾸면 새 버전으로 기록하고, 기존 audit holdout의 사람 답안을 보며 조정하지 않는다.', '',
           '웹 화면은 Qwen 답변을 보여주지 않는다. 각 annotator ID로 property, state, attitude, scope, condition, evidence를 입력한다. 원문 인용과 enum을 저장 전에 검증한다. 저장된 CSV는 annotations/<annotator_id>.csv이며 결과를 수정하면 해당 평가자의 같은 sample 행만 갱신한다.', '',
           '```bash',f'cd {ROOT}', '/home/user/onsesang/miniconda3/envs/texture/bin/streamlit run app.py --server.address 127.0.0.1 --server.port 8518','```', '',
           'VS Code Remote SSH의 Ports에서 8518을 포워딩한 뒤 로컬 브라우저에서 http://localhost:8518 에 접속한다. 이 문서 생성 시 서버는 상시 실행하지 않았다.', '',
           'CSV 입력도 가능하다. artifacts/human_annotation_template.csv를 복사해 작성하고 annotations/ 안에 저장한다. 평가자 ID, 모든 label field, verbatim evidence를 채워야 한다. 미완료 행은 invalid_human_rows로 보고되며 자동으로 사람 정답이 생성되지 않는다.', '',
           '판정 후 분석:', '', '```bash', '/home/user/onsesang/miniconda3/envs/texture/bin/python pilot.py analyze', '/home/user/onsesang/miniconda3/envs/texture/bin/python write_reports.py','```', '',
           '분석은 development/holdout 및 평가자별 모델 일치율과 support, 두 사람 간 raw agreement/Cohen kappa를 계산한다. 합의된 adjudicated gold가 없으면 이를 확정 정확도로 보고하지 않는다. 동일 단일 라벨만 존재하여 kappa가 정의되지 않는 경우 null로 기록한다.', '',
           '## 재현 순서', '', '```bash','python pilot.py prepare','python pilot.py infer','python pilot.py analyze','python -m unittest -v test_pilot.py','python write_reports.py','```', '',
           'prepare는 표본 및 빈 template을 다시 생성한다. infer는 기록된 sample ID를 건너뛰어 재개한다. 출력 실패도 완료된 추출 시도로 남는다. Prompt나 표본을 변경한 재실험은 기존 결과 파일을 재사용하지 않고 새 버전 폴더에서 수행해야 한다.']
    dest=ROOT/'notion/PREFERENCE_PILOT_RESULTS.md';dest.parent.mkdir(exist_ok=True);dest.write_text('\n'.join(lines)+'\n')


if __name__=='__main__':main()
