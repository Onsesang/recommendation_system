# Strong Recommender + Tactile 전체 실험 결과

생성 시각: 2026-09-08 12:28 KST  
실험 경로: `/home/user/onsesang/material_span_grounding/experiments/16_strong_recommender_tactile`  
프로토콜 seed: `20260904`

## 1. 연구 질문

- RQ1: Amazon Reviews'23 Amazon_Fashion 전체 catalog에서 BPR보다 강한 추천 backbone이 candidate retrieval과 Top-K를 개선하는가?
- RQ2: validation으로 고정한 후보군에 Last2 촉각 벡터를 더하면 일반 next-item 추천이 개선되는가?
- RQ3: 일반 추천과 분리된 명시적 tactile query에서 Last2가 촉각 관련 상품을 더 잘 정렬하는가?

## 2. 기존 BPR 실험이 실패한 이유

기존 실험은 추천 catalog를 촉각 라벨 교집합으로 먼저 줄였다. 보존된 artifact 기준 catalog는 7,365/825,869 (0.89%), test에서 history가 남은 사용자는 3,283명이었고, candidate Recall@300은 0.177277였다. Validation은 alpha=0을 선택해 proposed와 category-aware가 같았다. 이 결과는 촉각 표현의 무용성을 입증하지 않으며 retrieval·coverage 병목을 함께 반영한다. 기존 제한 실험과 이번 all-user metric은 평가 모집단이 달라 숫자를 직접 우열 비교하지 않는다.

## 3. 이번 재설계 핵심

추천 학습과 후보 생성은 825,869개 전체 catalog에서 수행했다. 이미지가 없는 상품도 제거하지 않았고, Last2는 별도의 image-available item feature로만 결합했다. backbone, K, profile 방식, class 수, alpha는 validation에서 고정한 뒤 test를 한 번만 열었다.

## 4. Amazon Reviews'23 Amazon_Fashion

- Raw: users 2,035,490, items 825,869, reviews 2,500,939
- Processed official split: users 2,035,490, parent items 825,869, interactions 2,474,375
- Train/validation/test events: 157,490 / 281,395 / 2,035,490
- Interaction은 review/rating event이며 click 또는 purchase로 단정하지 않는다. verified purchase는 raw flag가 참일 때만 근거가 있다.

## 5. User history distribution

| Evaluation | zero | >=1 | >=3 | >=5 | median | mean |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Validation | 204,640 | 76,755 | 14,731 | 5,323 | 0.000000 | 0.559676 |
| Test | 1,754,095 | 281,395 | 29,991 | 8,347 | 0.000000 | 0.215616 |

history가 없는 사용자는 모든 모델에서 train popularity로 fallback했다. Validation의 72.72%, test의 86.18%가 이 공통 fallback이므로 all-user metric은 personalized 모델 차이를 크게 희석한다. 낮은 절대값의 원인을 0-history 하나에만 귀속하지 않는다.

## 6. Item/parent mapping

ASIN→parent_ASIN은 raw review의 명시적 필드를 사용했다. v3 tactile products 8,003개 중 8,003개를 매핑했고, parent는 6,938개다. fuzzy matching은 사용하지 않았다.

## 7. Strong recommendation backbones

동일 catalog/split/seen filtering으로 Popularity, BPR-MF, LightGCN, SASRec, eSASRec을 비교했다. eSASRec은 공식 구현의 LiGR+SwiGLU 구조를 vendoring하고 NumPy 2 환경 불일치 때문에 local data/evaluation adapter와 64-negative sampled softmax를 사용했다. 이를 single SOTA가 아닌 recent strong reproducible recommender로 표현한다.

## 8. Backbone validation

`artifacts/backbone_validation_results.csv`가 두 learning rate와 best epoch의 근거다. Primary validation NDCG@10으로 `sasrec`을 선택했다.

## 9. Candidate recall

