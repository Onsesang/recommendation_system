# Codex 전달용: WSDM Tactile-Aware Recommendation 실험 설계 검토 요청

## 0. 이 문서의 목적

현재 진행 중인 Amazon Fashion 기반 촉감(tactile) 연구를 **WSDM 추천 논문**으로 연결하기 위해,
기존의 tactile attribute prediction 실험 결과를 바탕으로 **추천 시스템 실험 파이프라인을 새로 설계하려고 합니다.**

특히 아래 문제를 해결하고 싶습니다.

> Amazon의 실제 구매 이력만을 tactile-aware recommendation의 정답으로 사용하면,
> 사용자가 해당 상품을 "질감 때문에" 구매했는지 알 수 없습니다.
> 따라서 일반 추천 relevance와 tactile preference satisfaction을 분리해서 평가해야 하지 않을까?

이 아이디어가 현재 코드/데이터 구조에서 실현 가능한지 확인하고,
가능하다면 **누수 없는 실험 프로토콜, 필요한 추가 전처리, baseline, metric, ablation, 구현 순서**를 제안해 주세요.

**중요:** 우선 기존 산출물과 코드를 읽고 분석해 주세요.  
바로 코드를 수정하지 말고, 먼저 현재 구조를 파악한 뒤 구현 계획을 제시해 주세요.

---

# 1. 연구 배경

## 1.1 최종 연구 목표

온라인 패션 쇼핑에서는 색상, 디자인, 가격, 사이즈 등은 비교적 잘 제공되지만,
사용자가 실제로 만졌을 때 느끼는 다음과 같은 촉감 정보는 충분히 제공되지 않습니다.

- soft / firm
- smooth / rough
- elastic / non-elastic
- thin / thick
- flexible / stiff
- warm / cool
- spongy / crisp

현재 연구에서는 구매자 리뷰에서 실제 촉감 표현을 추출하고,
이를 상품의 tactile evidence로 구조화한 뒤,
리뷰가 부족하거나 없는 상품에서는 **상품 이미지로 tactile information을 예측**하려고 했습니다.

추천 논문에서는 이 정보를 다음처럼 사용하고 싶습니다.

```text
과거 사용자 리뷰
    ↓
사용자 tactile preference profile

상품 리뷰
    ↓
review-derived tactile profile
        또는
리뷰가 없는 상품 이미지
    ↓
image-predicted tactile profile

user tactile profile × item tactile profile
    ↓
tactile matching score
    ↓
기존 recommender와 결합
    ↓
tactile-aware recommendation
```

---

# 2. 현재 데이터와 split

기존 v2와 v3는 동일한 Amazon Fashion 적격 풀과 family-disjoint split을 사용합니다.

| 항목 | 값 |
|---|---:|
| 전체 상품 | 8,498 ASIN |
| 선택 리뷰 | 70,943 |
| lexical high-recall candidate span | 26,126 |
| train | 6,300 ASIN / 5,295 family |
| development | 1,077 ASIN / 1,035 family |
| locked test | 1,121 ASIN / 1,035 family |
| family overlap | 0 |

원칙:

- split 단위는 ASIN이 아니라 `parent product family`
- 기존 v1에 등장했던 family는 train에만 배치
- locked test는 taxonomy, threshold, hyperparameter, fine-tuning depth 선택에 사용하지 않음
- 미래 test review가 사용자 profile이나 item feature 생성에 들어가면 안 됨

---

# 3. 기존 tactile prediction 실험 요약

## 3.1 v2: bipolar axis

v2에서는 다음과 같이 양방향 axis를 예측했습니다.

```text
soft ↔ firm
smooth ↔ rough
non_elastic ↔ elastic
thin ↔ thick
flexible ↔ stiff
warm ↔ cool
spongy ↔ crisp
```

- Qwen3-VL-8B 사용
- 26,126 candidate 중 reviewer-first 대표 8,641개 span grounding
- 5,710 mapped
- 미언급 axis는 `REVIEW_UNOBSERVED`, 즉 0/neutral이 아니라 mask
- 이미지 encoder는 FashionCLIP / DINO를 freeze하고 Ridge, MLP 등으로 axis score 예측
- 주 지표는 axis별 Spearman

