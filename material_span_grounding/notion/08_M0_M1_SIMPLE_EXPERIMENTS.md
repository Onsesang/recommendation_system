# 소재 리뷰 공간 M0/M1 단순 실험 최종 보고서

> 기준일: 2026-08-10  
> 범위: GNN 이전의 단순 baseline 검증  
> 데이터 원칙: 공식 train split만 사용, protected test 미사용

## 1. 결론

이번 단계에서 **리뷰 임베딩 회귀 M1은 폐기할 방법은 아니지만, 논문의 최종 기여로 확정할
근거도 아직 부족하다.**

- 기존 sparse pilot 438상품에서는 M1이 원본 동결 이미지 M0보다 nDCG@5와 같은
  카테고리 소재 검색에서 유의한 개선을 보였다.
- 새로 구성한 100상품×5사용자 표본에서는 소재 target이 생긴 상품이 89개뿐이었고,
  이 데이터만 학습했을 때 M1의 개선은 사라졌다.
- 기존 sparse 상품 436개를 학습에만 보조로 추가하면 M1의 모든 핵심 점추정치가 다시
  양수로 바뀌었지만 95% bootstrap 신뢰구간은 여전히 0을 포함했다.
- 따라서 현재 병목은 GNN의 부재보다 **학습 가능한 상품 수와 신뢰도 높은 다중 사용자
  target 수**다.

권장 의사결정은 다음과 같다.

> GNN은 계속 보류한다. 먼저 현재 protocol을 고정하고 최소 500개 이상의 product-dense
> 상품으로 M0/M1을 다시 평가한다. M1이 same-category 지표에서 반복적으로 M0를 이길
> 때만 관계 증류·순위 학습·GNN으로 확장한다.

---

## 2. 사람 검수 품질 gate

RECALL V2 100-span 검수와 47개 full-review 검사가 완료됐다.

| 항목 | 결과 |
|---|---:|
| 사람 판정 | 100 / 100 |
| Human accepted / rejected | 76 / 24 |
| Qwen accepted precision | 93.75% |
| 전체 decision accuracy | 94.0% |
| Qwen rejected false-negative rate | 5.0% |
| Full Review Checked | 47 / 47 |
| 사람이 추가한 missing span | 0 |
| 관측된 within-review span recall | 100% |

주의할 점:

- 100% recall은 검수 대상으로 선택된 47개 리뷰 안에서만 계산한 값이다.
- 추출 결과가 전혀 없는 리뷰를 포함한 corpus-wide recall은 아니다.
- dense 500리뷰의 pseudo-label precision 93.75%는 같은 prompt에 대한 **전이 추정치**이며,
  dense 표본 자체를 사람이 다시 검수한 값은 아니다.

---

## 3. 데이터 밀도 분석

전체 Amazon Fashion review를 공식 train split과 로컬 이미지 존재 조건으로 스캔했다.

| 항목 | 결과 |
|---|---:|
| 전체 스캔 리뷰 | 2,500,939 |
| train·이미지 조건 충족 리뷰 | 152,878 |
| train 상품 | 14,907 |
| 로컬 이미지가 있는 train 상품 | 14,906 |
| 유효 사용자가 5명 이상인 상품 | 8,498 |
| 유효 사용자가 10명 이상인 상품 | 4,359 |
| 유효 사용자가 20명 이상인 상품 | 1,743 |

확장 가능성을 확인하기 위해 두 표본을 만들었다.

| 표본 | 상품 | 리뷰 | 사용자 제어 |
|---|---:|---:|---|
| 확장용 corpus | 500 | 4,158 | 상품 내 사용자당 리뷰 1개 |
| 이번 단순 실험 | 100 | 500 | 상품마다 서로 다른 사용자 5명 |

이번 100상품 표본의 선택 파일 SHA-256은
`01fab7cb86544594e79912a717fb6a36d3fda64961f4435354a8d0d2816d192d`다.

---

## 4. dense 표본의 Qwen 수집 결과

500개 full review에 surface/use와 behavior/care의 두 recall lens를 적용하고, 모든 quote를
코드로 원문 exact substring 검사한 뒤 Qwen semantic verification을 수행했다.

| 단계 | 결과 |
|---|---:|
| 입력 리뷰 | 500 |
| exact span이 하나 이상인 리뷰 | 212 (42.4%) |
| 추출 단계에서 근거가 있는 상품 | 91 / 100 |
| union exact span | 375 |
| 원문 불일치로 자동 제외한 후보 | 9 |
| semantic schema 성공 | 375 / 375 |
| Qwen accepted / rejected | 340 / 35 |
| 최종 target 상품 | 89 / 100 |

