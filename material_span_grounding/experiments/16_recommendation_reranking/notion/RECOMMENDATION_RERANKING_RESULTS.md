# Amazon Fashion Two-stage Recommendation Reranking

## 1. 연구 질문

Amazon 사용자의 과거 review/rating interaction으로 만든 추천 후보에서 category preference를 통제한 뒤에도, 공식 `fashionclip_last2.pt`의 14차원 촉감 표현을 추가하면 다음 interaction 상품의 Top-10 순위가 개선되는가?

결론은 **아니다**. Validation NDCG@10이 선택한 `alpha_star`는 `0.00`이다. 따라서 잠금 test에서 Proposed는 Category-aware recommender와 정확히 같으며, 촉감 표현의 추가 기여는 0이다. 반면 category-aware reranking 자체는 Vanilla BPR보다 높았다.

## 2. Amazon recommendation ground truth 설명

데이터는 McAuley-Lab의 Amazon Reviews 2023, revision `2aa726ef444e72c6a1364c4baa0bcdfb1de55db6`, `benchmark/0core/last_out/Amazon_Fashion.*.csv`이다. 공식 leave-last-out 파일을 수정 없이 사용했다.

Ground truth는 사용자의 **다음 review/rating interaction**이다. Click, conversion 또는 확정 purchase ground truth가 아니다. Primary에서는 rating과 무관하게 모든 interaction을 implicit positive로 취급했다.

## 3. Dataset overlap / ID mapping

추천 item ID는 `parent_asin`이다. 기존 8,498개 tactile product는 child ASIN 중심이므로 기존 product metadata의 명시적 `parent_asin`을 이용해 매핑했다. 한 parent에 여러 child가 있으면 Last2 continuous probability의 산술 평균을 parent profile로 사용했다.

| 항목 | 값 |
|---|---:|
| Tactile child IDs | 8,498 |
| 명시적 parent profiles / eligible catalog | 7,365 |
| Amazon official item IDs | 825,869 |
| Exact child-ID overlap | 7,083 |
| Parent mapping overlap | 7,365 / 7,365 |
| Unmatched tactile parents | 0 |
| Unmatched Amazon recommendation IDs | 818,504 |
| 전체 Amazon item 대비 catalog coverage | 0.892% |
| 공식 전체 interaction | 2,474,375 |
| Eligible interaction | 196,879 (7.957%) |
| Eligible interaction을 하나라도 가진 user | 190,563 |

System A/B/C 모두 동일한 7,365개 catalog를 사용했다.

## 4. Train-validation-test protocol

| Split | Raw interactions | Eligible interactions | 평가 cohort |
|---|---:|---:|---:|
| Train | 157,490 | 12,306 | — |
| Validation | 281,395 | 22,063 | 1,110 users |
| Test | 2,035,490 | 162,510 | 3,283 users |

Validation cohort는 target이 eligible catalog에 있고 eligible train history가 1개 이상인 user이다. Test cohort는 target이 eligible catalog에 있고 eligible train+validation history가 1개 이상인 user이다. Target coverage는 validation 7.841%, test 7.984%이다.

Validation user profile에는 train만, test user profile에는 train+validation만 사용했다. Held-out target은 포함하지 않았다. 시간 역전 0건, target-in-history 0건이다.

## 5. Vanilla BPR

PyTorch BPR-MF를 구현했다. 입력은 `user_id`, `item_id`, implicit interaction뿐이며 image, tactile, category, review text와 Qwen은 사용하지 않았다.

- Embedding dimension 64, Adam, learning rate `1e-3`, weight decay `1e-6`
- Positive당 uniform negative 2개, batch 4,096
- 최대 100 epochs, validation NDCG@10 patience 10
- Best epoch 23, validation NDCG@10 `0.005544`
- Test를 보기 전에 train+validation으로 정확히 23 epochs 재학습

## 6. Category-aware reranker

각 user의 추천 시점 전 history에서 category 빈도를 계산했다. Candidate item의 category 확률을 category score로 사용하며 tactile 정보는 사용하지 않는다.

`S_category = (1-beta) S_base_norm + beta S_category_norm`

Validation grid `0.00..1.00` (step 0.05)에서 NDCG@10 최대, 동률이면 작은 값 규칙으로 `beta_star=0.15`를 잠갔다. Category-aware validation NDCG@10은 `0.008811`이다.