v2에서 상대적으로 유망했던 축은:

- thickness
- elasticity

반면:

- softness는 약함
- surface texture는 Amazon 상품 이미지에서는 불안정
- category shortcut 가능성이 큼

---

# 4. 현재 v3: atomic-class multi-label tactile prediction

## 4.1 representation 변경

v3에서는 각 pole을 독립 class로 분리했습니다.

총 14개 class:

```text
soft
firm
smooth
rough
non_elastic
elastic
thin
thick
flexible
stiff
warm
cool
spongy
crisp
```

즉 기존:

```text
soft ↔ firm
```

을 하나의 축으로 예측하는 대신,

```text
soft
firm
```

을 각각 독립 output으로 예측합니다.

한 상품/리뷰에서 여러 class가 동시에 관측될 수 있으므로
masked multi-label classification으로 처리합니다.

---

## 4.2 Qwen grounding

v3에서는:

- `Qwen/Qwen3-VL-32B-Instruct`
- 4-bit NF4 quantization + BF16 compute
- 26,126 candidate span **전체 grounding**
- class별 present / absent / confidence
- unmappable flag
- 초기 parse 오류 24건은 repair 후 0건
- confidence 0.55 미만 evidence 제외
- 미언급 product-class는 negative가 아니라 mask=0

최종 observed product-class pair:

```text
34,168
```

주의:

- 이 값은 v2의 observed pair와 직접 배수 비교하면 안 됨
- v3는 atomic class + exclusive counterpart negative 규칙을 사용하기 때문

---

# 5. v3 FashionCLIP fine-tuning ablation

공통:

- masked BCE
- class imbalance positive weight 사용
- development에서 class별 threshold 선택
- locked test는 최종 보고 전용

비교한 regime:

| regime | 학습되는 부분 |
|---|---|
| frozen | 14-class head만 학습 |
| projection | head + visual projection |
| last1 | head + projection + 마지막 vision block 1개 |
| last2 | head + projection + 마지막 vision block 2개 |
| full | 전체 vision encoder |

결과:

| regime | Dev macro-F1 | Test macro-F1 | Test micro-F1 | Test macro-AP |
|---|---:|---:|---:|---:|
| frozen | 0.6294 | 0.5784 | 0.7621 | 0.5607 |
| projection | 0.6631 | 0.6166 | 0.7824 | 0.6143 |
| last1 | 0.6922 | 0.6050 | 0.8145 | 0.6412 |
| **last2** | **0.6975** | 0.6010 | **0.8216** | 0.6232 |
| full | 0.6736 | 0.5801 | 0.8066 | 0.6073 |

공식 선택 모델은 **development macro-F1 기준 `last2`** 입니다.

locked-test 결과만 보고 `projection`으로 모델을 바꾸면 test selection leakage가 되므로,
공식 모델은 `last2`를 유지해야 합니다.

---

# 6. v3 class imbalance 문제

`last2`의 locked-test 예시:

| class | observed | positive | F1 | AP |
|---|---:|---:|---:|---:|
| soft | 656 | 618 | 0.9702 | 0.9541 |
| firm | 631 | 12 | 0.0000 | 0.0538 |
| elastic | 463 | 390 | 0.9144 | 0.8923 |
| non_elastic | 419 | 21 | 0.0645 | 0.0891 |
| thin | 667 | 461 | 0.8242 | 0.8716 |
| thick | 667 | 197 | 0.5294 | 0.5519 |
| warm | 221 | 157 | 0.8698 | 0.9037 |
| spongy | 13 | 1 | 0.2857 | 0.2000 |

따라서 `soft`, `elastic` 등의 높은 F1을
그대로 "이미지가 촉감을 매우 잘 분류한다"라고 해석하면 안 됩니다.

rare pole / class imbalance / pseudo-label noise를 반드시 고려해야 합니다.

---

# 7. 추가 완료 평가

## 7.1 Category-only baseline

결과 디렉터리:

```text
experiments/13_category_only_baseline/
```

Locked test:

- Macro-F1: **0.5797**
- Micro-F1: **0.7120**
- Macro-AP: **0.5359**

공식 image model `last2`:

