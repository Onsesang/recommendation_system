"""Produce Notion-importable Markdown and a self-contained GPT handoff."""
from pipeline import ART,ROOT,read,write,sha


def main():
    r=read(ART/'results.json');p=read(ART/'protocol.json');e=read(ART/'evaluation_protocol.json')
    lines=['# 명시적 촉감 선호 기반 추천 — 탐색 실험 19','',
      '**자동 실험 완료. 사용자 요청으로 human audit은 생략했다. 사람 검증된 선호 정확도·촉감 만족도·확증적 논문 성능으로 해석하지 않는다.**','',
      '## 1. 기존 실험과 차이','',
      '| 항목 | 실험 16 | 이번 실험 19 |','|---|---|---|',
      '| 사용자 촉감 정보 | 과거 상품 이미지 촉감 벡터 평균 | 과거 리뷰에서 Qwen이 추출한 명시적 like/dislike |',
      '| 추출 단위 | 상품 14차원 | 원문 표현과 위치를 보존한 모든 lexical occurrence |',
      '| 속성 부재 | 상품 확률에 포함 | 상태와 태도를 분리하고 불확실하면 보류 |',
      '| 카테고리 전이 | 전체 history 벡터 | 같은 category만; other·카테고리 미연결은 보류 |',
      '| 조건·부위 | 별도 분리 없음 | 무조건적 whole_garment/unknown만 primary; 나머지 원문 evidence 보존 |',
      '| 후보 생성 | BPR Top-300 | validation Recall@300으로 BPR/인기도 중 선택 |',
      '| 사람 검증 | 없음 | 없음; AI 예비 audit은 기준 검토에만 사용, gold로 사용하지 않음 |','',
      '실험16에서는 beta=.15, alpha=0으로 tactile 추가 효과가 없었다. 이번 실험은 후보 생성과 점수식을 함께 변경했으므로 16→19의 개선 전체를 tactile 효과라고 해석하면 안 된다. 이번 실험 내부의 explicit−category가 핵심 비교다.','',
      '## 2. 데이터 범위와 처리','',
      f"- 기존 validation 1,110명 / test 3,283명과 7,365 parent 상품 카탈로그 유지.",
      f"- 공식 split에 연결된 해당 평가 사용자들의 키워드 리뷰 {p['reviews']:,}개, 사용자 {p['users']:,}명, 표현 {p['occurrences']:,}개 전체 추출. 표본 수 제한 없음.",
      '- 원문 2,500,939개 전체에 대한 lexical 조사는 실험17을 재사용했다. 원문 전체를 Qwen으로 추출한 것은 아니며, 키워드 밖 표현의 recall은 측정하지 않았다.',
      f"- split별 occurrence: {p['occurrences_by_split']}",
      f"- 모델: {p['model']['model_id']} / revision {p['model']['revision']} / 4-bit NF4 + BF16; text-only 선호 추출.",
      '- 기존 Last2 이미지 확률은 재사용했다. 재학습, 기존 threshold 변경, raw dataset 수정은 하지 않았다.',
      '- 최초 실패와 formatting 재시도를 모두 보존했다. 두 차례 보정 후에도 통과하지 않은 항목은 추정해 채우지 않고 제외했다.','',
      '```json',__import__('json').dumps(r['extraction'],ensure_ascii=False,indent=2),'```','',
      '## 3. 실험 흐름과 점수','',
      '전체 평가 사용자 lexical occurrence → 고정 prompt Qwen 추출 → schema/정확한 원문 위치 검사 → 추천 시점 전 history만 필터 → category/class별 local preference → 고정 후보에서 reranking → validation weight 고정 → test 탐색 보고.','',
      '한 리뷰에서 같은 class가 여러 번 언급돼도 리뷰 하나의 가중치를 넘지 않도록 평균한다. 리뷰 간 충돌 역시 평균하며 0.5이면 방향성 없음으로 처리한다. open-vocabulary 원문과 scope/condition은 validated_evidence.parquet에 그대로 남긴다.','',
      'desired_presence는 상태와 평가의 조합이다. present+like 또는 absent+dislike는 1, present+dislike 또는 absent+like는 0이다. 이는 같은 class의 확률에 대한 국소적인 matching 방향일 뿐 반대 class를 생성하거나 영구 선호의 정답으로 간주하지 않는다. uncertain/unknown/mixed/not_tactile은 선호로 변환하지 않는다.','',
      '`utility = mean((2*desired_presence-1) * (item_probability-.5) * n/(n+2))`','',
      '`score = (1-alpha)*category_base_percentile + alpha*utility`','',
      'n은 해당 category/class에 대한 고유 리뷰 수다. 지원 evidence가 없으면 utility=0으로 category ranking을 유지한다. other를 제외하며 cross-category transfer는 0이다. 전반적 상품 긍정만으로 모든 촉감을 선호한다고 판단하지 않는다.','',
      'likes_only는 local attitude=like인 evidence만으로 별도 프로필을 만든다(부재 상태를 좋아하는 표현도 포함). shuffled는 사용자별 프로필을 교환하되 받는 사용자의 추천 시점보다 앞선 donor evidence만 사용한다. 단일 seed 탐색 대조군이며, 다중 shuffle 유의성 검정이 아니다.','',
      'review_only는 이번에 추출한 cohort-history의 상품 리뷰만 사용한다. 추천 시점 이전, 허용된 history split, 평가 사용자 본인 제외 규칙을 적용한다. sparse feature이므로 전체 리뷰 기반 oracle upper bound가 아니다. hybrid는 누락된 review feature를 이미지로 채우며 v3 test-family 상품은 항상 이미지를 사용한다.','',
      '## 4. Validation 선택','',
      '```json',__import__('json').dumps(r['candidate_selection'],ensure_ascii=False,indent=2),
      __import__('json').dumps(r['selection'],ensure_ascii=False,indent=2),'```','',
      '모든 branch의 alpha는 validation NDCG@10으로 따로 선택했다. 동률이면 작은 값을 선택한다. Test 평가 전에 selection.json을 기록했다. 기존 cohort를 앞선 연구에서 이미 열람했으므로 새로운 독립 확증 test라고 부르지 않는다.','',
      '## 5. Test 결과','',
      '| 방법 | NDCG@10 | HR@10 | MRR@10 |','|---|---:|---:|---:|']
    for name,m in r['metrics']['all'].items():lines.append(f"| {name} | {m['ndcg_at_10']:.6f} | {m['hr_at_10']:.6f} | {m['mrr_at_10']:.6f} |")
    lines+=['',f"Candidate Recall@300: {r['test_candidate_recall']:.6f}",'',
      'popularity_full_catalog는 전체 카탈로그 기준 참고선이다. 나머지 main 방법은 같은 Top-300 후보를 공유한다. Category나 tactile 점수에 따라 정답 상품을 후보에 강제로 넣지 않았다.','',
      '## 6. 표본 지원과 subset','',
      '```json',__import__('json').dumps(r['coverage'],ensure_ascii=False,indent=2),'```','',
      '| subset | n | Category NDCG@10 | Explicit NDCG@10 | Delta와 paired 95% CI |',
      '|---|---:|---:|---:|---|']
    for name,methods in r['metrics'].items():
        c=r['paired_bootstrap'][name]['explicit_minus_category']
        lines.append(f"| {name} | {methods['category']['n']} | {methods['category']['ndcg_at_10']} | {methods['explicit']['ndcg_at_10']} | {c['delta']} / {c['ci95']} |")
    delta=r['paired_bootstrap']['all']['explicit_minus_category']
    alpha=r['selection']['alphas']['explicit']
    lines+=['','## 7. 해석','',
      f"명시적 선호 branch의 선택 alpha는 {alpha}, category 대비 NDCG@10 차이는 {delta['delta']:.6f}, paired user bootstrap 95% CI는 {delta['ci95']}다.",
      ('Validation이 alpha=0을 선택했다. 따라서 이번 구성에서도 명시적 촉감 선호의 추가 기여가 선택되지 않았다.' if alpha==0 else '양의 alpha가 선택됐지만, 개선 여부는 category 대비 delta/CI와 지원 표본 수를 함께 해석해야 한다. AI 추출 정확도가 검증됐다는 뜻은 아니다.'),
      '얕은 history, 제한된 카탈로그, 조건/부위 보류, 오류를 포함할 수 있는 Qwen 라벨이 모두 영향을 줄 수 있다. 이 실험만으로 개별 원인의 인과적 기여를 확정하지 않는다.',
      'candidate_hit와 profile_supported 결과는 조건부 진단이다. 이 값이 좋아도 전체 사용자 결과를 대체할 수 없다. Cold subset은 이미지 학습에서 제외한 family이지, CF 상호작용이나 모든 다른 사용자의 미래 정보까지 배제한 cold-start가 아니다.','',
      '## 8. 미래 리뷰 비교 — 독립 정답 아님','',
      '```json',__import__('json').dumps(r['future_review_pseudo_consistency'],ensure_ascii=False,indent=2),'```','',
      '과거/미래 모두 같은 Qwen으로 추출했으므로 이는 pseudo-label consistency다. 사람 만족도, 추천된 상품을 직접 만져본 평가, 또는 AI 오류와 독립적인 검증을 대체하지 않는다. 이 통계는 가중치 선택이나 추천 점수에 사용하지 않았다.','',
      '## 9. 한계와 보존 검증','']
    lines += ['- '+x for x in r['limitations']]
    lines += ['',f"보호 대상으로 기록한 {len(r['protected_inputs_unchanged'])}개 입력 hash는 모두 동일하다. 원문·모델 전체 트리에 대한 과도한 보존 주장이 아니라 protocol.json에 나열된 입력 검증이다.",'',
      '## 10. 산출물과 재현','',
      '- artifacts/results.json: 전체 결과와 한계',
      '- artifacts/validated_evidence.parquet: 원문, focal offset, Qwen 판정',
      '- artifacts/validation_user_profiles.json / test_user_profiles.json: provenance가 연결된 사용자 프로필',
      '- artifacts/selection.json / validation_search.csv: validation 가중치 선택',
      '- artifacts/per_user_results.csv: 방법별 순위와 subset mask',
      '- artifacts/score_breakdowns.json: 고정 규칙으로 뽑은 5명 추천 점수 분해',
      '- artifacts/protocol.json / evaluation_protocol.json: 실행 규칙과 입력 hash',
      '- artifacts/annotations.jsonl / repair_annotations.jsonl: 최초 출력과 재시도 기록','',
      '```bash','python pipeline.py prepare','python evaluate.py candidates','python pipeline.py infer',
      'python pipeline.py repair','python pipeline.py repair','python -m unittest -v test_preference.py',
      'python evaluate.py evaluate','python write_report.py','```','',
      '기존 사람 audit 양식은 보존됐다. 나중에 실제 사람 판정을 수행하면 별도 human 결과로 추가할 수 있다. 현재 실험을 human-audited로 소급 변경하지 않는다.']
    folder=ROOT/'notion';folder.mkdir(exist_ok=True)
    (folder/'EXPLICIT_PREFERENCE_EXPLORATORY_RESULTS.md').write_text('\n'.join(lines)+'\n')
    handoff=['# GPT 분석 요청 — 실험 19','',
      '아래 보고서를 바탕으로 기존 실험16과의 차이, 구현 흐름, 결과, category 대비 촉감의 추가 효과, pseudo-label 한계를 한국어로 분석해 주세요. 사람 audit은 사용자 요청으로 생략됐습니다. 자동 검증 통과율을 의미 정확도로, 미래 Qwen 일치를 사람 만족도로 표현하지 마세요. 후보 생성이 달라진 실험 간 수치를 tactile의 인과적 효과로 비교하지 마세요.','',*lines]
    (folder/'GPT_EXPERIMENT_19_HANDOFF.md').write_text('\n'.join(handoff)+'\n')
    print('Notion report and GPT handoff written.')


if __name__=='__main__':main()
