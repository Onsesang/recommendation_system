# GPT 대화용 실험 컨텍스트 — Tactile Cold-Start v2 Full-Pool

> 사용법: 이 문서 전체를 GPT 대화창에 첨부하거나 붙여 넣는다. 이후 질문에서는 이 문서의 실험 설계, 수치, 해석 경계를 기준으로 답하도록 요청한다.

## GPT에게 보내는 시작 메시지

아래는 구매자 리뷰의 촉감 표현을 구조화하고, 리뷰가 없는 새 상품의 이미지에서 촉감 방향을 예측하여 검색에 사용하는 **Tactile Cold-Start v2 Full-Pool 실험**의 전체 컨텍스트다.

이후 답변에서는 다음 원칙을 지켜 줘.

- 먼저 비전문가도 이해할 수 있는 말로 결론을 설명한 뒤 필요한 수치를 제시해 줘.
- `실제로 관측된 결과`, `가능한 해석`, `아직 검증되지 않은 주장`을 구분해 줘.
- 리뷰 기반 Qwen pseudo-label을 물리적 촉감의 객관적 ground truth라고 부르지 마.
- 리뷰에 어떤 축이 언급되지 않은 상태를 neutral이나 0점으로 해석하지 마.
- Phase 3에서 active인 축과 이미지에서 잘 예측되는 축을 같은 의미로 취급하지 마.
- category-only baseline보다 못한 이미지 결과를 촉감 시각 추론 성공으로 해석하지 마.
- test 표본이 작은 flexibility, warmth, surface texture 결과는 과장하지 마.
- v1과 v2는 데이터 크기뿐 아니라 target coding, 축 선택 기준, split, retrieval 난이도가 다르므로 절댓값을 단순 승패로 비교하지 마.
- 사람 검증이 완료되지 않았다는 한계를 모든 최종 결론에 반영해 줘.

---

## 1. 실험을 한 문장으로 설명하면

조건을 만족한 전체 상품 풀의 구매자 리뷰에서 촉감 표현을 찾아 구조화된 촉감 축으로 변환하고, 이 review-derived pseudo-target을 상품 이미지로 예측하여 **리뷰가 없는 새로운 product family도 촉감 조건으로 검색할 수 있는지**, 그리고 **자신 없는 예측을 거절하면 오류가 줄어드는지** 확인한 feasibility 실험이다.

## 2. 이번 v2에서 확인하려는 질문

1. v1의 500개 시작 표본이 아니라 전체 적격 상품에서도 파이프라인이 동작하는가?
2. 자유로운 리뷰 표현을 일관된 bipolar 촉감 축으로 변환할 수 있는가?
3. 리뷰 데이터만으로 학습 가능한 촉감 축은 무엇인가?
4. 새 parent product family의 이미지만 보고 review-derived 촉감 방향을 예측할 수 있는가?
5. 상품 category 평균을 넘어서는 실제 이미지 신호가 존재하는가?
6. Amazon에서 학습한 관계가 외부 MLLM-Fabric 데이터에도 전이되는가?
7. 모델이 자신 없는 예측에 abstain하면 남은 예측의 오류가 감소하는가?
8. 촉감 예측이 review-cold-start 상품 검색 순위를 개선하는가?

## 3. “전체 상품을 사용했다”는 말의 정확한 의미

이번 실험은 v1처럼 처음에 500개 ASIN을 뽑지 않았다. 아래 조건을 만족한 **전체 8,498개 ASIN**을 데이터셋과 이미지 특징 추출에 포함했다.

- 원본 source의 train 영역에 속함
- 로컬 상품 이미지가 존재하고 읽을 수 있음
- 40~2,000자 리뷰를 가진 서로 다른 reviewer가 5명 이상 존재함
- ASIN별로 reviewer당 리뷰 1개만 사용
- ASIN별 최대 10개 리뷰 사용

전체 범위는 다음과 같다.

- 적격 ASIN: 8,498개
- parent product family: 7,365개
- 선택 리뷰: 70,943개
- 모든 리뷰를 훑어 찾은 high-recall lexical candidate: 26,126개
- 촉감 후보가 하나 이상 나온 ASIN: 8,064개
- 후보가 없지만 dataset과 image feature에 유지한 ASIN: 434개
- Qwen 문맥 검증용 reviewer-first 대표 구절: 8,641개