- Macro-F1: 0.6010
- Micro-F1: 0.8216
- Macro-AP: 0.6232

차이:

```text
Last2 - Category-only
Macro-F1 : 약 +0.0214
Micro-F1 : +0.1096
Macro-AP : +0.0872
```

Sanity checks: 12/12 PASS

현재 해석:

> image model의 성능이 category prior만으로 전부 설명되지는 않는 신호가 있음.

단, class별로 category baseline을 얼마나 넘는지는 추가 분석 필요.

---

## 7.2 Same-category evaluation

결과 디렉터리:

```text
experiments/14_same_category_evaluation/
```

결과:

- Last2 macro-cell AUROC: **0.6568**
- Pair-weighted AUROC: **0.7528**
- Macro AP lift: **0.1928**
- Reliable (10/10): `0.7144 / 0.7578 / 0.1936`
- Family bootstrap: 1,000회
- Sanity checks: 14/14 PASS

**주의:** `Reliable(10/10)` 뒤의 세 수치가 정확히 어떤 집계 정의인지
결과 JSON/코드를 직접 확인해서 설명해 주세요.

현재 해석:

> 같은 category 안에서도 tactile-positive / negative를 어느 정도 구분하는 signal이 남아 있어,
> 단순 category shortcut만으로 설명되지는 않을 가능성이 있음.

---

# 8. 현재 가장 중요한 연구 문제

WSDM은 recommendation / ranking 중심의 학회이므로,
tactile classification 자체만으로 끝내지 않고
**추천 성능과 사용자 utility로 연결**하려고 합니다.

그런데 다음 문제가 있습니다.

## 문제: 구매 이력을 tactile preference의 정답으로 사용해도 되는가?

Amazon에서 사용자가 상품을 구매한 이유는 다음이 섞여 있습니다.

- 디자인
- 가격
- 브랜드
- 사이즈
- 할인
- 배송
- 노출
- 리뷰
- category
- 기타

따라서:

```text
사용자 u가 상품 i를 구매했다
```

는 사실만으로

```text
사용자 u가 상품 i의 질감을 선호했다
```

라고 간주할 수 없습니다.

즉 실제 purchase interaction은 **general recommendation relevance**의 정답으로는 쓸 수 있지만,
`tactile preference satisfaction`의 유일한 ground truth로 쓰는 것은 논리적으로 약하다고 판단하고 있습니다.

---

# 9. 제안하는 추천 실험 프레임

핵심 아이디어:

> **일반 추천 relevance와 tactile preference satisfaction을 분리해서 평가한다.**

최종 추천은 기존 recommender에 tactile score를 추가하는 reranking 구조부터 시작하는 것을 고려합니다.

```text
S_final(u, i)
=
S_base(u, i)
+
lambda * S_tactile(u, i)
```

`lambda`는 locked test가 아니라 development set에서 선택해야 합니다.

---

# 10. User tactile preference profile

사용자 u의 **과거 리뷰만** 이용해 tactile preference를 추출합니다.

예:

```text
"I love how soft this fabric feels."
→ class = soft
→ preference = positive

"Too thick for summer."
→ class = thick
→ preference = negative

"The fabric is stretchy."
→ class = elastic
→ preference polarity가 명확하지 않으면 단순 evidence로만 사용하거나 별도 처리
```

중요:

현재 v3 Qwen label은 주로 tactile property `present/absent`를 다룹니다.

추천에는 다음 정보가 추가로 필요할 가능성이 큽니다.

```text
tactile class
+
user preference polarity
(like / dislike / neutral-or-unknown)
```

예:

```json
{
  "class": "thick",
  "present": true,
  "preference": "negative"
}
```

질문:

1. 현재 v3 grounding 결과에서 preference polarity를 재사용/파생할 수 있는 정보가 있는지?
2. 없다면 원문 review/span을 대상으로 별도 Qwen grounding을 추가하는 것이 맞는지?
3. sentiment model/LLM 중 어떤 방식이 실험적으로 가장 깔끔한지?

---

# 11. User tactile vector

예시:

```text
User A

soft          +0.8
firm           ?
smooth        +0.3
rough         -0.6
non_elastic    ?
elastic       +0.9
thin          +0.4
thick         -0.8
warm           ?
...
```

