# GPT 대화용 실험 컨텍스트 — Review-Cold-Start Tactile Retrieval

> 사용법: 이 문서 전체를 GPT 대화창에 첨부하거나 붙여 넣고, 마지막의 `GPT에게 요청할 응답 방식`과 함께 질문한다. 이 문서는 실험의 사실, 결과, 해석 한계가 한 대화 안에서 유지되도록 만든 독립형 컨텍스트다.

## GPT에게 보내는 시작 메시지

아래는 내가 수행한 **리뷰 기반 촉감 축 grounding 및 리뷰가 없는 상품의 이미지 기반 촉감 검색 실험**에 대한 전체 컨텍스트다. 이후 대화에서는 이 문서의 수치를 기준으로 답해 줘.

- 결과를 과장하지 말고, `관측된 사실`, `가능한 해석`, `아직 검증하지 못한 주장`을 구분해 줘.
- 리뷰에서 언급되지 않은 촉감 속성을 중립값으로 해석하지 마.
- 리뷰 라벨을 물리적 촉감의 객관적 정답이라고 부르지 마.
- active axis와 이미지로 잘 예측되는 axis를 같은 의미로 취급하지 마.
- 전체 순위 성능보다 선택적 예측과 abstention의 효과를 이 실험의 핵심 결과로 다뤄 줘.
- 내가 질문하면 먼저 쉬운 말로 결론을 설명한 뒤, 필요한 경우 수치와 기술적 근거를 덧붙여 줘.

---

## 1. 실험을 한 문장으로 설명하면

구매자 리뷰에 흩어져 있는 촉감 표현을 구조화된 축으로 변환하고, 그 정보를 상품 이미지로 전이하여 **리뷰가 전혀 없는 새 상품도 촉감 조건으로 검색할 수 있는지**, 그리고 **모델이 자신 없는 속성에는 답하지 않는 것이 실제 오류를 줄이는지** 검증한 feasibility 실험이다.

## 2. 핵심 연구 질문

1. 자유로운 리뷰 표현을 일관된 촉감 축과 점수로 바꿀 수 있는가?
2. 리뷰에서 충분히 관측되는 촉감 축은 무엇인가?
3. 상품 이미지만 보고 리뷰 기반 촉감 경향을 예측할 수 있는가?
4. 외부 촉감 데이터에도 그 관계가 전이되는가?
5. 예측이 불확실할 때 abstain/UNKNOWN 처리하면 오류와 검색 품질이 개선되는가?

## 3. 반드시 구분해야 하는 세 상태

이 실험의 가장 중요한 설계 원칙은 다음 세 상태를 섞지 않는 것이다.

| 상태 | 의미 | 처리 |
|---|---|---|
| `REVIEW_UNOBSERVED` | 해당 상품 리뷰에 그 촉감 축이 언급되지 않음 | loss와 평가에서 mask 처리. 0점으로 만들지 않음 |
| reviewer disagreement | 여러 리뷰어가 같은 상품에 대해 서로 다르게 말함 | 분포, agreement, dispersion으로 보존 |
| `VISUAL_ABSTAIN` | 이미지 모델이 해당 촉감을 이미지에서 판단하기 어렵다고 봄 | 촉감 class가 아니라 예측 거부 상태로 처리 |

따라서 **“리뷰에 없음 = 중립”이 아니며, “모델이 모르겠음 = 중립”도 아니다.**

## 4. 데이터와 누수 방지 프로토콜

- 원본 리뷰: 4,158개
- exact span verification row: 6,345개
- Qwen grounding 대상 accepted claim: 4,527개
- 중복 제거된 product family: 465개
- split seed: `20260822`, `20260823`, `20260824`
- 각 seed의 family split: train 325 / development 70 / test 70
- 동일 family가 train과 test에 동시에 들어가지 않는 family-held-out 방식
- 모델 선택, 축 선택, threshold 조정은 train/development에서만 수행
- test review는 최종 평가 relevance로만 사용
- Phase 3 축 선택은 세 seed 모두에서 train+development에 속하는 285개 family의 교집합만 사용