중요한 구분이 있다.

**상품 8,498개와 리뷰 70,943개는 전부 census와 candidate 검색에 포함했지만, 26,126개 후보 span을 모두 Qwen에 넣은 것은 아니다.** 확장 비용과 중복을 통제하기 위해 촉감 후보가 있는 ASIN마다 대표 구절 1개를 선택하고, reviewer 일치도를 보기 위해 축별 최대 100개 상품에서 두 번째 독립 reviewer 구절을 추가했다. 그 결과 Qwen 판정 대상은 8,641개가 됐다.

즉 v2는 모든 적격 상품을 포함한 전수 풀 실험이지만, 각 상품의 모든 촉감 문장을 완전 라벨링한 dense annotation 실험은 아니다.

## 4. 반드시 구분해야 하는 상태

| 상태 | 의미 | 처리 |
|---|---|---|
| `REVIEW_UNOBSERVED` | 해당 상품 리뷰에서 그 촉감 축이 관측되지 않음 | 0점으로 채우지 않고 loss와 평가에서 mask 처리 |
| `neutral` | 리뷰가 축의 중간 방향을 명시적으로 표현함 | 방향 점수 0으로 사용 가능 |
| reviewer disagreement | 여러 reviewer가 같은 상품에 대해 다르게 표현함 | agreement, dispersion, entropy로 보존 |
| `VISUAL_ABSTAIN` | 이미지 모델이 해당 촉감을 신뢰하기 어렵다고 판단함 | 촉감 class가 아니라 예측 거부 상태로 처리 |
| Qwen `unmappable` | 리뷰 문장이 taxonomy의 촉감 축으로 안전하게 변환되지 않음 | 촉감 라벨을 만들지 않고 거절 |

따라서 다음 등식은 모두 틀리다.

- 리뷰에 없음 = neutral
- 모델이 모르겠음 = neutral
- Qwen 거절 = negative pole
- active axis = 이미지에서 잘 보이는 axis

## 5. v1 결과를 반영해 바꾼 핵심 설계

v1의 임시 AI consistency audit에서는 axis와 polarity보다 intensity 구분이 훨씬 불안정했다.

- 양쪽 모두 mappable인 행의 axis macro-F1: .953
- polarity accuracy: .886
- intensity weighted kappa: .107
- score-equivalent 일치율: 44.8%

이를 반영해 v2의 주 target은 intensity를 곱한 `-2~-1~0~+1~+2` 점수가 아니라 **방향 중심 `-1 / 0 / +1`**로 변경했다.

- negative pole: -1
- explicit neutral: 0
- positive pole: +1
- 원 intensity는 삭제하지 않고 진단 정보로 보존
- Qwen은 symbolic axis/direction/intensity/scope만 출력
- 실제 방향 숫자는 고정 config로 결정론적으로 변환

또한 외부 데이터 사용 가능 여부를 Phase 3 내부 축 선택의 필수조건에서 제거했다.

- Phase 3: 리뷰에서 학습 가능한 축인가?
- Phase 8: 외부 데이터에서도 시각적으로 검증 가능한가?

두 질문을 분리했기 때문에 v1에서 inactive였던 flexibility와 warmth도 v2에서는 내부 active axis가 될 수 있었다.

## 6. family-safe split과 누수 방지

예측 단위는 ASIN이지만 분할 단위는 parent product family다. 같은 family의 ASIN이 train과 test에 동시에 들어가는 것을 막았다.

| split | ASIN | parent family |
|---|---:|---:|
| train | 6,300 | 5,295 |
| development | 1,077 | 1,035 |
| locked test | 1,121 | 1,035 |

추가 누수 방지 규칙은 다음과 같다.

- 기존 v1에서 사용된 parent family 471개를 전부 train에 강제 배치
- development와 locked test는 v1에서 보지 않은 family로 구성
- Phase 3 active axis 선택에는 train만 사용
- 모델과 hyperparameter 선택에는 train/development만 사용
- abstention threshold와 calibrator는 development만 사용
- locked test 리뷰는 최종 평가 target과 retrieval relevance로만 사용
- parent family split 중복은 0개
- split 누수 관련 unit test 통과

v2는 v1보다 훨씬 큰 locked family test를 갖지만 split seed는 `20260901` 하나다. 따라서 v1의 3-seed 평균보다 family 다양성은 크지만, seed 변화에 따른 분산 평가는 부족하다.