| Model | Recall@100 | @300 | @500 | @1000 | @3000 |
| --- | ---: | ---: | ---: | ---: | ---: |
| popularity | 0.029997 | 0.047047 | 0.055299 | 0.071197 | 0.112184 |
| bpr | 0.029474 | 0.046183 | 0.054299 | 0.069827 | 0.109903 |
| lightgcn | 0.029632 | 0.046442 | 0.054585 | 0.070179 | 0.110401 |
| sasrec | 0.029547 | 0.046158 | 0.054270 | 0.069422 | 0.108607 |
| esasrec | 0.029609 | 0.045923 | 0.054134 | 0.069881 | 0.109744 |
| smore | 0.029351 | 0.046000 | 0.054071 | 0.069552 | 0.109604 |

Validation 규칙으로 K=`3000`를 고정했다. Recall≥0.80 조건 충족 여부: `False`. 미충족이면 K=3000을 사용하되 retrieval bottleneck이 해소됐다고 주장하지 않는다.

## 10. Selected backbone

선택 모델: `sasrec`. Tie-break는 NDCG@10 → HR@10 → MRR@10 → 사전 정의 모델 순서다. 효율과 정확도는 validation artifact에 함께 보존했다.

## 11. Generic multimodal baseline

이 결과는 공식 SMORE reproduction이 아니라 **SMORE-derived scalable adaptation**이다. Upstream commit `c745bb9`의 forward/spectrum-fusion과 BPR/InfoNCE objective form을 사용했지만, full-catalog 실행을 위해 fixed-seed FAISS IVF approximate kNN(`nlist=7270`, `nprobe=32`, index-training sample 150,000), self-edge 제거, negative cosine clamp, reverse-edge union과 재정규화를 적용했다. InfoNCE는 매 epoch shuffled interaction의 첫 1,024개로 제한했고 local optimizer·negative sampling·validation loop를 사용했다. Exact-kNN neighbor recall이나 adapter ablation은 측정하지 않아 architecture 효과와 graph approximation error를 분리할 수 없다.

입력 512D feature extractor는 pinned FashionCLIP snapshot으로 고정했지만 SMORE 내부 modality embedding table은 `freeze=False`로 학습된다. Dedicated Last2 probability 또는 tactile pseudo-label을 generic baseline 입력에 넣지는 않았으나, 이미지와 metadata text 자체가 tactile cue를 암묵적으로 포함할 수 있다. 상태: `complete_no_post_test_tuning`; generic feature report: `complete`.

## 12. Amazon 전체 tactile inference

공식 `fashionclip_last2.pt` SHA-256 `073b542a9d6bd4450aa1f48596c756cc0812b1b5d914945e8f94f7c3fda1934a`를 inference-only로 사용했다. Last2 재학습, Qwen 재실행, threshold 재튜닝, taxonomy 변경은 없었다. 출력은 binary threshold가 아닌 14D continuous probability다.

## 13. Tactile coverage

| Stage | Items |
| --- | ---: |
| Recommendation catalog | 825,869 |
| Metadata available | 825,869 |
| Main image URL available | 825,868 |
| Image downloaded or cache-verified | 825,840 |
| Last2 inference available | 825,840 |

Coverage=100.00%, 기존 8,498개 대비 97.18배다. 실패/미제공 item은 제거하지 않고 tactile adjustment를 neutral로 유지했다.

## 14. User tactile profile

Category-local historical mean을 사용했다. `all_history`와 `rating>=4`, 14-class와 사전 정의 reliable 8-class를 validation ablation했다. 다른 category의 촉감 선호를 strong default로 전이하지 않는다. 역사 평균은 선호의 증거가 아니라 noisy proxy다. 여기서 category는 official taxonomy가 아니라 title keyword로 만든 미검증 11-category heuristic이며, 오분류와 `other` pooling이 어떤 history가 profile에 들어가는지 바꿀 수 있다.

## 15. Alpha search

선택: profile=`all_history`, classes=14, alpha=`0`; validation NDCG@10=0.004693. alpha=0을 포함한 0.05 간격 전체 표는 `artifacts/alpha_search.csv`에 있다. 최선의 양수 alpha 조합은 profile=`rating_ge_4`, classes=8, alpha=0.050000, NDCG@10=0.004543로 alpha=0보다 낮았다. 따라서 profile/class 선택은 alpha=0에서 성능상 식별되지 않는 tie-break 기본값이다.

## 16. General next-item result