주의: 현재 Amazon test는 feasibility용 held-out split이다. 연구 과정에서 전혀 들여다보지 않은 별도의 최종 독립 test set은 아니다.

## 5. 촉감 축의 표현 방식

각 촉감 속성은 두 극을 가진 bipolar ordinal axis다.

- negative pole: `-1`
- positive pole: `+1`
- neutral: `0`
- strong intensity: 기본 방향 점수에 2배를 적용하여 대략 `-2` 또는 `+2`

여기서 negative/positive는 나쁨/좋음이 아니라 축의 방향을 나타내는 기호다. 예를 들어 softness에서 `soft`가 negative pole이고 `firm`이 positive pole일 수 있지만 품질 평가의 부정/긍정과는 관계없다.

Qwen은 숫자를 직접 생성하지 않고 `axis`, `pole`, `intensity`, `scope` 같은 symbolic label을 출력했다. 실제 숫자 점수는 고정된 config와 reviewer-first aggregation으로 결정했다. 원문의 exact span은 모든 grounding record에 보존했다.

## 6. Phase 0~11에서 실제로 한 일

### Phase 0 — 프로토콜과 입력 감사

원본 리뷰, 검증 span, 상품 family, 이미지, frozen embedding, Qwen checkpoint를 확인하고 데이터 누수 경계를 고정했다.

### Phase 1 — 촉감 taxonomy 선언

7개 후보 축과 양쪽 pole, ordinal coding, 선택 기준을 YAML config로 선언했다. 코드에 축 이름을 개별적으로 박아 넣지 않고 설정 기반으로 동작하게 만들었다.

### Phase 2 — Qwen 리뷰 span grounding

- 모델: `Qwen/Qwen3-VL-8B-Instruct`
- 고정 snapshot: `0c351dd01ed87e9c1b53cbc748cba10e6187ff3b`
- temperature: 0
- schema 성공: 4,527 / 4,527
- taxonomy에 mapping 가능: 2,596
- mapping 불가: 1,931, 즉 42.4%

Qwen 출력 중 엄격한 schema와 의미를 해치지 않는 8개 제한적 alias만 provenance를 남기고 정규화했다. 예: `medium → neutral`, `inner_surface → lining`, source span ID 우선 적용. 이 과정에서 임의의 촉감 점수를 만들어 넣지 않았다.

### Phase 3 — 축 타당성 진단과 active axis 선택

각 후보 축에 대해 mapped span 수, unique product 수, 양쪽 pole의 상품 수, 다중 reviewer 상품 수, category 집중도, Qwen mapping confidence, 접근 가능한 외부 검증 데이터 유무를 검사했다.

사전 선택 기준은 다음과 같다.

- mapped span 30개 이상
- unique product 20개 이상
- 각 pole에 상품 5개 이상
- reviewer 2명 이상인 상품 3개 이상
- 최다 category 비율 0.9 이하
- 평균 Qwen mapping confidence 0.75 이상
- 접근 가능한 외부 검증 source 존재

### Phase 4 — 사람 검증용 audit sheet

axis, direction, intensity, property status, scope를 고려한 deterministic stratified sampling으로 600개 행의 human audit CSV를 만들었다. 그러나 사람 라벨은 아직 0/600이다. 따라서 pseudo-label 정확도, 일치도, 오류율은 **계산되지 않았으며 pending**이다.

사람이 즉시 작업할 수 없는 상황에서 후속 v2 탐색을 위한 **임시 AI consistency audit**도 별도 수행했다. 같은 Qwen checkpoint에 기존 판정을 보여주지 않고 더 보수적인 독립 prompt로 600개를 다시 판정했으며 schema 성공은 600/600이었다. 이는 독립적인 사람 검증이 아니므로 원본 human 칸은 비워 두었고 `human_labels_complete=false`를 유지했다.