## 7. Phase 0~11에서 수행한 일

### Phase 0 — 전체 적격 풀 census와 프로토콜 고정

500개 상한을 제거하고 적격 ASIN 8,498개, parent family 7,365개, 리뷰 70,943개를 확정했다. 이미지 8,498개가 모두 읽히는지 검사했으며 손상 이미지는 0개였다. 모든 리뷰에서 high-recall lexical candidate 26,126개를 보존하고 family-safe split을 생성했다.

### Phase 1 — 촉감 taxonomy 동결

7개 후보 축과 bipolar pole, direction-only primary coding, 축 선택 기준을 YAML 설정으로 고정했다.

- softness: soft ↔ firm
- surface texture: smooth ↔ rough
- elasticity: non-elastic ↔ elastic
- thickness: thin ↔ thick
- flexibility: flexible ↔ stiff
- warmth: warm ↔ cool
- sponginess: spongy ↔ crisp

### Phase 2 — Qwen 리뷰 구절 문맥 grounding

- 모델: `Qwen/Qwen3-VL-8B-Instruct`
- snapshot: `0c351dd01ed87e9c1b53cbc748cba10e6187ff3b`
- deterministic decoding
- 출력: `[mappable, axis, direction, intensity, scope, confidence]`의 6개 정수 코드
- schema success: 8,641 / 8,641
- mappable: 5,710, 66.1%
- unmappable: 2,931, 33.9%

Qwen은 키워드가 있더라도 fit, size, durability, 날씨 선호, 비유적 표현 등 소재 촉감으로 안전하게 해석할 수 없는 문장을 거절했다.

엄격 검증 과정에서 축/방향 코드 위치가 명백히 뒤바뀐 21건은 코드만으로 결정론적으로 교정했다. 유효 축을 복원할 수 없는 3건은 임의 축을 만들지 않고 confidence 0의 unmappable로 fail-closed 처리했다. 원시 응답과 교정 사유는 모두 보존했다.

### Phase 3 — train-only 촉감 축 feasibility 진단

축 선택에는 train의 6,300개 ASIN, 5,295개 parent family만 사용했다. 다음 조건을 모두 만족해야 active로 선택했다.

- mapped span 30개 이상
- unique product 20개 이상
- 양쪽 pole에 각각 상품 5개 이상
- 독립 reviewer 2명 이상인 상품 3개 이상
- 최다 category 비율 90% 이하
- 평균 Qwen mapping confidence .70 이상
- 외부 데이터 지원 여부는 내부 선택의 필수조건으로 사용하지 않음

### Phase 4 — human audit 보류

600개 행의 deterministic audit CSV를 생성했지만 사용자 요청에 따라 사람 검증은 이번 실행에서 건너뛰었다.

- 상태: `skipped_by_user_pending`
- human validation complete: false
- downstream label: Qwen pseudo-label
- 물리적 촉감 ground truth라고 주장할 수 없음

### Phase 5 — reviewer-first sparse product target 생성

같은 reviewer가 여러 span을 말해도 `(product, reviewer, axis)` 안에서 먼저 평균하고, 그다음 reviewer를 동일 가중치로 평균했다. 리뷰를 많이 쓴 한 사람이 상품 점수를 지배하지 않도록 했다.

- reviewer-axis record: 5,680개
- 관측 product-axis pair: 5,482개
- 미관측 product-axis pair: 45,506개
- 가능한 8,498 × 6 pair 중 관측률: 10.8%
- 미관측률: 89.2%

v2는 절대 라벨 수는 늘었지만 상품 수와 active axis가 크게 늘어 축별 target은 매우 희소하다. 이는 이후 결과를 해석할 때 가장 중요한 제약이다.

### Phase 6 — 전체 이미지 특징 추출

8,498개 이미지 모두에서 두 종류의 frozen visual feature를 추출했다.

- FashionCLIP embedding: 8,498개
- DINOv2-small embedding: 8,498개
- 누락 이미지: 0개

### Phase 7 — 이미지 기반 촉감 방향 모델 비교

다음 모델과 control을 비교했다.

- category-only
- FashionCLIP linear
- FashionCLIP Ridge
- FashionCLIP + category Ridge
- DINO Ridge
- ordinal logistic
- pairwise logistic
- tiny MLP
- 선택과 무관한 보조 open 384-dimensional baseline

