"""Generate the final Notion-ready, evidence-linked experiment report."""
import pandas as pd
from common import *

def fmt(x):
    if x is None or (isinstance(x,float) and np.isnan(x)):return 'N/A'
    if isinstance(x,(float,np.floating)):return f'{float(x):.6f}'
    return str(x)

def metric_row(name,values,reason=''):
    if not values:return [name,'N/A','N/A','N/A',reason]
    return [name,fmt(values.get('ndcg_at_10')),fmt(values.get('hr_at_10')),fmt(values.get('mrr_at_10')),reason]

def table(headers,rows):
    return '| '+' | '.join(headers)+' |\n| '+' | '.join(['---']+['---:' for _ in headers[1:]])+' |\n'+'\n'.join('| '+' | '.join(map(str,row))+' |' for row in rows)

def main():
    stats=load_json(ART/'amazon_fashion_statistics.json');mapping=load_json(ART/'item_mapping_report.json');coverage=load_json(ART/'tactile_coverage.json')
    lock=load_json(ART/'selection_lock.json');general=load_json(ART/'general_recommendation_results.json');explicit=load_json(ART/'tactile_recommendation_results.json')
    cold=load_json(ART/'cold_start_results.json');sanity=load_json(ART/'sanity_checks.json');env=load_json(ART/'environment_report.json')
    if sanity.get('status')!='pass' or sanity.get('passed')!=sanity.get('total'):
        raise RuntimeError('final report requires a fully passing sanity audit')
    back=pd.read_csv(ART/'backbone_test_results.csv');valid=pd.read_csv(ART/'backbone_validation_results.csv');recall=pd.read_csv(ART/'candidate_recall.csv')
    mm=load_json(ART/'multimodal_recommendation_results.json');alpha=pd.read_csv(ART/'alpha_search.csv')
    generic=load_json(ART/'generic_feature_report.json');human=explicit.get('human_audit',{})
    positive_alpha=alpha[alpha.alpha>0].sort_values(['ndcg_at_10','alpha'],ascending=[False,True]).iloc[0]
    old=load_json(PROJECT/'experiments/16_recommendation_reranking/artifacts/recommendation_results.json')
    strong_tactile_name=f"Strong + Tactile (alpha={fmt(lock['alpha'])})"
    main_rows=[]
    for name in ('popularity','bpr','lightgcn','sasrec','esasrec'):
        row=back[back.model==name]
        main_rows.append(metric_row(name,None if row.empty else {k.replace('all_official_targets.',''):row.iloc[0][k] for k in row.columns if k.startswith('all_official_targets.')}))
    main_rows.append(metric_row(strong_tactile_name,general['strong_plus_tactile']['all']))
    if mm.get('status')=='complete_no_post_test_tuning':
        main_rows.append(metric_row('SMORE (generic image + text)',mm['generic_multimodal']['all']))
        main_rows.append(metric_row('SMORE + Last2 tactile',mm['generic_multimodal_plus_tactile']['all']))
    else:
        main_rows+= [metric_row('SMORE (generic image + text)',None,mm.get('reason','N/A')),metric_row('SMORE + Last2 tactile',None,mm.get('reason','N/A'))]
    cand=[]
    testrec=recall[recall.split=='test']
    for name,g in testrec.groupby('model',sort=False):
        values={int(r.k):r.recall for r in g.itertuples()};cand.append([name,*[fmt(values.get(k)) for k in (100,300,500,1000,3000)]])
    history=stats['evaluation_histories'];explicit_summary=explicit['test_summary']
    perclass=pd.read_csv(ART/'explicit_tactile_per_query.csv');perclass=perclass[(perclass.split=='test')&(perclass.method.isin(['non_tactile_popularity','last2_tactile']))&(~perclass['query'].str.contains(r'\+'))]
    classrows=[]
    for q,g in perclass.groupby('query',sort=False):
        b=g[g.method=='non_tactile_popularity'].iloc[0];t=g[g.method=='last2_tactile'].iloc[0]
        classrows.append([q,fmt(b.ndcg_at_10),fmt(t.ndcg_at_10),fmt(t.precision_at_10),int(t['items'])])
    same=pd.read_csv(ART/'explicit_tactile_same_category.csv');same=same[(same.split=='test')&(~same['query'].str.contains(r'\+'))]
    samecatrows=[]
    for q,g in same.groupby('query',sort=False):
        b=g[g.method=='non_tactile_popularity'];t=g[g.method=='last2_tactile']
        samecatrows.append([q,fmt(b.ndcg_at_10.mean()),fmt(t.ndcg_at_10.mean()),fmt(t.precision_at_10.mean()),len(t)])
    supportrows=[]
    for name,value in general['support_cohorts'].items():
        delta=value['proposed_ndcg_at_10']-value['strong_ndcg_at_10']
        supportrows.append([name,f"{value['users']:,}",fmt(value['strong_ndcg_at_10']),
                            fmt(value['proposed_ndcg_at_10']),fmt(delta)])
    coldrows=[]
    for name,value in cold.items():
        for method,key in [('Strong','strong'),(strong_tactile_name,'strong_plus_tactile'),('Generic MM','generic_multimodal'),('MM + Tactile','multimodal_plus_tactile')]:
            m=value.get(key);coldrows.append([name,method,'N/A' if not m else fmt(m.get('ndcg_at_10')),'N/A' if not m else fmt(m.get('hr_at_10')),value['support']])
    now=time.strftime('%Y-%m-%d %H:%M KST',time.localtime())
    text=f"""# Strong Recommender + Tactile 전체 실험 결과

생성 시각: {now}  
실험 경로: `{ROOT}`  
프로토콜 seed: `{SEED}`

## 1. 연구 질문

- RQ1: Amazon Reviews'23 Amazon_Fashion 전체 catalog에서 BPR보다 강한 추천 backbone이 candidate retrieval과 Top-K를 개선하는가?
- RQ2: validation으로 고정한 후보군에 Last2 촉각 벡터를 더하면 일반 next-item 추천이 개선되는가?
- RQ3: 일반 추천과 분리된 명시적 tactile query에서 Last2가 촉각 관련 상품을 더 잘 정렬하는가?

## 2. 기존 BPR 실험이 실패한 이유

기존 실험은 추천 catalog를 촉각 라벨 교집합으로 먼저 줄였다. 보존된 artifact 기준 catalog는 {old['data']['catalog']['eligible_items']:,}/{old['data']['catalog']['official_items']:,} ({old['data']['catalog']['item_coverage']:.2%}), test에서 history가 남은 사용자는 {old['data']['test']['eligible_users_with_pretest_history']:,}명이었고, candidate Recall@300은 {old['candidate_recall']['recall_at_300']:.6f}였다. Validation은 alpha=0을 선택해 proposed와 category-aware가 같았다. 이 결과는 촉각 표현의 무용성을 입증하지 않으며 retrieval·coverage 병목을 함께 반영한다. 기존 제한 실험과 이번 all-user metric은 평가 모집단이 달라 숫자를 직접 우열 비교하지 않는다.

## 3. 이번 재설계 핵심

추천 학습과 후보 생성은 {stats['processed']['items']:,}개 전체 catalog에서 수행했다. 이미지가 없는 상품도 제거하지 않았고, Last2는 별도의 image-available item feature로만 결합했다. backbone, K, profile 방식, class 수, alpha는 validation에서 고정한 뒤 test를 한 번만 열었다.

## 4. Amazon Reviews'23 Amazon_Fashion

- Raw: users {stats['raw']['users']:,}, items {stats['raw']['items']:,}, reviews {stats['raw']['reviews']:,}
- Processed official split: users {stats['processed']['users']:,}, parent items {stats['processed']['items']:,}, interactions {stats['processed']['interactions']:,}
- Train/validation/test events: {stats['split_event_counts']['train']:,} / {stats['split_event_counts']['validation']:,} / {stats['split_event_counts']['test']:,}
- Interaction은 review/rating event이며 click 또는 purchase로 단정하지 않는다. verified purchase는 raw flag가 참일 때만 근거가 있다.

## 5. User history distribution

| Evaluation | zero | >=1 | >=3 | >=5 | median | mean |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Validation | {history['validation']['available_history']['zero']:,} | {history['validation']['available_history']['ge_1']:,} | {history['validation']['available_history']['ge_3']:,} | {history['validation']['available_history']['ge_5']:,} | {fmt(history['validation']['available_history']['median'])} | {fmt(history['validation']['available_history']['mean'])} |
| Test | {history['test']['available_history']['zero']:,} | {history['test']['available_history']['ge_1']:,} | {history['test']['available_history']['ge_3']:,} | {history['test']['available_history']['ge_5']:,} | {fmt(history['test']['available_history']['median'])} | {fmt(history['test']['available_history']['mean'])} |

history가 없는 사용자는 모든 모델에서 train popularity로 fallback했다. Validation의 72.72%, test의 86.18%가 이 공통 fallback이므로 all-user metric은 personalized 모델 차이를 크게 희석한다. 낮은 절대값의 원인을 0-history 하나에만 귀속하지 않는다.

## 6. Item/parent mapping

ASIN→parent_ASIN은 raw review의 명시적 필드를 사용했다. v3 tactile products {mapping['tactile_products']:,}개 중 {mapping['mapped_child_asins']:,}개를 매핑했고, parent는 {mapping['mapped_parents']:,}개다. fuzzy matching은 사용하지 않았다.

## 7. Strong recommendation backbones

동일 catalog/split/seen filtering으로 Popularity, BPR-MF, LightGCN, SASRec, eSASRec을 비교했다. eSASRec은 공식 구현의 LiGR+SwiGLU 구조를 vendoring하고 NumPy 2 환경 불일치 때문에 local data/evaluation adapter와 64-negative sampled softmax를 사용했다. 이를 single SOTA가 아닌 recent strong reproducible recommender로 표현한다.

## 8. Backbone validation

`artifacts/backbone_validation_results.csv`가 두 learning rate와 best epoch의 근거다. Primary validation NDCG@10으로 `{lock['strong_backbone']}`을 선택했다.

## 9. Candidate recall

{table(['Model','Recall@100','@300','@500','@1000','@3000'],cand)}

Validation 규칙으로 K=`{lock['candidate_k']}`를 고정했다. Recall≥0.80 조건 충족 여부: `{lock['candidate_rule_satisfied']}`. 미충족이면 K=3000을 사용하되 retrieval bottleneck이 해소됐다고 주장하지 않는다.

## 10. Selected backbone

선택 모델: `{lock['strong_backbone']}`. Tie-break는 NDCG@10 → HR@10 → MRR@10 → 사전 정의 모델 순서다. 효율과 정확도는 validation artifact에 함께 보존했다.

## 11. Generic multimodal baseline

이 결과는 공식 SMORE reproduction이 아니라 **SMORE-derived scalable adaptation**이다. Upstream commit `c745bb9`의 forward/spectrum-fusion과 BPR/InfoNCE objective form을 사용했지만, full-catalog 실행을 위해 fixed-seed FAISS IVF approximate kNN(`nlist=7270`, `nprobe=32`, index-training sample 150,000), self-edge 제거, negative cosine clamp, reverse-edge union과 재정규화를 적용했다. InfoNCE는 매 epoch shuffled interaction의 첫 1,024개로 제한했고 local optimizer·negative sampling·validation loop를 사용했다. Exact-kNN neighbor recall이나 adapter ablation은 측정하지 않아 architecture 효과와 graph approximation error를 분리할 수 없다.

입력 512D feature extractor는 pinned FashionCLIP snapshot으로 고정했지만 SMORE 내부 modality embedding table은 `freeze=False`로 학습된다. Dedicated Last2 probability 또는 tactile pseudo-label을 generic baseline 입력에 넣지는 않았으나, 이미지와 metadata text 자체가 tactile cue를 암묵적으로 포함할 수 있다. 상태: `{mm.get('status')}`; generic feature report: `{generic.get('status')}`.

## 12. Amazon 전체 tactile inference

공식 `fashionclip_last2.pt` SHA-256 `{CHECKPOINT_SHA}`를 inference-only로 사용했다. Last2 재학습, Qwen 재실행, threshold 재튜닝, taxonomy 변경은 없었다. 출력은 binary threshold가 아닌 14D continuous probability다.

## 13. Tactile coverage

| Stage | Items |
| --- | ---: |
| Recommendation catalog | {coverage['catalog_items']:,} |
| Metadata available | {coverage['metadata_available']:,} |
| Main image URL available | {coverage['image_url_available']:,} |
| Image downloaded or cache-verified | {coverage['image_download_or_cache_success']:,} |
| Last2 inference available | {coverage['last2_inference_success']:,} |

Coverage={coverage['coverage_fraction']:.2%}, 기존 8,498개 대비 {coverage['expansion_ratio_vs_8498']:.2f}배다. 실패/미제공 item은 제거하지 않고 tactile adjustment를 neutral로 유지했다.

## 14. User tactile profile

Category-local historical mean을 사용했다. `all_history`와 `rating>=4`, 14-class와 사전 정의 reliable 8-class를 validation ablation했다. 다른 category의 촉감 선호를 strong default로 전이하지 않는다. 역사 평균은 선호의 증거가 아니라 noisy proxy다. 여기서 category는 official taxonomy가 아니라 title keyword로 만든 미검증 11-category heuristic이며, 오분류와 `other` pooling이 어떤 history가 profile에 들어가는지 바꿀 수 있다.

## 15. Alpha search

선택: profile=`{lock['profile_method']}`, classes={lock['tactile_classes']}, alpha=`{lock['alpha']}`; validation NDCG@10={fmt(lock['alpha_validation_ndcg_at_10'])}. alpha=0을 포함한 0.05 간격 전체 표는 `artifacts/alpha_search.csv`에 있다. 최선의 양수 alpha 조합은 profile=`{positive_alpha['profile']}`, classes={int(positive_alpha['classes'])}, alpha={fmt(positive_alpha['alpha'])}, NDCG@10={fmt(positive_alpha['ndcg_at_10'])}로 alpha=0보다 낮았다. 따라서 profile/class 선택은 alpha=0에서 성능상 식별되지 않는 tie-break 기본값이다.

## 16. General next-item result

{table(['Method','NDCG@10','HR@10','MRR@10','Note'],main_rows)}

Held-out target은 다음 Amazon interaction이지 촉감 만족도 ground truth가 아니다.

## 17. Strong vs Strong + Tactile

- Strong NDCG@10: {fmt(general['strong']['all']['ndcg_at_10'])}
- Strong + tactile NDCG@10: {fmt(general['strong_plus_tactile']['all']['ndcg_at_10'])}
- Paired Δ: {fmt(general['bootstrap']['ndcg_at_10']['mean'])}, 95% CI [{fmt(general['bootstrap']['ndcg_at_10']['ci95_low'])}, {fmt(general['bootstrap']['ndcg_at_10']['ci95_high'])}]
- Rank movement: {general['rank_movement']}

Validation이 alpha=0을 선택했으므로 최종 Strong+tactile 구성은 Strong과 수학적으로 동일하다. 따라서 test의 delta=0 및 CI=[0,0]은 촉각 효과에 대한 독립적인 무효효과 검정이 아니라 validation 단계에서 tactile 항을 비활성화한 결과다.

## 18. Multimodal vs Multimodal + Tactile

{('Paired Δ NDCG@10='+fmt(mm['bootstrap']['ndcg_at_10']['mean'])+', 95% CI ['+fmt(mm['bootstrap']['ndcg_at_10']['ci95_low'])+', '+fmt(mm['bootstrap']['ndcg_at_10']['ci95_high'])+'].' if mm.get('status')=='complete_no_post_test_tuning' else 'N/A: '+mm.get('reason','multimodal run unavailable'))}

여기서 `SMORE + Tactile`은 SMORE를 Last2와 함께 재학습한 3-modality architecture가 아니라, validation으로 고정한 SMORE 후보·점수에 동일한 Last2 post-hoc reranker를 적용한 결과다. 따라서 interaction+tactile 또는 in-model image+text+tactile ablation으로 해석하지 않는다.

## 19. Tactile-support cohort

{table(['Profiled history items','Users','Strong NDCG@10','Strong + Tactile','Delta'],supportrows)}

support 0/1/2/3–4/5+는 상호배타적인 고정 diagnostic이며 이 cohort를 test 성능으로 선택하지 않았다. 원 명세의 겹치는 `3+` 집계는 이 표에 없으므로 후속 보완 대상으로 남긴다.

## 20. Cold-start result

{table(['Cohort','Method','NDCG@10','HR@10','Support'],coldrows)}

Train-count cold cohort(0, <=5, <=10)는 protocol에서 test 전에 고정했다. `outside_v3_tactile_training_family`는 deterministic하게 계산했지만 locked protocol에 없었던 supplementary diagnostic이며 confirmatory cohort로 해석하지 않는다.

## 21. Explicit tactile-query result

| Method | Mean tactile NDCG@10 | Mean Precision@10 |
| --- | ---: | ---: |
| Non-tactile popularity | {fmt(explicit_summary['non_tactile_popularity']['mean_ndcg_at_10'])} | {fmt(explicit_summary['non_tactile_popularity']['mean_precision_at_10'])} |
| Generic multimodal | N/A | N/A |
| Last2 tactile | {fmt(explicit_summary['last2_tactile']['mean_ndcg_at_10'])} | {fmt(explicit_summary['last2_tactile']['mean_precision_at_10'])} |
| Dev-selected fusion | {fmt(explicit_summary['selected_fusion']['mean_ndcg_at_10'])} | {fmt(explicit_summary['selected_fusion']['mean_precision_at_10'])} |

Query benchmark에는 user ID가 없어 non-tactile baseline은 personalized strong model이 아니라 train popularity다. 기존 Experiment 14에서 같은 test를 이미 관찰했으므로 fresh confirmatory evidence가 아닌 exploratory replication이다.

{table(['Class','Popularity NDCG@10','Last2 NDCG@10','Last2 Precision@10','Known items'],classrows)}

Family bootstrap Last2−non-tactile Δ NDCG@10={fmt(explicit['family_bootstrap_last2_minus_non_tactile']['mean_delta_ndcg_at_10'])}, 95% CI [{fmt(explicit['family_bootstrap_last2_minus_non_tactile']['ci95_low'])}, {fmt(explicit['family_bootstrap_last2_minus_non_tactile']['ci95_high'])}].

## 22. Same-category tactile result

{table(['Class','Popularity mean NDCG@10','Last2 mean NDCG@10','Last2 mean Precision@10','Category cells'],samecatrows)}

전체 category/query cell은 `artifacts/explicit_tactile_same_category.csv`에 있으며 mask=0은 negative가 아니라 평가에서 제외했다.

## 23. Qualitative examples

`artifacts/qualitative_examples.json`은 largest gain, median-nearest, largest loss를 uid tie-break로 자동 선택하며 각 방향에 실제 변화가 있을 때만 최대 3개를 남긴다. alpha=0인 strong 결과에서는 gain/loss가 빈 배열인 것이 정상이다. 성공만 cherry-pick하지 않았다.

## 24. Human audit connection

Experiment 15 manifest는 {human.get('total_rows','N/A')}개이고 live annotation CSV에는 completed {human.get('completed_rows','N/A')}개가 있으나 audit 전체는 미완료다. Cached result는 `{human.get('cached_result_status','N/A')}`/{human.get('cached_completed_rows','N/A')}로 live CSV보다 오래됐다. 작성자 provenance가 artifact에 기록되지 않아 이 5개를 quantitative human-gold 결과로 통합하지 않았고, AI 판정을 human label로 취급하지 않았다.

## 25. Limitations

- 데이터가 매우 sparse하고 test 사용자의 다수가 0-history여서 personalized model의 all-user 이점이 희석된다.
- 다음 review/rating은 tactile satisfaction이 아니다.
- historical tactile mean은 preference proof가 아니다.
- eSASRec/SMORE는 환경·scale adapter를 사용했으므로 upstream의 다른 dataset 숫자와 직접 비교할 수 없다.
- FAISS graph의 exact-neighbor recall과 scale-adapter ablation이 없어 SMORE architecture 효과를 approximation error와 분리할 수 없다.
- Generic FashionCLIP에는 dedicated Last2 입력은 없지만 이미지·text의 암묵적 tactile cue까지 제거된 baseline은 아니다.
- title keyword category heuristic은 검증된 taxonomy가 아니다.
- tactile query ground truth는 기존 pseudo-label이며 이미 관찰된 family-heldout test다.
- candidate recall이 낮으면 reranker는 target을 복구할 수 없다.

## 26. Offline evaluator와 demo의 범위

```text
Offline next-item evaluator: Amazon 전체 catalog → validation-selected backbone Top-K
→ title-heuristic category-local historical tactile proxy
→ frozen Last2 continuous similarity → model별 validation-locked alpha → Top-10

Demo (`app.py`/`recommend.py`): explicit desired-class slider 기반 설명용 ranking
(historical category-local profile 경로와 동일하지 않으며 실험의 production service 구현으로 간주하지 않음)
```

`reproduce.sh`는 clean reconstruction 순서를 문서화하지만, 현재 완료 디렉터리에서 one-shot test guard 때문에 처음부터 재실행하는 명령이 아니다.

Sanity checks: `{sanity['status']}` ({sanity['passed']}/{sanity['total']}); 환경: torch {env['torch']}, CUDA {env['cuda_build']}, CUDA available={env['cuda_available']}.
"""
    out=ROOT/'notion/STRONG_RECOMMENDER_TACTILE_RESULTS.md';out.parent.mkdir(parents=True,exist_ok=True)
    tmp=out.with_suffix(out.suffix+'.tmp');tmp.write_text(text);os.replace(tmp,out)
    event('report','complete',path=str(out),bytes=out.stat().st_size)

if __name__=='__main__':main()