- 핵심 의미 일치율(mappability/axis/polarity, intensity·scope 제외): 69.3%
- 현재 점수 coding 기준 score-equivalent 일치율(scope 제외): 44.8%
- 완전 symbolic 일치율: 30.2%
- 양쪽 모두 mappable인 행의 axis macro-F1: .953
- polarity accuracy: .886
- intensity weighted kappa: .107
- 향후 사람 검토 high priority: 184개
- 향후 사람 검토 medium priority: 235개
- 전체 symbolic label 일치: 181개

이 결과는 기존 pseudo-label을 사람 기준으로 정확하다고 인증하지 않는다. 오히려 mappability 135건, axis 22건, direction 49건, intensity 217건, scope 91건의 불일치 신호를 찾아 향후 사람 검수 순서를 정하는 triage 자료다. 특히 강도와 scope 정의를 v2 prompt에서 더 명확히 고정해야 한다는 신호로 해석한다.

### Phase 5 — 리뷰어 우선 상품 target 생성

먼저 `(family, reviewer, axis)` 안의 여러 span을 평균하고, 그다음 reviewer별 값을 동일 가중치로 평균했다. 리뷰를 많이 작성한 한 사람이 상품 점수를 지배하지 않도록 한 것이다.

- 가능한 product-axis pair: 465 × 4 = 1,860
- 리뷰에서 관측된 pair: 829, 44.6%
- 관측되지 않은 pair: 1,031, 55.4%
- reviewer-axis record: 1,462

관측되지 않은 55.4%는 0점이나 neutral label로 채우지 않고 mask 처리했다. 각 target에는 support, agreement, dispersion, entropy 등의 정보도 보존했다.

### Phase 6~7 — 이미지 모델 및 학습 방식 비교

비교한 방법은 category-only, FashionCLIP linear/ridge, FashionCLIP+category ridge, DINOv2 ridge, ordinal logistic, pairwise logistic, tiny MLP, 기존 open 384차원 vector baseline, Qwen VLM image-only zero-shot이다. 학습 가중치는 equal, log-support, agreement, support×agreement를 비교했다.

### Phase 8 — 외부 데이터 전이

MLLM-Fabric의 RGB 이미지 220개를 사용했다. 110개는 property recoverability calibration, 나머지 110개는 서로 겹치지 않는 external test로 사용했다. Leeds 데이터는 raw image+rating 공개 및 license를 확인하지 못해 사용할 수 없다고 명시했다.

### Phase 9 — 선택적 예측과 calibration

FashionCLIP Ridge bootstrap ensemble 20개로 instance uncertainty를 얻고, Phase 8의 axis별 external recoverability와 분리하여 사용했다. development 데이터만으로 `[instance confidence, property recoverability, 두 값의 곱]`을 입력으로 받는 공통 logistic calibrator를 학습했다. test의 관측된 product-axis example 125개에서 risk-coverage를 평가했다.

### Phase 10 — 리뷰가 없는 상품 검색

single-axis query 40개와 multi-axis query 12개, 총 52개를 구성했다. 후보는 같은 category 안에서 최소 4개가 되도록 했고, 숨겨 둔 test review는 relevance 평가에만 사용했다.

UNKNOWN 정책은 세 가지였다.

- U0: abstain한 constraint의 기여도를 0으로 둠
- U1: abstain에 약한 `-0.1` penalty
- U2: 약한 penalty에 더해, 지원되는 constraint의 비율로 최종 score를 조정

### Phase 11 — 통합 평가

세 family split의 평균, bootstrap confidence interval, 가설 판정, manifest, unit test를 통합했다. unit test는 20/20 통과했고 최종 manifest 상태는 `complete`다.

## 7. Phase 3 축 구성과 선택 결과

아래 통계는 전체 465 family가 아니라, 누수 방지용 Phase 3 selection family 285개에서 계산한 값이다.