최종 89상품의 소재 근거 사용자 수는 다음과 같다.

| 검증된 소재 근거 사용자 수 | 상품 수 |
|---:|---:|
| 1명 | 21 |
| 2명 | 34 |
| 3명 | 20 |
| 4명 | 12 |
| 5명 | 2 |

원본에는 상품마다 5명의 리뷰가 있지만 모든 사용자가 소재를 언급하지는 않는다. 따라서
89상품 중 다중 사용자 소재 target은 68상품이고, 21상품은 여전히 단일 사용자 target이다.

---

## 5. 상품 target 구성

고정 소재 class는 사용하지 않았다. 채택된 자유 텍스트 claim을 BGE-small로 임베딩하고
다음 순서로 상품 target을 만들었다.

```text
Qwen accepted claim
→ 동일 사용자 안에서 normalized exact claim 중복 제거
→ 사용자별 claim 평균 및 L2 정규화
→ 사용자 벡터 동일 가중 평균
→ 상품 벡터 L2 정규화
```

이 방식은 span 개수가 많은 사용자 한 명이 상품 target을 지배하지 않게 한다. BGE 문장
임베딩의 공통 평균 방향 때문에 서로 무관한 상품도 높은 cosine을 보이는 현상이 있어,
각 fold의 development 데이터에서만 평균 방향을 추정해 제거했다. sparse pilot에서는
상품 간 평균 cosine이 0.7848에서 0.0014로 내려갔다.

상반된 claim은 삭제하지 않았다. `soft`와 `scratchy`, `stretchy`와 `not stretchy`처럼 서로
다른 사용자 경험은 향후 polarity-aware set target이나 확률적 target에서 분리할 대상이다.

---

## 6. 비교 방법

| 방법 | 정의 |
|---|---|
| Random | 후보 무작위 순위 |
| Category only | 같은 카테고리 후보 안에서 무작위 순위 |
| M0 | 원본 동결 Qwen 이미지 feature를 L2 정규화해 cosine 검색 |
| M0 standardized diagnostic | development 통계로 이미지 feature를 표준화한 보조 진단 |
| M1 | StandardScaler + multi-output Ridge로 이미지→리뷰 상품 벡터 회귀 |

중간 점검에서 M0에도 StandardScaler가 적용돼 있던 문제를 발견했다. 이는 “기성 임베딩
그대로”라는 baseline 정의와 맞지 않으므로 최종 M0는 **원본 feature + L2 normalization만**
사용하도록 수정했다. 표준화 M0는 결론에 쓰지 않고 보조 결과로만 보존했다.

평가는 상품/parent group 단위로 분리했다. sparse pilot은 train 내부 70/15/15 split,
dense follow-up은 5-fold outer holdout과 fold 내부 validation으로 Ridge alpha를 선택했다.
protected test는 사용하지 않았다.

---

## 7. 실험 결과

### 7.1 Sparse pilot: 438상품

| 방법 | Material cosine@5 | nDCG@5 | Same-category material cosine@5 |
|---|---:|---:|---:|
| Category only | 0.0183 | 0.3974 | 0.0183 |
| M0 raw frozen | 0.0414 | 0.4136 | 0.0362 |
| M1 Ridge | **0.0919** | **0.4613** | **0.0946** |

| M1 − M0 | 차이 | Bootstrap 95% CI | 해석 |
|---|---:|---:|---|
| Material cosine@5 | +0.0505 | -0.0016 ~ +0.1079 | 경계, 확정 아님 |
| nDCG@5 | +0.0477 | +0.00002 ~ +0.0987 | 유의한 양의 차이 |
| Same-category cosine@5 | +0.0584 | +0.0065 ~ +0.1110 | 유의한 양의 차이 |

좋은 초기 신호지만 438상품 중 430상품이 소재 근거 사용자 1명뿐이라는 한계가 있다.

### 7.2 Dense-only follow-up: 89상품, 5-fold

| 방법 | Material cosine@5 | nDCG@5 | Same-category material cosine@5 |
|---|---:|---:|---:|
| Category only | 0.0322 | 0.4998 | 0.0396 |
| M0 raw frozen | **0.0441** | **0.5290** | **0.0547** |
| M1 Ridge | 0.0479 | 0.5241 | 0.0498 |