hyperparameter와 최종 방법은 development에서만 선택하고 locked family test에서 평가했다. 보조 open 384차원 baseline의 cosine 2개는 비유한 값이어서 숫자로 치환하지 않고 JSON null로 기록했으며 핵심 구조화 모델 선택에는 사용하지 않았다.

### Phase 8 — 외부 MLLM-Fabric 전이

MLLM-Fabric RGB 이미지 220개를 Amazon target과 합치지 않고 별도 외부 평가로 사용했다.

- recoverability calibration: 110개
- external test: 110개
- 호환 축: softness, surface texture, elasticity, thickness
- 비호환 또는 모델 미지원: flexibility, warmth
- Leeds: 원시 이미지+평점 배포본과 재배포 license를 확인하지 못해 실행하지 않음

### Phase 9 — 선택적 예측과 abstention

FashionCLIP Ridge bootstrap ensemble 20개로 instance uncertainty를 계산했다. instance confidence와 외부 property recoverability를 분리하여 다음 방법을 비교했다.

- confidence only
- recoverability only
- confidence × recoverability
- learned cross-axis logistic calibrator

threshold와 calibrator는 development에서만 맞추고 locked test의 관측 product-axis example 705개에서 평가했다.

### Phase 10 — review-cold-start retrieval

locked test에서 같은 category의 후보가 최소 30개이고 hidden review target support가 있는 경우에만 query를 구성했다.

- query: 10개
- single-axis query: 10개
- multi-axis query: 0개
- 후보의 review pseudo-target은 relevance 평가에만 사용
- 이전 v1보다 후보군을 크게 만들어 더 어려운 검색으로 변경

### Phase 11 — 통합 결과와 재현 검증

- 최종 manifest: complete
- unit test: 23 / 23 통과
- JSON/JSONL 비유한 scalar: 0개
- family split과 leakage test 통과
- 상세 Notion-ready 보고서와 machine-readable artifact 생성

## 8. Phase 3 축 구성과 실제 결과

아래 통계는 전체 dataset이 아니라 축 선택에 사용한 train 영역의 결과다.

| 축 | pole | mapped span | 상품 | 2명 이상 reviewer 상품 | REVIEW_UNOBSERVED | pole별 상품 | 결정 |
|---|---|---:|---:|---:|---:|---|:---:|
| softness | soft ↔ firm | 488 | 476 | 12 | 92.4% | soft 422 / firm 55 | ACTIVE |
| surface texture | smooth ↔ rough | 160 | 152 | 8 | 97.6% | smooth 66 / rough 86 | ACTIVE |
| elasticity | non-elastic ↔ elastic | 2,001 | 1,928 | 73 | 69.4% | non-elastic 1,468 / elastic 459 | ACTIVE |
| thickness | thin ↔ thick | 1,167 | 1,139 | 28 | 81.9% | thin 718 / thick 417 | ACTIVE |
| flexibility | flexible ↔ stiff | 98 | 91 | 7 | 98.6% | flexible 31 / stiff 60 | ACTIVE |
| warmth | warm ↔ cool | 317 | 293 | 24 | 95.3% | warm 167 / cool 139 | ACTIVE |
| sponginess | spongy ↔ crisp | 2 | 2 | 0 | 약 100% | spongy 0 / crisp 2 | INACTIVE |

최종 active axes는 다음 6개다.

`softness, surface_texture, elasticity, thickness, flexibility, warmth`

sponginess는 span, product, pole balance, multi-reviewer support가 모두 부족해 inactive다.

다시 강조하면 ACTIVE는 “리뷰에서 학습 target을 구성할 최소 조건을 통과했다”는 뜻이다. 이미지에서 잘 예측된다는 의미가 아니다.

## 9. 이미지 기반 축 예측 결과

Spearman은 상품의 상대적인 촉감 순서를 얼마나 잘 맞췄는지를 나타낸다. 1에 가까울수록 좋고, 0은 순서 관계가 거의 없으며 음수는 반대 경향을 뜻한다.

아래는 locked family test 결과다. v2는 한 split seed만 사용했으므로 표준편차 0은 안정성이 완벽하다는 뜻이 아니라 seed 반복이 없다는 뜻이다.