| 후보 축 | 양쪽 pole | mapped span | 상품 | 2명 이상 reviewer 상품 | 리뷰 미관측률 | pole별 상품 | 평균 Qwen confidence | 결정 |
|---|---|---:|---:|---:|---:|---|---:|---|
| softness | soft ↔ firm | 499 | 164 | 102 | 42.5% | soft 154 / firm 23 | .978 | ACTIVE |
| surface_texture | smooth ↔ rough | 102 | 47 | 10 | 83.5% | smooth 21 / rough 31 | .952 | ACTIVE |
| elasticity | non_elastic ↔ elastic | 223 | 98 | 32 | 65.6% | non-elastic 45 / elastic 77 | .965 | ACTIVE |
| thickness | thin ↔ thick | 549 | 184 | 102 | 35.4% | thin 146 / thick 68 | .971 | ACTIVE |
| flexibility | flexible ↔ stiff | 70 | 31 | 6 | 89.1% | flexible 2 / stiff 30 | .964 | INACTIVE |
| warmth | warm ↔ cool | 117 | 58 | 23 | 79.6% | warm 44 / cool 25 | .965 | INACTIVE |
| sponginess | spongy ↔ crisp | 9 | 3 | 0 | 98.9% | spongy 0 / crisp 3 | .967 | INACTIVE |

inactive 이유:

- flexibility: flexible 쪽 상품이 2개뿐이라 pole balance 기준 실패, 검증 가능한 외부 source도 없음
- warmth: 접근 가능한 외부 검증 source 없음
- sponginess: span/product/reviewer/pole support가 모두 부족하고 외부 source도 없음

**ACTIVE는 리뷰에서 분석할 최소 데이터 조건을 통과했다는 뜻이지, 이미지로 잘 보이거나 잘 예측된다는 뜻이 아니다.** 실제로 surface texture는 active였지만 이미지 예측 결과는 불안정했다.

## 8. 주요 정량 결과

### 8.1 이미지 기반 축 예측 — Spearman 상관계수

Spearman은 상품의 상대적 순서를 얼마나 잘 맞췄는지 나타낸다. `1`에 가까울수록 좋고, `0`은 순서 관계가 거의 없으며, 음수는 반대 방향 경향이다. 아래 값은 세 family split 평균이다.

| 방법 | softness | surface texture | elasticity | thickness |
|---|---:|---:|---:|---:|
| category-only | .084 | .142 | .248 | -.130 |
| DINO Ridge | .075 | .086 | .148 | **.270** |
| FashionCLIP linear | .012 | -.211 | .184 | .060 |
| FashionCLIP Ridge | .051 | -.175 | .280 | .087 |
| image+category Ridge | .047 | -.107 | .230 | .126 |
| ordinal | -.007 | .047 | .286 | .032 |
| pairwise | .005 | -.235 | .188 | .078 |
| tiny MLP | .022 | -.218 | **.323** | .136 |

해석:

- elasticity는 tiny MLP의 `.323`이 가장 좋았다.
- thickness는 DINO Ridge의 `.270`이 가장 좋았다.
- softness는 모든 방법에서 약했다.
- surface texture는 여러 이미지 모델에서 음수로 매우 불안정했다.
- category-only가 예상보다 강해 category proxy/confounding 가능성이 크다.
- 모든 축에 공통으로 우수한 단일 모델은 없었다.

### 8.2 Qwen VLM image-only zero-shot

Qwen이 `visually_assessable=true`라고 응답한 pair에서만 계산했으므로 위의 full split 학습 모델과 직접적인 공정 비교는 아니다.

| 축 | 평가 표본 | Spearman | MAE | 방향 정확도 |
|---|---:|---:|---:|---:|
| softness | 41 | .162 | .931 | .854 |
| surface texture | 15 | -.093 | 2.150 | .467 |
| elasticity | 18 | .133 | 1.463 | .556 |
| thickness | 43 | .159 | 1.529 | .615 |