| M1 − M0 | 차이 | Bootstrap 95% CI |
|---|---:|---:|
| Material cosine@5 | +0.0038 | -0.0312 ~ +0.0408 |
| nDCG@5 | -0.0049 | -0.0413 ~ +0.0314 |
| Same-category cosine@5 | -0.0049 | -0.0272 ~ +0.0166 |

M1이 M0를 이겼다고 볼 수 없다. fold별 최적 alpha가 0.1부터 10,000까지 크게 흔들렸고,
fold당 학습 dense 상품이 50~70개라 1,152차원 이미지 입력을 안정적으로 회귀하기에는
작았다.

### 7.3 Sparse 학습 보조 + dense-only 평가

기존 human-corrected sparse 상품 436개를 학습에만 추가했다. 각 outer test group과 inner
validation group에 속하는 보조 상품은 해당 학습에서 제외했다. 평가 질의와 후보는 계속
dense 89상품만 사용했고, 텍스트 중심도 dense development 상품으로 고정해 M0 결과가
7.2와 정확히 같도록 했다.

| 방법 | Material cosine@5 | nDCG@5 | Same-category material cosine@5 |
|---|---:|---:|---:|
| M0 raw frozen | 0.0441 | 0.5290 | 0.0547 |
| M1 Ridge + sparse train | **0.0835** | **0.5482** | **0.0730** |

| M1 − M0 | 차이 | Bootstrap 95% CI | P(delta > 0) |
|---|---:|---:|---:|
| Material cosine@5 | +0.0394 | -0.0065 ~ +0.0855 | 0.954 |
| nDCG@5 | +0.0192 | -0.0322 ~ +0.0702 | 0.761 |
| Same-category cosine@5 | +0.0183 | -0.0070 ~ +0.0434 | 0.924 |

학습 상품 수를 늘리면 방향은 회복되지만 세 지표 모두 95% CI가 0을 포함한다. 이는 M1의
가능성과 동시에 더 큰 product-dense 평가 세트가 필요함을 보여준다.

---

## 8. 현재 해석

### 확인된 것

- open-vocabulary 소재 span을 높은 exact-quote 안정성으로 수집할 수 있다.
- 사람 100-span audit에서 Qwen accepted precision은 93.75%였다.
- 사용자별 1표 target과 group-safe 평가를 코드로 재현할 수 있다.
- sparse 파일럿에서는 M1이 M0보다 같은 카테고리 소재 검색을 개선했다.
- 더 많은 학습 상품을 주면 dense 평가에서도 M1의 점추정치가 좋아졌다.

### 아직 확인되지 않은 것

- dense 다중 사용자 상품에서 M1이 M0를 통계적으로 안정되게 이긴다는 주장
- 향상이 실제 미세 소재 단서 때문이고 카테고리·실루엣 shortcut이 아니라는 최종 증명
- 평균 target이 상충 의견과 불확실성을 충분히 보존한다는 주장
- GNN이 단순 평균이나 Ridge보다 낫다는 주장

### 결과가 흔들린 핵심 원인

1. dense target 상품이 89개라 회귀 차원에 비해 작다.
2. 89개 중 21개는 검증 후에도 소재 근거 사용자가 1명뿐이다.
3. dense label은 사람 검수 prompt의 전이 추정치를 사용한 pseudo-label이다.
4. 자유 텍스트 평균은 상충·다봉 분포를 하나의 벡터로 압축한다.
5. 카테고리별 표본 수가 작아 fold 구성에 따라 난도가 달라진다.

---

## 9. 다음 권장 실험

### 우선순위 1 — 현재 protocol 그대로 규모 확대

이미 준비한 500상품·4,158리뷰 표본을 사용한다. 최소 조건은 다음과 같다.

- 상품당 서로 다른 사용자 5명 이상
- 사용자당 리뷰 1개
- 500상품 전부 이미지 존재
- 동일 exact-quote 및 semantic verification prompt 고정
- 사람은 전체 span이 아니라 층화 표본을 검수해 precision drift만 확인
- dense gold evaluation 상품을 별도로 150~300개 확보

### 우선순위 2 — M1을 먼저 다시 판단

500상품 실험에서도 M0 raw frozen, category-only, M1 Ridge를 그대로 유지한다. 사전에
정한 primary metric은 `same-category material cosine@5`, 보조 metric은 nDCG@5와
material cosine@5로 둔다. 세 seed 또는 5-fold에서 일관된 양의 차이가 나와야 다음 모델로
간다.

