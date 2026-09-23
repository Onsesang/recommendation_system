# 촉감 선호 Feasibility — 전체 원문 조사

## 실행 범위와 해석

로컬 Amazon Fashion 원문 전체를 조사했다. 기존 v3 AXIS_PATTERNS를 그대로 재사용한 high-recall lexical screen이다. 키워드 일치는 속성 정확성이나 like/dislike의 정답이 아니다. 기존 선택 리뷰의 grounded 표본 수와 직접적인 semantic coverage 비교를 하지 않는다.

- 원문: 2,500,939 reviews / 2,035,490 users / 825,869 parent items
- 공식 leave-last-out: 2,474,375 events; 원문과 정확히 연결된 공식 event 2,474,375
- 키워드 포함 고유 event: 352,828
- 키워드 리뷰 2개 이상 사용자: 20,073; 3개 이상: 4,906

연결 키는 user_id + parent_asin + timestamp이다. 같은 키의 raw 중복은 첫 레코드를 사용한다. 선택된 원문 text/title, child ASIN, rating, verified_purchase, timestamp를 parquet에 보존했다. 전체 원문은 그대로 남아 있다.

## 기존 추천 cohort 안의 지원 표본

| 조건 | Validation | Test |
|---|---:|---:|
| 평가 사용자 | 1,110 | 3,283 |
| 미래 target에 키워드 | 312 | 901 |
| 과거·미래 모두 키워드 (전체 상품 history) | 174 | 444 |
| 과거·미래 모두 키워드 (eligible history) | 133 | 372 |
| 과거 키워드 리뷰 2개 이상 + 미래 키워드 | 75 | 120 |
| 과거·미래 동일 키워드 계열 | 104 | 237 |
| 과거·미래 키워드 + v3 test-family target | 20 | 51 |

전체 상품 history에는 이미지 촉감 카탈로그 밖 상품의 리뷰도 포함된다. 이 확장은 사용자 리뷰에서 직접 선호를 추출할 때 가능하며, 해당 상품의 이미지 벡터가 있다는 뜻은 아니다.

## Same-category 후보 가용성 진단

parent family 중복 제거 및 seen-item 제거 후 같은 category 후보 수를 계산했다. 상품 첫 리뷰가 추천 시점보다 앞서는 경우만 남겼다. 첫 리뷰는 실제 판매 시작 시점의 대용 지표이며, 상품 availability를 완벽하게 복원하지 못한다.

| 최소 후보 수 | Validation | Test |
|---|---:|---:|
| 20 | 1108 | 3275 |
| 30 | 1104 | 3270 |
| 50 | 1102 | 3254 |

Target category는 이 후보 개수 진단에만 사용했다. 실제 일반 추천의 oracle filter로 사용하지 않았다.

## GO / NO-GO

**조건부 GO: 소규모 preference annotation의 실행 가능성은 확인됐다. 대규모 개인화 추천 및 cold-start 성능 주장은 아직 보류한다.**

Test 444명은 명확한 선호가 확인된 사용자가 아니라 lexical 후보 사용자다. 같은 계열을 과거·미래에 언급한 경우는 237명이며, v3 locked-test target family의 공동 lexical 표본은 51명뿐이다. 사람 검증 후 지원 표본이 더 줄 수 있다.

Official leave-last-out은 사용자별 시간 순서이다. 다른 사용자의 미래 리뷰로 학습된 모델을 배제하는 global temporal protocol은 별도 설계가 필요하다. 기존 test를 설계 탐색에 활용했으므로 후속 확증 평가에는 새 holdout 또는 독립적인 human evaluation이 필요하다.

다음 단계: 실험 18에서 property existence / local attitude / scope / condition을 구별하는 추출의 정확성을 사람에게 검증받는다. 이 결과와 표본 수를 확인한 뒤 실험 19 이후를 진행한다.

## 재실행

```bash
cd /home/user/onsesang/material_span_grounding/experiments/17_tactile_preference_feasibility
/home/user/onsesang/miniconda3/envs/texture/bin/python run_feasibility.py
/home/user/onsesang/miniconda3/envs/texture/bin/python -m unittest -v test_feasibility.py
```

상세 통계와 입력 Arrow SHA-256은 artifacts/feasibility_results.json에 있다. 실행 산출물은 실험 17 내부에만 기록한다.