## 7. Last2 tactile profile

Checkpoint는 `experiments/12_class_multilabel_fashionclip_ft/models/fashionclip_last2.pt`이며 SHA-256은 `073b542a9d6bd4450aa1f48596c756cc0812b1b5d914945e8f94f7c3fda1934a`이다. Inference 전후 hash가 같다.

Pinned FashionCLIP processor를 사용해 8,498개 이미지를 추론했다. Class order는 `soft, firm, smooth, rough, non_elastic, elastic, thin, thick, flexible, stiff, warm, cool, spongy, crisp`이다. Thresholded label이 아닌 14차원 continuous probability를 사용했다. Last2 재학습, threshold tuning, Qwen 실행, target 재생성은 하지 않았다.

## 8. User tactile preference construction

Primary user profile은 추천 시점 전 eligible history item의 14차원 parent profile을 동일 가중 평균했다. Candidate와 user profile 사이 cosine similarity를 tactile score로 사용했다.

Secondary sensitivity는 history 중 `rating>=4`인 item만 평균했다. 이는 primary와 분리했다.

## 9. Candidate generation

각 user에 대해 전체 7,365개 eligible catalog를 BPR로 scoring하고 이미 본 item을 제거한 뒤 Top-300을 만들었다. 세 main method는 동일한 user, catalog, filtering, target, candidate set을 사용했다. 모든 component는 Top-300 안에서 average-tie percentile rank로 `[0,1]` 정규화했다.

## 10. Weight tuning

### beta search

`beta_star=0.15`이며 validation NDCG@10은 `0.008811`이다. 전체 결과는 `artifacts/validation_weight_search.csv`에 있다.

### alpha search

`S_non_tactile`을 다시 percentile-normalize한 뒤 `S_final=(1-alpha)S_non_tactile_norm + alpha S_tactile_norm`을 계산했다.

| alpha | Val NDCG@10 | HR@10 | MRR@10 |
|---:|---:|---:|---:|
| 0.00 | 0.008811 | 0.014414 | 0.007075 |
| 0.05 | 0.008687 | 0.012613 | 0.007412 |
| 0.10 | 0.007734 | 0.012613 | 0.006141 |
| 0.15 | 0.006784 | 0.011712 | 0.005218 |
| 0.20 | 0.006021 | 0.010811 | 0.004489 |
| 0.25 | 0.005677 | 0.010811 | 0.004092 |
| 0.30 | 0.005690 | 0.011712 | 0.003875 |
| 0.35 | 0.006113 | 0.013514 | 0.003947 |
| 0.40 | 0.006357 | 0.014414 | 0.004031 |
| 0.45 | 0.006641 | 0.015315 | 0.004146 |
| 0.50 | 0.006232 | 0.013514 | 0.004085 |
| 0.55 | 0.006508 | 0.014414 | 0.004189 |
| 0.60 | 0.006090 | 0.012613 | 0.004135 |
| 0.65 | 0.005868 | 0.011712 | 0.004098 |
| 0.70 | 0.005961 | 0.011712 | 0.004220 |
| 0.75 | 0.005584 | 0.010811 | 0.003995 |
| 0.80 | 0.005634 | 0.009910 | 0.004325 |
| 0.85 | 0.004906 | 0.009910 | 0.003349 |
| 0.90 | 0.005100 | 0.011712 | 0.003127 |
| 0.95 | 0.004584 | 0.010811 | 0.002766 |
| 1.00 | 0.003687 | 0.007207 | 0.002668 |

따라서 `alpha_star=0.00`이다. `alpha=0`과 Category-aware ranking의 완전 일치도 자동 검증했다. Optional Vanilla+tactile ablation은 validation에서 weight `0.10`을 선택했으나 test NDCG@10 `0.012088`로 Vanilla `0.013416`보다 낮았다.

## 11. Main recommendation result

| Method | NDCG@10 | HR@10 | MRR@10 | NDCG@5 | HR@5 |
|---|---:|---:|---:|---:|---:|
| Popularity | 0.046859 | 0.092294 | 0.032755 | 0.040061 | 0.070972 |
| Vanilla BPR | 0.013416 | 0.024063 | 0.010165 | 0.011082 | 0.016753 |
| Category-aware | 0.017149 | 0.029851 | 0.013311 | 0.014014 | 0.020104 |
| Proposed Tactile-aware | 0.017149 | 0.029851 | 0.013311 | 0.014014 | 0.020104 |