원칙:

```text
미언급
≠ dislike
≠ neutral
```

따라서 사용자 profile도 observed mask를 유지해야 합니다.

사용자가 여러 과거 리뷰에서 같은 tactile class를 언급한 경우:

- reviewer가 본인이므로 interaction/time 단위 aggregation 필요
- recency weighting을 넣을지
- confidence weighting을 넣을지
- positive/negative 충돌을 어떻게 처리할지

검토해 주세요.

---

# 12. Item tactile profile

두 가지 setting을 구분합니다.

## 12.1 Review-available item

추천 시점 이전에 이용 가능한 **다른 사용자들의 review evidence**에서 item tactile profile을 생성합니다.

```text
past item reviews
    ↓
Qwen tactile grounding
    ↓
review-derived item tactile profile
```

주의:

해당 target user가 미래에 작성할 test review는 사용하면 안 됩니다.

---

## 12.2 Review-cold-start item

상품의 tactile review evidence를 숨기고:

```text
item image
    ↓
v3 FashionCLIP last2
    ↓
image-predicted 14-class tactile profile
```

을 사용합니다.

이 실험은 "완전한 item cold-start"보다는:

> **review-cold-start / missing tactile evidence**

라고 부르는 것이 더 정확할 수 있습니다.

상품 image/category/metadata는 존재하지만 tactile review evidence가 없는 setting입니다.

---

# 13. Tactile matching score

초기에는 복잡한 neural fusion보다 해석 가능한 score부터 시작하고 싶습니다.

예:

```text
User preference:
soft    +0.9
elastic +0.8
thick   -0.7

Item:
soft    0.8
elastic 0.9
thick   0.2
```

사용자가 관측한 tactile preference class만 사용하여:

```text
S_tactile(u, i)
```

를 계산합니다.

검토 요청:

- dot product
- masked cosine
- signed weighted sum
- learned bilinear score
- MLP fusion

중 무엇을 **첫 baseline**으로 두는 것이 가장 타당한지 제안해 주세요.

가능하면 해석 가능한 단순 baseline → learned fusion 순으로 ablation하고 싶습니다.

---

# 14. Base recommender 후보

초기 baseline 후보:

- Popularity
- BPR-MF
- LightGCN
- SASRec

질문:

1. 현재 Amazon Fashion interaction 구조에서 어떤 모델부터 시작하는 것이 좋은가?
2. user interaction 수가 충분히 긴가?
3. sequential recommendation을 하기 적합한지?
4. 현재 8,498 tactile-item subset만 쓰는 것이 나은지,
   아니면 더 큰 Amazon interaction graph에서 tactile 8,498 item을 subset evaluation하는 것이 나은지?

**현재 실제 user interaction density를 먼저 확인해 주세요.**
임의로 SASRec/LightGCN을 선택하지 말고 데이터 통계를 보고 판단해 주세요.

확인하고 싶은 통계:

- unique user 수
- user당 interaction 수 분포
- 2+, 3+, 5+, 10+ interaction user 수
- item당 interaction 수
- timestamp coverage
- 동일 사용자의 train/dev/test 가능한 비율
- tactile-relevant review를 여러 번 남긴 user 수

---

# 15. 제안하는 평가 1: General recommendation relevance

실제 held-out purchase/interactions를 정답으로 사용합니다.

질문:

> tactile 정보를 추가해도 일반적인 추천 relevance를 유지하는가?

Metric 후보:

- Recall@K
- NDCG@K
- HitRate@K
- MRR

비교:

```text
Base recommender
vs
Base + tactile
```

이 평가에서는 구매 이력을 정답으로 사용해도 됩니다.

하지만 이것을 "tactile satisfaction"으로 해석하면 안 됩니다.

---

# 16. 제안하는 평가 2: Tactile-aware recommendation

전체 purchase가 아니라 **tactile-relevant test interaction**을 별도로 구성하려고 합니다.

예:

```text
Future purchased item review:
"Love how soft and stretchy this is."
```

조건 후보:

1. 실제 future purchase/review item
2. future review에 tactile class가 명시적으로 등장
3. 해당 tactile property에 positive/negative preference polarity가 확인됨

