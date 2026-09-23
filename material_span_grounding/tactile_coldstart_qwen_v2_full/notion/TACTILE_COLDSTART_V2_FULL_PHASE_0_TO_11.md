# Tactile Cold-Start v2 Full-Pool — Phase 0~11 실험 과정과 결과

## 한눈에 보는 결론

이번 v2는 v1의 500개 ASIN 상한을 제거하고 조건을 만족한 **전체 8,498개 ASIN**에서 시작했다. 예측 단위는 ASIN, 분할 단위는 parent product family(7,365개)다. 기존 v1에 나타난 family는 train에만 넣었고, development와 locked test는 이전에 보지 않은 family로만 구성했다.

70,943개 선택 리뷰 전체를 키워드로 훑어 26,126개 고재현율 후보를 보존했다. 그중 8,641개 reviewer-first 대표 구절을 Qwen이 문맥 검증했고, 5,710개를 촉감 축으로 안전하게 매핑했으며 2,931개는 거절했다.

촉감 후보가 하나라도 나온 ASIN은 8,064개이며, 나머지 434개도 데이터셋과 이미지 feature에는 그대로 포함했다. 후보가 없다는 사실은 중립 촉감이 아니라 review-unobserved로 처리한다.

중요: 사용자 요청으로 사람 검증을 이번 실행에서 건너뛰었다. 따라서 아래 숫자는 사람 ground truth가 아니라 **Qwen pseudo-label 기반 feasibility 결과**이며 human validation 상태는 `pending`이다.

## 데이터 선정과 family 분할

포함 조건은 source train split, 로컬 이미지 존재, 리뷰 길이 40~2,000자, 서로 다른 reviewer 5명 이상이다. 상품 수 상한은 없다. 각 ASIN에서는 reviewer당 리뷰 하나만 남기고 최대 10명의 리뷰를 사용했다.

- train: 6,300 ASIN / 5,295 family
- development: 1,077 ASIN / 1,035 family
- locked test: 1,121 ASIN / 1,035 family
- 기존 v1 family 중 train 강제 배치: 471
- parent family 중복: 0; test 리뷰는 모델 선택·축 선택·threshold 보정에 사용하지 않음

## Phase 2 — 후보 구절과 Qwen 검증

단순 키워드 일치는 최종 라벨이 아니다. 모든 리뷰에서 soft/rough/stretch/thin/stiff/warm/spongy 계열 표현이 있는 문장을 먼저 넓게 찾은 뒤, 각 ASIN에서 한 축을 결정론적으로 선택했다. reviewer 일치도 측정을 위해 축마다 최대 100개 상품에 한해 같은 축을 말한 두 번째 독립 reviewer도 보존했다. Qwen은 로컬 문맥을 보고 소재 촉감이 아닌 fit·size·durability·날씨 선호·비유적 표현을 거절했다.

Qwen 출력은 `[mappable, axis, direction, intensity, scope, confidence]`의 6개 정수 코드로 제한했다. 숫자 target은 Qwen이 직접 만들지 않고, symbolic label을 코드에서 결정론적으로 변환했다.

엄격한 출력 검증 과정에서 축/방향 위치가 코드만으로 명백히 뒤바뀐 21건은 결정론적으로 교정했다. 유효 축을 복원할 수 없었던 3건은 축을 임의 생성하지 않고 confidence=0의 unmappable로 보수적으로 거절했으며, 두 경우 모두 원시 Qwen 응답과 정규화 사유를 보존했다.

## Phase 3 — 촉감 축은 어떻게 구성됐나

각 축은 서로 반대되는 두 pole을 가진 bipolar 축이다. v1 임시 AI audit에서 strong/moderate 구분이 불안정했기 때문에 v2 주 타깃은 강도를 곱하지 않는 방향 중심 `-1 / 0 / +1`이다. 원 intensity는 삭제하지 않고 진단용으로 보존했다. 축 선택에는 오직 train split만 사용했다.

| 축 | 구성 | 의미 | train mapped span | 상품 | 두 reviewer 이상 | 미관측률 | 선택 |
|---|---|---|---:|---:|---:|---:|:---:|
| softness | soft ↔ firm | Perceived yielding softness versus resistant firmness of the textile or garment material. | 488 | 476 | 12 | 92.4% | ACTIVE |
| surface_texture | smooth ↔ rough | Smooth versus rough, scratchy, or coarse character of the textile surface. | 160 | 152 | 8 | 97.6% | ACTIVE |
| elasticity | non_elastic ↔ elastic | Resistance to stretch versus ability to stretch and recover as a material property. | 2,001 | 1,928 | 73 | 69.4% | ACTIVE |
| thickness | thin ↔ thick | Low versus high perceived textile thickness, including explicit thinness or thickness. | 1,167 | 1,139 | 28 | 81.9% | ACTIVE |
| flexibility | flexible ↔ stiff | Ease of bending and draping versus stiffness or rigidity of the textile. | 98 | 91 | 7 | 98.6% | ACTIVE |
| warmth | warm ↔ cool | Perceived thermal warmth versus coolness attributable to the textile. | 317 | 293 | 24 | 95.3% | ACTIVE |
| sponginess | spongy ↔ crisp | Compressible spongy hand versus crisp, sharply structured textile hand. | 2 | 2 | 0 | 100.0% | INACTIVE |