| 방법 | softness | surface texture | elasticity | thickness | flexibility | warmth |
|---|---:|---:|---:|---:|---:|---:|
| category-only | .071 | .396 | .328 | .086 | -.297 | -.009 |
| FashionCLIP linear | .024 | -.040 | .340 | .251 | .018 | -.161 |
| FashionCLIP Ridge | .071 | -.066 | .356 | **.322** | .092 | -.110 |
| image+category Ridge | .079 | -.093 | **.364** | .318 | .129 | -.087 |
| DINO Ridge | -.058 | -.423 | .357 | .249 | .314 | -.069 |
| ordinal | **.089** | -.026 | .260 | .264 | .092 | .018 |
| pairwise | .046 | -.053 | .192 | .241 | .092 | .018 |
| tiny MLP | .019 | **.040** | .327 | .303 | **.351** | **.060** |

축별 locked test 관측 표본은 다음과 같다.

| 축 | test product-axis example |
|---|---:|
| softness | 75 |
| surface texture | 23 |
| elasticity | 345 |
| thickness | 209 |
| flexibility | 14 |
| warmth | 39 |

### 축별 해석

#### Thickness

가장 안정적인 긍정 결과다. category-only .086에 비해 FashionCLIP Ridge .322, image+category Ridge .318, tiny MLP .303으로 개선됐다. 이미지에서 두께와 관련된 시각 신호가 존재할 가능성이 가장 크다.

#### Elasticity

category-only .328도 강하지만 image+category Ridge .364, DINO Ridge .357, FashionCLIP Ridge .356으로 소폭 개선됐다. 이미지 신호는 있으나 category shortcut을 크게 넘어섰다고 보기는 어렵다.

#### Softness

최고 결과가 ordinal .089로 매우 약하다. 전체 데이터가 늘었어도 softness를 일반 상품 이미지 한 장에서 읽는 것은 여전히 어렵다.

#### Surface texture

category-only가 .396인데 최고 이미지 모델은 tiny MLP .040이다. 이미지 모델 대부분은 음수다. 촉감 표면을 직접 읽기보다 상품 category가 target을 설명하는 shortcut이 강하다는 경고다.

#### Flexibility

tiny MLP .351, DINO Ridge .314로 좋아 보이지만 test example이 14개뿐이다. 탐색적 신호로만 보고 확정 결과로 사용하면 안 된다.

#### Warmth

최고 Spearman이 .060이고 여러 이미지 모델은 음수다. 현재 이미지 기반 warmth 예측은 약하다.

## 10. 외부 MLLM-Fabric 결과

Pairwise accuracy의 무작위 기준은 약 .5다.

| 축 | external Spearman | pairwise accuracy | calibration recoverability | 해석 |
|---|---:|---:|---:|---|
| softness | .002 | .501 | .095 | 거의 무작위 |
| surface texture | .318 | .654 | .339 | 가장 강한 외부 신호 |
| elasticity | .119 | .581 | .083 | 약한 양의 전이 |
| thickness | .190 | .603 | .283 | 의미 있는 탐색적 전이 |
| flexibility | — | — | — | 외부 property와 직접 호환되지 않음 |
| warmth | — | — | — | 외부 property와 직접 호환되지 않음 |

softness는 여전히 외부에서 거의 무작위다. surface texture는 Amazon 내부 이미지 모델에서는 category shortcut 문제가 크지만 MLLM-Fabric의 통제된 RGB textile 이미지에서는 상대적으로 강한 결과가 나왔다. 이는 상품 이미지의 촬영 조건과 소재 확대 정도가 중요할 가능성을 시사한다.

## 11. 선택적 예측 결과

AURC는 모델이 자신 있는 예측부터 남겼을 때 coverage 전체에서 발생하는 오류를 요약하며 낮을수록 좋다.

| 방법 | test example | AURC↓ | full coverage MAE | nominal 80% 실제 coverage | 해당 MAE↓ |
|---|---:|---:|---:|---:|---:|
| confidence only | 705 | **.601** | .693 | .776 | .659 |
| recoverability only | 705 | .763 | .693 | .925 | .672 |
| confidence × recoverability | 705 | .717 | .693 | .806 | .670 |
| learned calibrator | 705 | .621 | .693 | .773 | **.648** |

해석은 두 부분으로 나눠야 한다.