이 future review는 **평가용 label로만 사용**하고
추천 입력에는 절대 사용하지 않습니다.

시간 구조:

```text
Past interactions/reviews
        ↓
user tactile profile
        ↓
recommendation time
        ↓
future purchased item
        ↓
future review
        ↓
evaluation only
```

---

# 17. Tactile-specific 평가의 핵심 고민

단순히 future purchased item 하나를 positive로 두는 것만으로는
여전히 purchase bias가 남습니다.

그래서 다음 중 어떤 평가가 논리적으로 가장 타당한지 검토해 주세요.

### 옵션 A. Tactile-positive held-out item ranking

future review에서 사용자가 positive tactile sentiment를 남긴 purchased item을 positive로 사용.

### 옵션 B. Same-category tactile pairwise ranking

같은 category 안에서:

```text
target user's preferred tactile property와 맞는 item
vs
맞지 않는 item
```

을 비교.

현재 v3 same-category evaluation과 철학적으로 연결됩니다.

### 옵션 C. Tactile alignment metric

Top-K 추천의 item tactile profile이
과거 사용자 tactile preference profile과 얼마나 일치하는지 별도 측정.

예:

- Tactile Match@K
- Tactile NDCG@K
- Preference Satisfaction@K
- Constraint Satisfaction@K

단, 이 metric이 자기참조적(self-fulfilling)이지 않도록
정답 정의를 어떻게 해야 하는지 반드시 검토해 주세요.

### 옵션 D. Future-review preference validation

추천 당시에는 사용하지 않은 future review의 tactile sentiment를 이용해
추천 결과와 실제 미래 preference evidence를 비교.

이 방식이 가장 직접적일 수 있지만 sample 수가 충분한지 확인 필요.

---

# 18. Same-category candidate 설계

category shortcut을 줄이기 위해 tactile-specific evaluation에서는
가능하면 same-category candidate를 사용하려고 합니다.

예:

```text
Target category = blouse

Candidate:
Blouse A
Blouse B
Blouse C
Blouse D
...
```

이 상태에서:

```text
soft 선호
thin 선호
thick 비선호
```

같은 user tactile preference가 ranking에 도움이 되는지 평가합니다.

검토 요청:

- category 단위를 현재 코드에서 무엇으로 정의하는지
- candidate 최소 크기
- hard negative sampling
- full ranking 가능 여부
- sampled negative를 쓸 경우 bias
- family 중복 제거
- 동일 상품 variant 제거

를 제안해 주세요.

---

# 19. Review-cold-start 실험

이 연구에서 가장 중요한 downstream RQ 후보입니다.

### Oracle / upper-bound에 가까운 setting

```text
Base + review-derived tactile
```

### Cold-start setting

```text
Base + image-predicted tactile
```

### No tactile

```text
Base only
```

### Hybrid

```text
review evidence available
→ review-derived tactile

review evidence unavailable
→ image-predicted tactile
```

비교하고 싶은 것:

```text
No tactile
vs
Review tactile
vs
Image tactile
vs
Hybrid
```

핵심 질문:

> 리뷰가 없을 때 image-predicted tactile representation이
> tactile recommendation utility의 일부를 복원하는가?

---

# 20. Baseline / ablation 초안

최소한 다음을 검토해 주세요.

| 모델 | 목적 |
|---|---|
| Popularity | trivial baseline |
| Base Rec | tactile 없는 일반 추천 |
| Base + Category | category prior 효과 |
| Tactile-only | tactile 자체의 signal 확인 |
| Base + Review Tactile | review tactile utility |
| Base + Image Tactile | image tactile utility |
| Base + Hybrid Tactile | practical setting |
| Base + shuffled tactile | sanity check |
| Base + random tactile | sanity check |

추가로 가능하면:

```text
Base + v2 bipolar axis
vs
Base + v3 atomic class
```

를 공정하게 비교하고 싶습니다.

단, **동일 Qwen annotation / 동일 split / 동일 backbone 조건**을 맞춰
representation 효과만 분리해야 합니다.

---

# 21. 추천 논문의 RQ 후보

## RQ1. Tactile preference utility