70개 이미지 입력 모두 schema 처리에 성공했다. 불완전하게 반환된 6개 출력은 누락 축을 `visually_assessable=false`, confidence 0으로 보수적으로 복구했고 촉감 점수를 임의로 생성하지 않았다.

### 8.3 외부 전이 — MLLM-Fabric test 110개

Pairwise accuracy의 무작위 기준은 약 `.5`다.

| 축 | Spearman | pairwise accuracy | calibration half의 property recoverability |
|---|---:|---:|---:|
| softness | .021 | .511 | .009 |
| surface texture | .108 | .552 | .299 |
| elasticity | -.074 | .455 | .012 |
| thickness | .067 | .535 | .057 |

- 외부 pairwise accuracy 평균: `.5132`
- 형식적으로 `.5`를 조금 넘어서 H2 기준은 통과했다.
- 그러나 차이가 매우 작으므로 실질적인 외부 일반화 성능은 약하다.

### 8.4 선택적 예측 — AURC와 coverage-risk

AURC는 모델이 자신 있는 것부터 남겼을 때 coverage 전 구간에서 발생하는 risk를 요약하며 **낮을수록 좋다**.

| confidence 방법 | AURC ↓ |
|---|---:|
| confidence only | .8086 |
| external recoverability only | 1.0948 |
| confidence × recoverability | 1.0667 |
| learned calibrator | **.6715** |

learned calibrator의 고정 coverage 결과:

| nominal coverage | 실제 coverage | MAE risk | 대략 남은 표본 수 |
|---:|---:|---:|---:|
| 1.0 | 1.000 | .8362 | 125/125 |
| .8 | .816 | .7327 | 102/125 |
| .6 | .608 | .6995 | 76/125 |
| .4 | .424 | .6701 | 53/125 |

이 실험에서 가장 분명한 긍정적 결과다. 모든 예측을 강제할 때보다, development에서 정한 confidence threshold로 약 18%를 거절했을 때 test MAE가 `.8362 → .7327`로 감소했다. 단, external recoverability만 단독으로 사용하는 것은 효과적이지 않았다.

### 8.5 Cold-start 검색 — NDCG@10

NDCG@10은 추천 순위 상위 10개의 품질이며 높을수록 좋다.

| 방법 | NDCG@10 |
|---|---:|
| structured no abstention | .7298 |
| confidence selective | .7393 |
| proposed calibrator U0 | .7547 |
| proposed calibrator U1 | .7488 |
| proposed UNKNOWN coverage U2 | .7487 |
| FashionCLIP taxonomy zero-shot | .7497 |
| Qwen VLM zero-shot | .7654 |
| open 384d current split | .7660 |
| category-only | .7687 |
| random | **.7837** |

U2와 forced structured를 query별 paired bootstrap으로 비교하면:

- 평균 차이: `+.0188`, 반올림하면 `+.019`
- 95% CI: `[.002, .040]`

따라서 **같은 structured system 안에서는 UNKNOWN-aware abstention이 강제 예측보다 유의하게 개선**됐다. 하지만 random이 가장 높았고 대부분 방법의 Recall@10도 약 `.98`이었다. 이는 후보군이 작고 relevance가 조밀하여 현재 retrieval benchmark가 쉬우며 변별력이 부족할 가능성이 높다는 뜻이다. proposed method가 모든 baseline보다 우수하다고 주장할 수 없다.

## 9. 사전 가설 판정

| 가설 | 판정 | 근거 |
|---|---|---|
| H1: structured image model이 category-only와 open-vector보다 우수 | **기각** | 축 평균 Spearman `.0608 < .0859`; retrieval `.7298 < .7660` |
| H2: 외부 pairwise 평균이 무작위 `.5`보다 높음 | **지지, 하지만 매우 약함** | `.5132` |
| H3: confidence+recoverability learned calibrator가 confidence-only보다 낮은 AURC | **지지** | `.6715 < .8086` |
| H4: 80% 선택적 예측이 full coverage보다 MAE risk 감소 | **지지** | 실제 coverage `.816`에서 `.7327 < .8362` |
| H5: UNKNOWN-aware ranking이 forced structured보다 NDCG@10 향상 | **지지** | `.7487 > .7298`, paired CI `[.002, .040]` |