| Method | NDCG@10 | HR@10 | MRR@10 | Note |
| --- | ---: | ---: | ---: | ---: |
| popularity | 0.005765 | 0.009468 | 0.004615 |  |
| bpr | 0.005686 | 0.009313 | 0.004559 |  |
| lightgcn | 0.005727 | 0.009374 | 0.004594 |  |
| sasrec | 0.005787 | 0.009394 | 0.004665 |  |
| esasrec | 0.005716 | 0.009405 | 0.004571 |  |
| Strong + Tactile (alpha=0) | 0.005787 | 0.009394 | 0.004665 |  |
| SMORE (generic image + text) | 0.005683 | 0.009287 | 0.004562 |  |
| SMORE + Last2 tactile | 0.005683 | 0.009287 | 0.004562 |  |

Held-out target은 다음 Amazon interaction이지 촉감 만족도 ground truth가 아니다.

## 17. Strong vs Strong + Tactile

- Strong NDCG@10: 0.005787
- Strong + tactile NDCG@10: 0.005787
- Paired Δ: 0.000000, 95% CI [0.000000, 0.000000]
- Rank movement: {'improved': 0, 'unchanged': 2035490, 'worsened': 0, 'entered_top10': 0, 'left_top10': 0}

Validation이 alpha=0을 선택했으므로 최종 Strong+tactile 구성은 Strong과 수학적으로 동일하다. 따라서 test의 delta=0 및 CI=[0,0]은 촉각 효과에 대한 독립적인 무효효과 검정이 아니라 validation 단계에서 tactile 항을 비활성화한 결과다.

## 18. Multimodal vs Multimodal + Tactile

Paired Δ NDCG@10=0.000000, 95% CI [0.000000, 0.000000].

여기서 `SMORE + Tactile`은 SMORE를 Last2와 함께 재학습한 3-modality architecture가 아니라, validation으로 고정한 SMORE 후보·점수에 동일한 Last2 post-hoc reranker를 적용한 결과다. 따라서 interaction+tactile 또는 in-model image+text+tactile ablation으로 해석하지 않는다.

## 19. Tactile-support cohort

| Profiled history items | Users | Strong NDCG@10 | Strong + Tactile | Delta |
| --- | ---: | ---: | ---: | ---: |
| 0 | 1,754,104 | 0.006056 | 0.006056 | 0.000000 |
| 1 | 204,632 | 0.004252 | 0.004252 | 0.000000 |
| 2 | 46,764 | 0.003910 | 0.003910 | 0.000000 |
| 3_to_4 | 21,644 | 0.003471 | 0.003471 | 0.000000 |
| 5_plus | 8,346 | 0.003555 | 0.003555 | 0.000000 |

support 0/1/2/3–4/5+는 상호배타적인 고정 diagnostic이며 이 cohort를 test 성능으로 선택하지 않았다. 원 명세의 겹치는 `3+` 집계는 이 표에 없으므로 후속 보완 대상으로 남긴다.

## 20. Cold-start result

| Cohort | Method | NDCG@10 | HR@10 | Support |
| --- | ---: | ---: | ---: | ---: |
| train_count_0 | Strong | 0.000000 | 0.000000 | 1324933 |
| train_count_0 | Strong + Tactile (alpha=0) | 0.000000 | 0.000000 | 1324933 |
| train_count_0 | Generic MM | 0.000000 | 0.000000 | 1324933 |
| train_count_0 | MM + Tactile | 0.000000 | 0.000000 | 1324933 |
| train_count_le_5 | Strong | 0.000000 | 0.000000 | 1838267 |
| train_count_le_5 | Strong + Tactile (alpha=0) | 0.000000 | 0.000000 | 1838267 |
| train_count_le_5 | Generic MM | 0.000003 | 0.000005 | 1838267 |
| train_count_le_5 | MM + Tactile | 0.000003 | 0.000005 | 1838267 |
| train_count_le_10 | Strong | 0.000000 | 0.000000 | 1919145 |
| train_count_le_10 | Strong + Tactile (alpha=0) | 0.000000 | 0.000000 | 1919145 |
| train_count_le_10 | Generic MM | 0.000006 | 0.000010 | 1919145 |
| train_count_le_10 | MM + Tactile | 0.000006 | 0.000010 | 1919145 |
| outside_v3_tactile_training_family | Strong | 0.001458 | 0.003608 | 1909390 |
| outside_v3_tactile_training_family | Strong + Tactile (alpha=0) | 0.001458 | 0.003608 | 1909390 |
| outside_v3_tactile_training_family | Generic MM | 0.001453 | 0.003611 | 1909390 |
| outside_v3_tactile_training_family | MM + Tactile | 0.001453 | 0.003611 | 1909390 |