### 우선순위 3 — 그다음 확장 순서

```text
M1 리뷰 임베딩 회귀
→ M2 관계 구조 증류
→ M5 순위 학습
→ M1+M2 결합
→ 확률적 target
→ 충분한 graph 밀도가 생긴 뒤 GNN
```

GNN은 review node가 있다는 이유만으로 바로 넣지 않는다. 동일 상품의 여러 사용자,
semantic 유사·반대 관계, 사용자 신뢰도 edge가 충분하고 단순 set/mean baseline을 먼저
이겼을 때 비교한다.

---

## 10. 추천 시스템 반영 방식

현재 단계에서는 M1을 production 기본값으로 확정하지 않는다.

```text
질의 이미지
→ M0와 M1을 offline A/B retrieval
→ 같은 카테고리 안에서 소재 유사 상품 검색
→ 검색 상품의 accepted 실제 review claim만 evidence로 사용
→ 사용자 수·합의도와 함께 설명 생성
```

- 세탁 후 수축·피부 자극처럼 이미지에서 직접 보이지 않는 속성은 “검색된 구매자 리뷰”
  근거임을 명시한다.
- 근거 사용자 1명은 `한 구매자는`, 여러 사용자가 합의하면 `구매자들은`으로 표현한다.
- 반대 의견은 평균으로 숨기지 말고 `의견이 엇갈립니다`로 표시한다.
- `short`, `wide`, `runs small` 같은 핏 정보는 현재 소재 공간에서 제외하고 별도 fit
  pipeline과 vector로 관리한다.
- 생성 모델은 검색된 claim 밖의 소재 속성을 새로 만들 수 없게 한다.

---

## 11. 재현 명령

```bash
# 전체 train 리뷰 밀도 스캔과 확장용 500상품 표본
conda run -n texture python run.py density \
  --min-users 5 --max-reviews-per-product 10 --max-products 500 \
  --output-root data/dense

# 이번 100상품×5사용자 표본
conda run -n texture python run.py density \
  --min-users 5 --max-reviews-per-product 5 --max-products 100 \
  --output-root data/dense/simple_100x5

# recall extraction과 semantic verification
conda run -n texture python run.py recall-extract \
  --input data/dense/simple_100x5/reviews_product_dense.jsonl \
  --output-root data/dense/simple_100x5/v2 --batch-size 6
conda run -n texture python run.py recall-verify-prepare \
  --output-root data/dense/simple_100x5/v2
conda run -n texture python run.py recall-verify \
  --output-root data/dense/simple_100x5/v2 --batch-size 8

# M0/M1 실험
conda run -n texture python run.py simple-m0-m1
conda run -n texture python run.py dense-m0-m1 \
  --root data/dense/simple_100x5/v2
conda run -n texture python run.py dense-m0-m1 \
  --root data/dense/simple_100x5/v2 --augment-sparse
```

---

## 12. 주요 산출물

| 경로 | 내용 |
|---|---|
| `data/dense/density_manifest.json` | 전체 밀도 스캔과 500상품 표본 manifest |
| `data/dense/simple_100x5/density_manifest.json` | 이번 100×5 표본 manifest |
| `data/dense/simple_100x5/v2/span_extractions.jsonl` | 500리뷰 recall 추출 |
| `data/dense/simple_100x5/v2/semantic_verifications.jsonl` | 375 span 검증 결과 |
| `experiments/06_simple_m0_m1/results/metrics.json` | sparse M0/M1 최종 결과 |
| `experiments/07_dense_m0_m1/results/metrics.json` | dense-only 5-fold 결과 |
| `experiments/08_dense_m0_m1_augmented/results/metrics.json` | sparse 학습 보조 결과 |
| `artifacts/simple_m0_m1/m1_ridge.joblib` | sparse Ridge artifact |
| `artifacts/dense_m0_m1/` | dense-only fold artifacts |
| `artifacts/dense_m0_m1_augmented/` | 보조 학습 fold artifacts |

## 최종 판정

**진행(조건부):** 리뷰 임베딩 회귀 M1을 다음 규모 실험의 주 baseline으로 유지한다. 다만
현재 수치만으로 “학습 방식이 기성 임베딩보다 우수하다”고 최종 주장하지 않는다. 다음
gate는 500상품 product-dense 평가에서 same-category primary metric의 신뢰구간이 0보다
크고, fold별 방향이 안정적인지다.