## 10. 이 결과에서 가장 주목해야 할 점

### 10.1 가장 강한 결과는 “이미지로 촉감을 잘 맞힌다”가 아니다

원시 예측 성능은 전반적으로 낮고 축마다 편차가 크다. 특히 외부 전이는 거의 무작위 수준이다. 이 실험이 보여 준 더 믿을 만한 결과는 **모델이 자신 없는 예측을 거절하면 남은 결과의 평균 오류가 줄어든다**는 것이다.

### 10.2 데이터의 절반 이상이 부정 예제가 아니라 미관측이다

product-axis pair의 55.4%가 리뷰에서 언급되지 않았다. 이를 neutral로 채우면 “말하지 않음”을 “중간 촉감”으로 잘못 학습하게 된다. 이 실험의 mask 설계는 성능 수치만큼 중요한 방법론적 기여다.

### 10.3 리뷰에서 충분히 나오는 축과 이미지에서 보이는 축은 다르다

surface texture는 Phase 3 기준을 통과했지만 이미지 예측은 불안정했다. 반대로 어떤 축은 이미지 feature와 관계가 있어도 리뷰 언급량이나 pole balance 때문에 학습 target으로 부적절할 수 있다. 따라서 `review feasibility`와 `visual recoverability`를 별도 gate로 둬야 한다.

### 10.4 category shortcut이 강하다

복잡한 이미지 모델보다 category-only가 여러 조건에서 경쟁력이 있었다. 모델이 소재의 미세한 촉감을 읽는 대신 “이 category는 보통 두껍다/신축성이 있다” 같은 평균 경향을 사용하는지 점검해야 한다.

### 10.5 축별 전략이 필요하다

elasticity와 thickness는 초기 후속 연구 후보지만, softness는 약하고 surface texture는 불안정했다. 하나의 공통 모델과 threshold를 모든 축에 적용하기보다 축별 모델, confidence, abstention 정책을 고려해야 한다.

## 11. 이 실험으로 주장할 수 있는 것과 없는 것

### 주장할 수 있는 것

- 리뷰 span을 7개 후보 촉감 축에 schema 기반으로 grounding하는 파이프라인을 구축했다.
- 누수 없는 selection split에서 4개 active axis를 식별했다.
- 미관측 review target과 neutral target을 분리한 sparse target을 만들었다.
- 일부 축, 특히 elasticity와 thickness에서 약한 이미지 예측 신호가 관측됐다.
- development에서 calibration한 selective abstention이 test risk를 낮췄다.
- 같은 structured retrieval system 안에서 UNKNOWN-aware 정책이 강제 예측보다 나았다.

### 아직 주장하면 안 되는 것

- 이미지가 실제 물리적 촉감을 정확히 예측한다.
- Qwen pseudo-label이 사람 수준으로 정확하다.
- 제안 방법이 모든 retrieval baseline보다 우수하다.
- Amazon에서 얻은 관계가 외부 데이터에 강하게 일반화된다.
- current test가 완전히 untouched인 최종 성능이다.
- 리뷰에 언급되지 않은 축은 neutral이다.

## 12. 남은 위험과 후속 실험 우선순위

1. **600개 human audit 완성**  
   axis mapping, pole, intensity, scope별 정확도와 사람 간 일치도를 계산해야 한다.

2. **완전히 untouched인 새 product-family final test 구성**  
   연구 과정에서 한 번도 선택이나 해석에 사용하지 않은 최종 평가셋이 필요하다.

3. **더 어려운 retrieval benchmark 설계**  
   후보 수를 늘리고 relevance를 더 희소하게 만들며 hard negative를 추가해야 한다. random NDCG가 가장 높은 현재 상태로는 방법 간 차이를 신뢰하기 어렵다.