Locked values: `candidate K=300`, `beta_star=0.15`, `alpha_star=0.00`.

Popularity가 학습 BPR보다 훨씬 강하므로 BPR candidate generator의 절대 성능이 이 downstream 실험의 중요한 제한이다.

## 12. Candidate recall

| K | Validation Recall | Test Recall |
|---:|---:|---:|
| 100 | 0.059459 | 0.094730 |
| 200 | 0.095495 | 0.138593 |
| 300 | 0.138739 | 0.177277 |

Test target의 82.27%가 Top-300 밖이므로 reranker가 살릴 수 없다. 이 상한과 Top-10 reranking 효과를 구분해야 한다.

## 13. Proposed vs Category-aware

| Comparison | Delta NDCG@10 | 95% CI |
|---|---:|---:|
| Category − Vanilla | +0.003733 | [0.001651, 0.006077] |
| Proposed − Vanilla | +0.003733 | [0.001651, 0.006077] |
| Proposed − Category | 0.000000 | [0.000000, 0.000000] |

핵심 질문에 대한 답은 “현재 protocol과 representation에서는 category를 넘어서는 추가 tactile contribution이 validation에서 선택되지 않았다”이다.

## 14. Bootstrap confidence interval

User 단위 paired bootstrap 1,000회, seed `20260904`를 사용했다. 동일 bootstrap sample에서 method 차이를 계산했다. Proposed−Category의 NDCG@10, HR@10, MRR@10 차이는 모두 0이고 CI도 `[0,0]`이다. 이는 불확실한 작은 개선이 아니라, validation이 `alpha=0`을 선택해 두 ranking이 동일해진 결과다.

## 15. Cold-start target subset

V3 locked-test family에 속한 target 410개를 별도로 평가했다.

| Method | NDCG@10 | HR@10 | MRR@10 |
|---|---:|---:|---:|
| Vanilla | 0.005994 | 0.014634 | 0.003397 |
| Category-aware | 0.004903 | 0.012195 | 0.002686 |
| Proposed | 0.004903 | 0.012195 | 0.002686 |

이 subset에서는 category reranking도 Vanilla보다 낮았고 tactile 추가 기여는 없었다.

## 16. Positive-rating sensitivity

Test target rating이 4 이상인 2,434명에서:

| Method | NDCG@10 | HR@10 | MRR@10 |
|---|---:|---:|---:|
| Vanilla | 0.015680 | 0.027116 | 0.012177 |
| Category-aware | 0.018477 | 0.032046 | 0.014381 |
| Proposed | 0.018477 | 0.032046 | 0.014381 |

Rating>=4 history profile을 만들 수 있는 2,428명에서도 locked `alpha=0`이므로 촉감 profile 선택은 ranking에 영향을 주지 않는다. 이 cohort의 NDCG@10은 0.019469이다.

## 17. Category별 결과

| Target category | Support | Vanilla NDCG@10 | Category / Proposed NDCG@10 |
|---|---:|---:|---:|
| accessory | 371 | 0.013870 | 0.012678 |
| dress | 1,162 | 0.003529 | 0.006297 |
| other | 134 | 0.002157 | 0.014925 |
| outerwear | 43 | 0.000000 | 0.000000 |
| pants | 265 | 0.009547 | 0.009501 |
| skirt | 98 | 0.003072 | 0.000000 |
| sleepwear | 39 | 0.000000 | 0.000000 |
| sweater | 85 | 0.000000 | 0.000000 |
| swimwear | 6 | 0.000000 | 0.000000 |
| top | 934 | 0.032064 | 0.041727 |
| underwear | 146 | 0.011861 | 0.005405 |

Sparse category는 추론보다 support를 우선 확인해야 한다.

## 18. Qualitative examples

Main Proposed와 Category-aware의 rank 변화는 improved 0명(0%), same 3,283명(100%), worse 0명(0%)이다. Mean/median censored rank gain도 0이다. 따라서 존재하지 않는 성공/실패 사례를 만들지 않았다. `qualitative_examples.json`에는 deterministic median 사례 5명과 세 method의 Top-10, history, ground truth, component scores, tactile match detail이 있다. Strong/failure group에는 `alpha_star=0`으로 사례가 없다는 명시적 note가 있다.