> Does tactile preference modeling improve tactile alignment of fashion recommendations without substantially degrading conventional recommendation relevance?

필요 평가:

- general NDCG/Recall
- tactile-specific ranking/alignment

---

## RQ2. Review-cold-start

> Can image-predicted tactile attributes recover recommendation utility when review-derived tactile evidence is unavailable?

비교:

- no tactile
- review tactile
- image tactile
- hybrid

---

## RQ3. Beyond category shortcut

> Does tactile-aware ranking capture preference beyond product-category priors?

방법:

- category-only baseline
- same-category candidate evaluation
- category-stratified analysis

현재 image classification 단계에서는 이미:

- category-only baseline
- same-category evaluation

을 완료했습니다.

추천 단계에서도 같은 confound control을 유지하고 싶습니다.

---

# 22. 절대 지켜야 할 leakage 규칙

다음은 추천 입력에 사용하면 안 됩니다.

### 금지 1

```text
target user's future test review
→ user tactile profile
```

### 금지 2

```text
target user's future review
→ test item tactile profile
```

### 금지 3

```text
test 결과
→ lambda / threshold / recommender hyperparameter 선택
```

### 금지 4

```text
same parent family
→ train과 test 양쪽에 등장
```

### 허용 가능한 방향

```text
과거 user reviews
→ user profile

추천 시점 이전의 다른 사용자 review
→ warm item tactile profile

item image
→ review-cold-start tactile profile

future target review
→ evaluation only
```

시간 기준으로 어떤 review가 recommendation 시점에 "available"한지
timestamp로 엄격하게 제어해야 합니다.

---

# 23. Human validation 문제

현재 tactile label은 여전히 Qwen pseudo-label 기반입니다.

따라서 추천 실험이 잘 나오더라도:

```text
실제 physical tactile truth
```

를 예측했다고 주장하면 안 됩니다.

정확한 표현은:

```text
review-derived tactile preference/evidence
```

입니다.

추천 실험 전에 또는 병행하여 다음 human audit이 필요합니다.

- tactile class correctness
- preference polarity correctness
- negation
- rare pole
- fit/comfort와 material tactile 혼동
- garment part / scope
- opposite-pair conflict

이 human audit을 recommendation subset에 맞춰 어떻게 설계하는 것이 좋은지도 제안해 주세요.

---

# 24. Codex에게 우선 요청하는 분석

현재 repository와 산출물을 먼저 확인한 뒤,
다음 질문에 순서대로 답해 주세요.

## A. 데이터 feasibility

1. user-level interaction sequence를 만들 수 있는가?
2. 동일 user가 여러 item을 구매/review한 데이터가 충분한가?
3. tactile preference profile을 만들 수 있을 만큼 반복 tactile review를 남긴 user가 몇 명인가?
4. temporal train/dev/test가 가능한 user 수는?
5. tactile-relevant future review를 가진 test event가 몇 개인가?
6. same-category candidate를 20/30/50개 이상 만들 수 있는 test event가 몇 개인가?

**먼저 이 통계를 계산하는 script/plan을 제안해 주세요.**

---

## B. 기존 산출물 재사용 가능성

아래 v3 결과에서 어떤 데이터를 바로 추천 실험에 재사용할 수 있는지 확인해 주세요.

```text
experiments/12_class_multilabel_fashionclip_ft/
experiments/13_category_only_baseline/
experiments/14_same_category_evaluation/
```

특히 확인:

- product별 14-class review-derived target 파일
- image-predicted probability 파일
- user_id / asin / parent_asin / timestamp 연결 가능 여부
- review span 원문과 grounding 연결
- category 정보
- family split
- target mask/confidence
- Qwen output에 sentiment/preference 관련 정보가 이미 존재하는지

---

## C. 추천 task 정의

아래 중 어떤 task가 현재 데이터에 가장 방어 가능한지 평가해 주세요.

1. next-item recommendation + tactile auxiliary score
2. tactile-aware reranking
3. same-category tactile preference ranking
4. review-cold-start reranking
5. multi-objective recommendation
6. 다른 더 적합한 정의

**WSDM 논문 관점에서 왜 그 task가 가장 적합한지도 설명해 주세요.**