4. **축별 모델과 abstention 적용**  
   elasticity와 thickness를 우선 대상으로 삼고, 축마다 threshold와 모델을 다르게 선택한다.

5. **category shortcut 통제**  
   category-balanced evaluation, category residual target, within-category hard negative로 이미지가 실제 축 정보를 사용하는지 확인한다.

6. **외부 일반화 재검증**  
   더 크고 명확하게 정렬된 외부 촉감 데이터셋을 확보하여 calibration과 test를 엄격히 분리한다.

## 13. 지표를 쉬운 말로 해석하는 법

| 지표 | 쉬운 의미 | 방향 |
|---|---|---|
| Spearman | 상품의 촉감 순서를 얼마나 잘 맞췄는가 | 높을수록 좋음 |
| MAE | 예측 점수가 정답 점수에서 평균적으로 얼마나 벗어났는가 | 낮을수록 좋음 |
| Pairwise accuracy | 두 상품 중 어느 쪽이 축의 positive 방향인지 맞힌 비율 | `.5`가 무작위, 높을수록 좋음 |
| AURC | 자신 있는 예측부터 사용할 때 coverage 전반의 평균 risk | 낮을수록 좋음 |
| Coverage | 전체 중 모델이 답을 내놓은 비율 | 높음이 항상 좋은 것은 아님 |
| NDCG@10 | 검색 결과 상위 10개의 순서 품질 | 높을수록 좋음 |

## 14. 재현성과 결과 파일

프로젝트 경로:

`/home/user/onsesang/material_span_grounding/tactile_coldstart_qwen_v1`

주요 파일:

- 전체 실행 문서: `notion/TACTILE_COLDSTART_PHASE_0_TO_11.md`
- Phase 3 상세 문서: `notion/PHASE_3_TACTILE_AXIS_FEASIBILITY.md`
- 최종 ablation 보고서: `reports/phase11_full_ablation.md`
- 최종 manifest: `manifests/phase11_final.json`
- 리뷰 span grounding: `artifacts/axis_groundings.jsonl`
- product-axis target: `artifacts/product_axis_targets.jsonl`, `artifacts/product_axis_targets.npz`
- 사람 검증용 600행: `artifacts/human_axis_audit.csv`
- 임시 AI consistency audit: `artifacts/provisional_ai_axis_audit.csv`, `reports/phase4_provisional_ai_audit.md`
- 외부 전이: `artifacts/external_transfer_results.json`
- selective prediction: `artifacts/phase9_selective_results.json`
- retrieval: `artifacts/phase10_retrieval_results.json`
- 최종 machine-readable 결과: `artifacts/phase11_paper_results.json`

## 15. GPT에게 요청할 응답 방식

이 문서를 읽은 뒤 다음 원칙으로 나와 대화해 줘.

1. 먼저 이 실험의 결론을 5문장 이내로 요약해 줘.
2. 이어서 가장 강한 증거 3개와 가장 큰 한계 3개를 구분해 줘.
3. 수치를 인용할 때 어떤 평가 조건의 수치인지 함께 말해 줘.
4. 결과로 직접 증명되지 않은 해석은 반드시 “가능한 해석”이라고 표시해 줘.
5. 내가 논문 주장, 후속 실험, 오류 분석, 표/그림, 발표 자료를 요청하면 이 문서의 수치와 한계를 유지해 줘.
6. 정보가 부족하면 추측해 채우지 말고, 어떤 artifact를 추가로 확인해야 하는지 물어봐 줘.

처음에는 다음처럼 답해 줘:  
**“컨텍스트를 이해했습니다. 이 실험의 핵심은 원시 촉감 예측의 우수성보다, 리뷰 미관측을 중립과 분리하고 불확실한 이미지 예측을 선택적으로 거절했을 때 위험이 감소했다는 점입니다.”**