1. learned calibrator는 약 77%만 예측할 때 MAE를 `.693 → .648`로 줄였다. 따라서 자신 없는 예측을 일부 거절하면 남은 예측의 평균 오류가 줄어든다는 신호는 있다.
2. coverage 전체를 요약한 AURC에서는 단순 confidence-only `.601`이 learned calibrator `.621`보다 좋다. 따라서 복잡한 calibrator가 항상 단순 confidence보다 낫다는 주장은 지지되지 않는다.

## 12. review-cold-start retrieval 결과

NDCG@10은 상위 10개 검색 순위의 품질이며 높을수록 좋다.

| 방법 | NDCG@10 |
|---|---:|
| random | .567 |
| category-only | .504 |
| FashionCLIP taxonomy zero-shot | .535 |
| structured no abstention | **.656** |
| confidence selective U0 | .616 |
| recoverability selective U0 | .656 |
| confidence × recoverability U0 | .627 |
| proposed calibrator U0 | .642 |
| proposed calibrator U1 | .635 |
| proposed UNKNOWN coverage U2 | .635 |

현재 결과에서는 structured no-abstention이 random과 category-only보다 높다. v1에서 random이 가장 높았던 문제는 후보를 최소 30개로 늘리면서 완화됐다.

그러나 query가 10개뿐이고 multi-axis query가 0개다. 또한 proposed calibrator/UNKNOWN ranking이 structured no-abstention보다 낮다. 따라서 **구조화 촉감 score에 검색 신호가 있다는 탐색적 결과**는 있지만, **abstention이 검색 순위를 개선한다는 주장은 v2에서 재현되지 않았다.**

bootstrap confidence interval도 넓으므로 검색 결과를 확정적 성능 차이로 해석하면 안 된다.

## 13. v1과 비교해 무엇이 달라졌나

| 항목 | v1 | v2 full-pool | 의미 |
|---|---|---|---|
| 시작 범위 | 약 500개 ASIN, 465 family | 8,498 ASIN, 7,365 family | 표본 실험에서 전체 적격 풀로 확대 |
| 선택 리뷰 | 4,158 | 70,943 | 데이터 다양성 증가 |
| primary target | 방향 × intensity | direction-only -1/0/+1 | v1 intensity 불안정 반영 |
| active axis | 4개 | 6개 | 외부 availability와 내부 feasibility 분리 |
| test split | 3개 feasibility seed 평균 | v1-unseen family locked test 1개 | test 독립성 강화, seed 반복은 감소 |
| 관측 pair 비율 | 44.6% | 10.8% | 규모는 늘었지만 축별 label 밀도 감소 |
| 강한 축 | elasticity, thickness | elasticity, thickness | 핵심 경향 반복 |
| learned calibrator AURC | confidence보다 우수 | confidence보다 약간 낮음 | 복잡한 calibrator 우위는 미재현 |
| retrieval | random이 가장 높음 | structured가 random보다 높음 | benchmark 난이도 개선 신호 |
| UNKNOWN ranking | forced보다 개선 | forced보다 낮음 | 검색 abstention 효과는 미재현 |

가장 쉬운 비유는 다음과 같다.

> v1은 소수 상품을 여러 번 자세히 관찰한 작은 교실 실험이고, v2는 도시 전체 상품을 한 번씩 넓게 조사한 전수조사다. v2는 전체 경향과 새 family 일반화를 확인하기에 더 좋지만, 한 상품에 대한 다중 reviewer와 다중 축 라벨의 깊이는 부족하다.

## 14. 이번 실험에서 가장 주목해야 할 결론

### 14.1 두께가 가장 일관된 후속 연구 축이다

두께는 category-only를 넘어서는 이미지 모델 성능이 있고 외부 MLLM-Fabric에서도 pairwise .603을 보였다. 현재 가장 재현성이 높은 축이다.

### 14.2 탄성도 유망하지만 category shortcut 통제가 필요하다

탄성은 내부와 외부 모두 양의 신호가 있지만 category-only도 이미 .328로 높다. 같은 category 안의 hard negative나 category residual target을 사용해야 실제 소재 신호인지 확인할 수 있다.

### 14.3 surface texture는 촬영 조건에 매우 민감할 가능성이 있다

Amazon 상품 이미지에서는 category-only보다 훨씬 나쁘지만, 통제된 외부 textile RGB에서는 가장 강한 외부 결과가 나왔다. 확대 소재 이미지, crop, multi-view가 필요할 수 있다.