## 19. 서비스 구조

`recommend.py`는 다음 API를 제공한다.

```python
recommend(user_id, desired_tactile=None, category_filter=None, top_k=10)
```

Known user는 train+validation history로 BPR candidate를 만든다. Optional category filter는 candidate generation 전에 적용한다. `desired_tactile`이 있으면 선택한 class 확률만 평균하며, 선택하지 않은 class는 negative로 보지 않는다. 없으면 historical tactile profile cosine을 사용한다. Locked `alpha_star`를 기본 적용한다.

`alpha_star`는 next-item validation ground truth용으로 최적화됐으며 explicit tactile-query 만족도를 직접 최적화한 값은 아니다. 현재 `alpha_star=0`이므로 실제 서비스 기본 설정에서 tactile 선택은 순위를 바꾸지 않는다.

실행:

```bash
cd /home/user/onsesang/material_span_grounding/experiments/16_recommendation_reranking
/home/user/onsesang/miniconda3/envs/texture/bin/streamlit run app.py --server.address 0.0.0.0 --server.port 8516
```

## 20. 한계

1. Tactile catalog가 Amazon 전체 item의 0.892%라 target/user coverage가 작다.
2. Test candidate Recall@300이 17.73%라 reranking 상한이 낮다.
3. 사용자 대부분의 eligible history가 매우 짧아 category와 tactile profile이 불안정할 수 있다.
4. Review/rating interaction은 클릭 또는 구매 의도와 같지 않다.
5. Popularity가 BPR을 크게 앞서 BPR-MF candidate generator가 약하다. 향후 stronger sequential/collaborative candidate model은 별도 사전 등록 실험이 필요하다.
6. Last2 profile은 tactile classification supervision으로 학습됐고 next-item preference에 직접 최적화되지 않았다.
7. Validation이 `alpha=0`을 선택했으므로 현재 결과는 tactile-aware 서비스의 효용을 지지하지 않는다. 이를 test 이후 다른 alpha로 바꾸면 protocol 위반이다.

## 재현 순서

```bash
cd /home/user/onsesang/material_span_grounding/experiments/16_recommendation_reranking
PY=/home/user/onsesang/miniconda3/envs/texture/bin/python
$PY inspect_data.py
$PY build_tactile_profiles.py
$PY build_interactions.py
$PY build_user_profiles.py
$PY train_vanilla_recommender.py
$PY tune_reranker.py
$PY evaluate_recommender.py
$PY -m unittest -v test_recommendation.py
```

`tune_reranker.py`가 validation에서 weight를 잠근 다음에만 `evaluate_recommender.py`를 실행해야 한다. 본 실행에서는 test 결과를 근거로 model, weight, candidate K, normalization 또는 분석 cohort를 변경하지 않았다.

## Sanity checks

요구된 18개 검사—temporal/target leakage, method feature purity, validation-only alpha/beta, alpha-zero identity, 동일 candidate/filter/catalog, seen 제거, parent mapping, oracle category 미사용, Last2 hash, Qwen 미실행, v3 원본 보호, paired bootstrap, qualitative 규칙—가 모두 통과했다. 기계 판독 결과는 `artifacts/sanity_checks.json`에 있다.

## 주요 산출물

- `models/bpr_validation.pt`: validation epoch 선택에 사용한 train-only BPR
- `models/bpr_final.pt`: 선택된 23 epochs로 train+validation에 재학습한 서비스/test용 BPR
- `artifacts/product_tactile_profiles.parquet`: 7,365개 parent-level Last2 profile
- `artifacts/recommendation_splits.parquet`, `evaluation_cases.parquet`: eligible official interaction과 평가 cohort
- `artifacts/user_category_profiles.parquet`, `user_tactile_profiles.parquet`: target 이전 user profile
- `artifacts/validation_weight_search.csv`, `selection.json`, `alpha_validation_curve.png`: validation-only weight 선택
- `artifacts/recommendation_results.json`, `per_user_results.csv`: aggregate 및 user-level 잠금 test 결과
- `artifacts/qualitative_examples.json`: deterministic 사례와 Top-10 score breakdown
- `artifacts/sanity_checks.json`: 18/18 자동 검증 결과
- `recommend.py`, `app.py`: 서비스 API와 Streamlit demo