---

## D. Ground truth 설계

다음 각각의 장단점과 leakage 위험을 비교해 주세요.

- purchase-only
- purchase + future tactile-positive review
- future tactile sentiment
- same-category preference pair
- user-profile/item-profile alignment
- human evaluation

그리고:

> 일반 추천 relevance와 tactile satisfaction을 어떤 metric으로 분리해야 하는지

구체적으로 제안해 주세요.

---

## E. Model design

처음부터 복잡한 모델을 만들기보다 다음 순서가 타당한지 검토해 주세요.

```text
1. Base recommender 학습
2. User tactile profile 생성
3. Item tactile profile 생성
4. 단순 tactile matching score
5. lambda reranking
6. learned fusion
```

각 단계의 최소 구현안을 제안해 주세요.

---

## F. 추천 baseline

현재 데이터 크기와 interaction density를 확인한 뒤:

- BPR-MF
- LightGCN
- SASRec
- 다른 모델

중 어떤 baseline 조합이 필요한지 추천해 주세요.

너무 많은 baseline을 무작정 추가하지 말고,
WSDM short/full paper에서 설득력 있는 최소 세트를 제안해 주세요.

---

## G. Evaluation protocol

최종적으로 아래 표를 채울 수 있는 protocol을 설계하고 싶습니다.

| Model | General NDCG@10 | Recall@10 | Tactile metric | Same-category tactile metric | Review-cold-start metric |
|---|---:|---:|---:|---:|---:|
| Base | | | | | |
| + Category | | | | | |
| + Review Tactile | | | | | |
| + Image Tactile | | | | | |
| + Hybrid | | | | | |

필요하다면 추천 metric 구성을 수정해 주세요.

---

# 25. Codex에게 원하는 최종 답변 형식

코드를 수정하기 전에 다음 형식으로 먼저 답해 주세요.

## 1. 현재 repo에서 확인한 사실
- 실제 파일 경로
- 사용할 수 있는 산출물
- user/item/timestamp 데이터 상태

## 2. 데이터 feasibility 통계
- user 수
- interaction density
- temporal split 가능 user 수
- tactile-relevant event 수
- same-category evaluation 가능 event 수

## 3. 가장 추천하는 recommendation task
- task 정의
- 왜 이 task인지
- 다른 후보를 버리는 이유

## 4. Ground truth 설계
- general relevance label
- tactile-specific label
- future review 사용 위치
- leakage 방지

## 5. 추천 파이프라인
데이터 입력부터 최종 locked-test까지 단계별로.

## 6. Baseline / ablation
최소 필수 실험부터 우선순위 순.

## 7. Metric
각 metric이 정확히 무엇을 검증하는지.

## 8. 예상 한계
- purchase bias
- exposure bias
- pseudo-label
- class imbalance
- category shortcut
- user sparsity
- cold-start definition

## 9. 구현 계획
수정/추가해야 할 파일을 예상 경로와 함께 제안.

## 10. GO / NO-GO 판단
현재 Amazon Fashion 데이터만으로 이 WSDM tactile-aware recommendation 실험이
논리적으로 가능한지 평가.

가능하다면 가장 먼저 돌릴 **최소 feasibility experiment**를 하나 제안해 주세요.

---

# 26. 매우 중요한 해석 원칙

결과를 과장하지 말아 주세요.

다음 표현을 구분해 주세요.

- **관측 사실**
- **해석**
- **추가 검증 필요**

특히 아래 주장은 현재 바로 하면 안 됩니다.

```text
"사용자가 질감 때문에 구매했다."
"이미지가 실제 물리적 촉감을 정확히 이해한다."
"Qwen pseudo-label은 ground truth다."
"v3가 category shortcut을 완전히 제거했다."
"구매 NDCG가 높으면 tactile recommendation도 좋다."
```

현재 우리가 검증하고 싶은 핵심은 다음입니다.

> **Review-derived tactile preference는 일반적인 구매 relevance와 다른 보완적 preference dimension인가?**

그리고:

> **Review tactile evidence가 없는 상품에서 image-predicted tactile representation이 그 recommendation utility의 일부를 복원할 수 있는가?**