최종 active axes: **softness, surface_texture, elasticity, thickness, flexibility, warmth**. 축은 span 30개, 상품 20개, 양 pole 각각 상품 5개, multi-reviewer 상품 3개, category 집중도 90% 이하, 평균 mapping confidence 0.70 이상을 모두 만족해야 active가 된다. 외부 데이터셋 지원 여부는 내부 축 선택의 필수조건으로 쓰지 않고 Phase 8에서 별도로 평가했다.

## Phase 4~5 — 사람 검증 상태와 reviewer-first target

사람 검증용 고정 표본 CSV는 만들었지만 human 필드는 비어 있다. downstream에서는 같은 reviewer가 여러 구절을 말해도 먼저 reviewer 수준에서 평균낸 뒤 상품 수준으로 평균했다. reviewer 수가 많은 사람이 과도한 가중치를 갖지 않으며, 축 언급이 없는 상품은 0점이 아니라 mask=0인 `REVIEW_UNOBSERVED`다.

- 관측 product-axis pair: 5,482
- 미관측 product-axis pair: 45,506
- reviewer-axis record: 5,680

## Phase 6~7 — 이미지에서 촉감 방향 예측

모든 이미지에서 frozen FashionCLIP과 DINO 특징을 뽑았다. category-only, 선형 회귀, Ridge, image+category, ordinal, pairwise, tiny MLP를 비교했고, hyperparameter와 최종 방법 선택은 development만 사용했다. 아래 값은 locked family test의 축별 Spearman이다.

| 방법 | softness | surface_texture | elasticity | thickness | flexibility | warmth |
|---|---:|---:|---:|---:|---:|---:|
| category_only | 0.071 | 0.396 | 0.328 | 0.086 | -0.297 | -0.009 |
| fashionclip_linear | 0.024 | -0.040 | 0.340 | 0.251 | 0.018 | -0.161 |
| fashionclip_ridge | 0.071 | -0.066 | 0.356 | 0.322 | 0.092 | -0.110 |
| image_category_ridge | 0.079 | -0.093 | 0.364 | 0.318 | 0.129 | -0.087 |
| dino_ridge | -0.058 | -0.423 | 0.357 | 0.249 | 0.314 | -0.069 |
| ordinal | 0.089 | -0.026 | 0.260 | 0.264 | 0.092 | 0.018 |
| pairwise | 0.046 | -0.053 | 0.192 | 0.241 | 0.092 | 0.018 |
| tiny_mlp | 0.019 | 0.040 | 0.327 | 0.303 | 0.351 | 0.060 |

Spearman이 category-only보다 높아야 실제 이미지 신호가 category shortcut을 넘어섰다고 해석할 수 있다. same-category pairwise 지표도 함께 기록했으며, 낮거나 음수인 결과는 숨기지 않고 시각적 촉감 추론의 한계로 해석한다.

선택 모델과 무관한 보조 open 384차원 baseline에서는 비유한 cosine 값 2개가 발생해 성능 숫자로 치환하지 않고 JSON null과 원래 경로로 기록했다. 위 구조화 모델 표와 development 기반 모델 선택에는 사용되지 않았다.

## Phase 8 — 외부 MLLM-Fabric 전이

MLLM-Fabric 220개 RGB 이미지는 Amazon과 점수 체계를 합치지 않고 별도 외부 평가로 사용했다. 110개는 recoverability 보정, 나머지 110개는 외부 test다.
Leeds 자료는 이번 실행에서 `unavailable_for_execution`였다. 공개 원문과 별개로 원시 이미지+평점 배포본 및 재배포 라이선스를 확인하지 못해 수치를 만들지 않았다.

| 축 | 상태 | 외부 Spearman | pairwise accuracy | recoverability |
|---|---|---:|---:|---:|
| softness | complete | 0.002 | 0.501 | 0.095 |
| surface_texture | complete | 0.318 | 0.654 | 0.339 |
| elasticity | complete | 0.119 | 0.581 | 0.083 |
| thickness | complete | 0.190 | 0.603 | 0.283 |
| flexibility | not_compatible_or_model_unavailable | — | — | — |
| warmth | not_compatible_or_model_unavailable | — | — | — |

## Phase 9 — 틀릴 것 같으면 abstain