### 14.4 전체 풀 확장은 label sparsity 문제를 해결하지 않았다

관측 product-axis pair 비율이 10.8%다. 대표 축 1개 중심의 scaling 정책 때문에 한 상품의 모든 촉감 축이 관측되지 않는다. 다음 실험에서는 전수 상품 풀을 유지하되 한 상품당 여러 reviewer와 여러 축을 보존해야 한다.

### 14.5 abstention은 예측 오류에는 도움 신호가 있지만 검색 개선은 미확정이다

선택적 예측에서는 일부 거절 시 MAE가 감소했다. 그러나 AURC에서는 confidence-only가 더 좋고 retrieval에서는 no-abstention이 더 높았다. 예측 calibration과 ranking UNKNOWN 정책을 별개로 다시 설계해야 한다.

## 15. 주장할 수 있는 것

- 500개 상한 없이 전체 적격 ASIN 8,498개에서 Phase 0~11 파이프라인을 실행했다.
- parent family 단위로 train/development/test를 분리하고 기존 v1 family를 train에 격리했다.
- 리뷰 미언급과 neutral을 분리한 sparse reviewer-first target을 만들었다.
- 리뷰 기준으로 6개 active axis를 식별했다.
- thickness와 elasticity에서 category-only를 일부 넘어서는 이미지 순위 신호가 관측됐다.
- MLLM-Fabric에서 surface texture, elasticity, thickness의 탐색적 외부 전이 신호가 관측됐다.
- 일부 예측을 abstain했을 때 남은 예측의 MAE가 감소했다.
- 더 어려운 retrieval 후보군에서 structured score가 random/category-only보다 높았다.

## 16. 아직 주장하면 안 되는 것

- Qwen pseudo-label이 사람 수준으로 정확하다.
- 이미지가 실제 물리적 촉감을 정확히 예측한다.
- 모든 active axis가 시각적으로 recoverable하다.
- flexibility .351이 안정적인 성능이다. test example이 14개뿐이다.
- learned calibrator가 단순 confidence보다 항상 우수하다.
- UNKNOWN-aware ranking이 검색 품질을 개선한다.
- 10개 retrieval query 결과가 일반적인 쇼핑 검색 성능을 대표한다.
- Amazon에서 얻은 관계가 모든 외부 촉감 데이터에 일반화된다.
- 리뷰에서 언급되지 않은 축이 neutral이다.

## 17. 남은 한계

1. 사람 audit이 완료되지 않아 axis confusion, polarity, scope 정확도가 미확정이다.
2. lexical candidate miner가 키워드가 없는 우회적 촉감 표현을 놓칠 수 있다.
3. 대표 축 1개 중심의 Qwen scaling 때문에 product-axis target이 89.2% 미관측이다.
4. softness, surface texture, flexibility, warmth의 locked test 관측 수가 작다.
5. split seed가 하나라 seed 변화에 따른 안정성을 평가하지 못했다.
6. Amazon 상품 이미지는 소재 확대 이미지가 아니므로 미세 surface texture가 보이지 않을 수 있다.
7. category shortcut이 강하다.
8. 외부 MLLM-Fabric은 220개로 작고 4개 축만 직접 호환된다.
9. Leeds 외부 검증은 실행 가능한 원시 데이터와 license 확인 후 추가해야 한다.
10. retrieval query가 10개이고 multi-axis query가 없다.

## 18. 다음 실험 우선순위

1. **human audit 완성**  
   pending 600개 표본에서 mappability, axis, direction, scope 정확도와 사람 간 일치도를 계산한다.

2. **전수 풀은 유지하고 label density 확대**  
   ASIN당 대표 축 하나만 남기지 않고 여러 reviewer와 여러 축을 보존한다. 특히 softness, surface texture, flexibility, warmth의 다중 reviewer support를 늘린다.

3. **thickness와 elasticity 우선 검증**  
   현재 가장 반복성이 높은 두 축을 별도 frozen primary endpoint로 설정한다.

4. **category shortcut 통제**  
   within-category hard negative, category-balanced evaluation, category residual target을 적용한다.

5. **소재 중심 이미지 입력 추가**  
   전체 상품 이미지 외에 fabric crop, 확대 이미지, multi-view를 사용해 surface texture와 softness를 재검증한다.