Train-count cold cohort(0, <=5, <=10)는 protocol에서 test 전에 고정했다. `outside_v3_tactile_training_family`는 deterministic하게 계산했지만 locked protocol에 없었던 supplementary diagnostic이며 confirmatory cohort로 해석하지 않는다.

## 21. Explicit tactile-query result

| Method | Mean tactile NDCG@10 | Mean Precision@10 |
| --- | ---: | ---: |
| Non-tactile popularity | 0.475245 | 0.568750 |
| Generic multimodal | N/A | N/A |
| Last2 tactile | 0.765099 | 0.831250 |
| Dev-selected fusion | 0.783492 | 0.850000 |

Query benchmark에는 user ID가 없어 non-tactile baseline은 personalized strong model이 아니라 train popularity다. 기존 Experiment 14에서 같은 test를 이미 관찰했으므로 fresh confirmatory evidence가 아닌 exploratory replication이다.

| Class | Popularity NDCG@10 | Last2 NDCG@10 | Last2 Precision@10 | Known items |
| --- | ---: | ---: | ---: | ---: |
| smooth | 0.568458 | 0.889954 | 0.900000 | 154 |
| rough | 0.367921 | 0.738192 | 0.700000 | 159 |
| thin | 0.861138 | 1.000000 | 1.000000 | 667 |
| thick | 0.138862 | 0.705905 | 0.600000 | 667 |
| flexible | 0.870125 | 0.614107 | 0.600000 | 109 |
| stiff | 0.063621 | 0.757382 | 0.700000 | 117 |
| warm | 0.388981 | 0.914857 | 0.900000 | 221 |
| cool | 0.611019 | 0.936379 | 0.900000 | 216 |

Family bootstrap Last2−non-tactile Δ NDCG@10=0.295028, 95% CI [0.203259, 0.391518].

## 22. Same-category tactile result

| Class | Popularity mean NDCG@10 | Last2 mean NDCG@10 | Last2 mean Precision@10 | Category cells |
| --- | ---: | ---: | ---: | ---: |
| smooth | 0.615908 | 0.753702 | 0.700000 | 6 |
| rough | 0.496105 | 0.688651 | 0.533333 | 6 |
| thin | 0.747097 | 0.921319 | 0.900000 | 10 |
| thick | 0.284077 | 0.612857 | 0.560000 | 10 |
| flexible | 0.654747 | 0.623195 | 0.600000 | 3 |
| stiff | 0.449299 | 0.703074 | 0.566667 | 3 |
| warm | 0.655593 | 0.922888 | 0.922222 | 9 |
| cool | 0.500650 | 0.741179 | 0.500000 | 9 |

전체 category/query cell은 `artifacts/explicit_tactile_same_category.csv`에 있으며 mask=0은 negative가 아니라 평가에서 제외했다.

## 23. Qualitative examples

`artifacts/qualitative_examples.json`은 largest gain, median-nearest, largest loss를 uid tie-break로 자동 선택하며 각 방향에 실제 변화가 있을 때만 최대 3개를 남긴다. alpha=0인 strong 결과에서는 gain/loss가 빈 배열인 것이 정상이다. 성공만 cherry-pick하지 않았다.

## 24. Human audit connection

Experiment 15 manifest는 160개이고 live annotation CSV에는 completed 5개가 있으나 audit 전체는 미완료다. Cached result는 `not_started`/0로 live CSV보다 오래됐다. 작성자 provenance가 artifact에 기록되지 않아 이 5개를 quantitative human-gold 결과로 통합하지 않았고, AI 판정을 human label로 취급하지 않았다.

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

Sanity checks: `pass` (23/23); 환경: torch 2.5.1+cu121, CUDA 12.1, CUDA available=True.