20개 bootstrap Ridge ensemble의 상품별 불안정성(instance confidence)과 외부 축별 recoverability를 분리했다. development에서 threshold/calibrator를 정하고 locked test에서 risk-coverage를 측정했다.

| 방법 | AURC↓ | nominal 80%의 실제 coverage | 해당 risk(MAE)↓ |
|---|---:|---:|---:|
| confidence_only | 0.601 | 0.776 | 0.659 |
| recoverability_only | 0.763 | 0.925 | 0.672 |
| product | 0.717 | 0.806 | 0.670 |
| learned_calibrator | 0.621 | 0.773 | 0.648 |

## Phase 10 — review-cold-start retrieval

locked test에서 같은 category 안에 최소 30개 후보가 있고 review target support가 있는 경우만 query를 만들었다. 생성 query는 10개이며, relevance는 test의 숨겨진 review pseudo-target에서만 계산했다.

| 방법 | NDCG@10 | 95% bootstrap CI |
|---|---:|---:|
| category_only | 0.504 | [0.285, 0.742] |
| confidence_selective_u0 | 0.616 | [0.455, 0.776] |
| fashionclip_taxonomy_zero_shot | 0.535 | [0.404, 0.680] |
| product_selective_u0 | 0.627 | [0.484, 0.759] |
| proposed_calibrator_u0 | 0.642 | [0.467, 0.805] |
| proposed_calibrator_u1 | 0.635 | [0.439, 0.819] |
| proposed_unknown_coverage_u2 | 0.635 | [0.451, 0.815] |
| random | 0.567 | [0.398, 0.737] |
| recoverability_selective_u0 | 0.656 | [0.492, 0.791] |
| structured_no_abstention | 0.656 | [0.498, 0.800] |

## 우리가 주목해야 할 점

1. **500개 샘플 결론이 아니라 전체 적격 풀 결론이다.** 상품 수가 17배로 늘었고 family 단위 locked test를 새로 만들었다.
2. **라벨이 없는 축을 중립으로 만들지 않았다.** 미언급은 REVIEW_UNOBSERVED로 mask 처리했기 때문에 0점 과잉이 없다.
3. **강도보다 방향이 더 신뢰할 만하다.** v1 audit에서 드러난 intensity 불안정을 반영해 주 타깃을 방향 중심으로 바꿨다.
4. **category shortcut을 반드시 확인해야 한다.** 이미지 모델이 category-only를 못 이기면 촉감이 아니라 상품 종류를 맞힌 것일 수 있다.
5. **abstention은 새 라벨이 아니다.** VISUAL_ABSTAIN은 모델이 답을 보류하는 추론 상태이며 REVIEW_UNOBSERVED/neutral과 다르다.
6. **사람 검증 전까지 결론은 잠정적이다.** 데이터 규모와 누수 방지는 개선됐지만 pseudo-label의 의미 정확도는 human audit 뒤에야 확정된다.

## Phase별 실행 요약

- Phase 0: 전체 census, ASIN/master/review corpus, family-safe split 및 locked test 생성
- Phase 1: 7개 축 taxonomy와 direction-only primary coding 동결
- Phase 2: lexical high-recall 후보 → Qwen 보수적 문맥 grounding
- Phase 3: train-only coverage/pole/reviewer/category/confidence gate로 active axis 선택
- Phase 4: human audit는 실행하지 않고 pending CSV와 한계 기록
- Phase 5: reviewer-first target/distribution/support/agreement/mask 생성
- Phase 6: 전체 이미지 FashionCLIP/DINO frozen embedding 추출
- Phase 7: category/linear/Ridge/ordinal/pairwise/MLP 및 robustness 비교
- Phase 8: MLLM-Fabric 외부 전이와 property recoverability 계산
- Phase 9: development-calibrated risk-coverage와 abstention 평가
- Phase 10: same-category locked-test tactile retrieval 평가
- Phase 11: 테스트, bootstrap CI, manifest, 본 Notion-ready 문서 통합

## 한계와 다음 필수 작업

- 사람 audit를 건너뛰었으므로 Qwen axis confusion, polarity, scope 정확도는 미확정이다.
- lexical candidate miner는 효율적인 high-recall front end지만, 키워드가 전혀 없는 우회적 촉감 표현을 놓칠 수 있다.
- 한 ASIN에서 대표 축을 선택하는 scaling 정책 때문에 모든 축이 모든 상품에서 관측되는 구조가 아니다.
- 외부 MLLM-Fabric은 220개로 작고 softness/texture/elasticity/thickness만 직접 호환된다.
- Leeds 외부 검증은 실행 가능한 원시 이미지+평점 배포본과 라이선스를 확인한 뒤 추가해야 한다.
- 최종 배포 전에는 pending audit CSV를 사람이 채우고, 오류가 큰 축은 taxonomy/prompt를 재동결해야 한다.