6. **다중 seed locked family 평가**  
   v2의 큰 pool을 유지하면서 3개 이상의 family split seed로 반복한다.

7. **retrieval query 확대**  
   single-axis와 multi-axis query를 사전에 충분히 확보하고 최소 후보 수 30 이상을 유지한다.

8. **abstention 재설계**  
   예측 오류 감소용 confidence와 ranking용 UNKNOWN penalty를 분리해 평가한다.

## 19. 지표를 쉽게 읽는 방법

| 지표 | 쉬운 의미 | 좋은 방향 |
|---|---|---|
| Spearman | 상품의 촉감 순서를 얼마나 잘 맞췄는가 | 높을수록 좋음 |
| MAE | 예측값이 target에서 평균적으로 얼마나 벗어났는가 | 낮을수록 좋음 |
| Pairwise accuracy | 두 상품 중 어느 쪽이 positive pole 방향인지 맞힌 비율 | .5가 무작위, 높을수록 좋음 |
| AURC | 자신 있는 예측부터 남겼을 때 coverage 전반의 오류 | 낮을수록 좋음 |
| Coverage | 전체 중 모델이 실제 답한 비율 | 높음이 항상 좋은 것은 아님 |
| NDCG@10 | 상위 10개 검색 결과의 순위 품질 | 높을수록 좋음 |
| Recoverability | 해당 축을 외부 이미지에서 시각적으로 회수할 가능성 | 높을수록 좋지만 ground truth 정확도와 동일하지 않음 |

## 20. 주요 결과 파일

- 최종 설명 문서: `/home/user/onsesang/material_span_grounding/tactile_coldstart_qwen_v2_full/notion/TACTILE_COLDSTART_V2_FULL_PHASE_0_TO_11.md`
- Phase 3 축 문서: `/home/user/onsesang/material_span_grounding/tactile_coldstart_qwen_v2_full/notion/PHASE_3_TACTILE_AXIS_FEASIBILITY.md`
- 전체 풀 manifest: `/home/user/onsesang/material_span_grounding/tactile_coldstart_qwen_v2_full/manifests/phase0_full_pool.json`
- Qwen grounding manifest: `/home/user/onsesang/material_span_grounding/tactile_coldstart_qwen_v2_full/manifests/phase2_axis_grounding.json`
- 축 통계: `/home/user/onsesang/material_span_grounding/tactile_coldstart_qwen_v2_full/artifacts/tactile_axis_stats.json`
- 모델 결과: `/home/user/onsesang/material_span_grounding/tactile_coldstart_qwen_v2_full/artifacts/phase6_7_model_results.json`
- 외부 전이 결과: `/home/user/onsesang/material_span_grounding/tactile_coldstart_qwen_v2_full/artifacts/external_transfer_results.json`
- 선택적 예측 결과: `/home/user/onsesang/material_span_grounding/tactile_coldstart_qwen_v2_full/artifacts/phase9_selective_results.json`
- retrieval 결과: `/home/user/onsesang/material_span_grounding/tactile_coldstart_qwen_v2_full/artifacts/phase10_retrieval_results.json`
- 최종 manifest: `/home/user/onsesang/material_span_grounding/tactile_coldstart_qwen_v2_full/manifests/phase11_final.json`

## 21. GPT에게 요청할 응답 방식

이 문서를 받은 GPT는 질문에 따라 다음 순서로 답한다.

1. 한두 문장으로 쉬운 결론
2. 결론을 뒷받침하는 핵심 수치
3. 수치의 해석 한계
4. 실제 의사결정 또는 다음 실험에 주는 의미

답변에서 결과를 과장하지 말고 다음 표현을 우선 사용한다.

- “현재 데이터에서 관측됐다.”
- “탐색적 신호다.”
- “category shortcut을 통제한 추가 검증이 필요하다.”
- “사람 검증 전의 pseudo-label 기반 결과다.”
- “v1에서 보인 결과가 v2에서 재현됐다/재현되지 않았다.”

다음 표현은 human audit과 추가 실험 전에는 사용하지 않는다.

- “이미지가 실제 촉감을 정확히 안다.”
- “사람 수준의 촉감 정답이다.”
- “모든 상품에 일반화된다.”
- “제안 방법이 최종적으로 우수함이 입증됐다.”
