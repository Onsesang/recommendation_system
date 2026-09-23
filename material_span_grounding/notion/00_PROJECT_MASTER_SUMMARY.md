# 이미지 기반 소재 추천을 위한 Open-vocabulary 리뷰 Grounding 프로젝트

> 기준일: 2026-08-10  
> 프로젝트 경로: `/home/user/onsesang/material_span_grounding`  
> 현재 상태: RECALL V2 100-span 사람 검수와 GNN 이전 M0/M1 단순 실험 완료  
> 데이터 원칙: train split만 사용, protected test 미사용

---

## 1. 프로젝트 한 줄 요약

상품 리뷰에서 고정 소재 class 없이 실제 소재·질감 표현을 exact quote로 수집하고, 이미지가
그 리뷰 공간을 예측하도록 학습한 뒤, 유사 상품의 실제 리뷰 안에서만 소재 설명을 생성하는
추천 시스템을 만든다.

핵심 연구 질문은 다음과 같다.

> 기성 이미지 임베딩을 그대로 사용할 때보다, 실제 사용자 소재 리뷰로 이미지 표현을
> 학습했을 때 같은 의류 종류 안에서도 소재 차이를 더 잘 검색하고 설명할 수 있는가?

---

## 2. 문제 정의

일반적인 의류 검색 임베딩은 카테고리, 색상, 실루엣처럼 이미지에서 두드러지는 특징을 잘
찾지만, 사용자가 실제로 궁금해하는 다음 정보는 충분히 표현하지 못할 수 있다.

- 부드러움, 까끌함, 뻣뻣함
- 두께, 무게, 비침
- 신축성과 회복성
- 통기성, 보온성, 땀 흡수
- 드레이프와 형태 유지
- 세탁 후 수축, 보풀, 늘어남, 변형
- 안감이나 특정 부위의 소재 특성
- 피부 자극과 착용 중 소재 반응

이 프로젝트는 이를 고정 taxonomy 분류 문제로 만들지 않는다. 리뷰가 실제로 사용하는
자유 표현을 보존하고, 이미지와 리뷰의 관계를 벡터 공간에서 학습하는 open-vocabulary
grounding 문제로 정의한다.

---

## 3. 최종 시스템의 전체 파이프라인

```text
[Train-only 상품·리뷰]
        │
        ▼
[1] 리뷰 전체에서 소재 exact span 수집
    - Qwen recall extraction
    - 원문 exact substring 검사
        │
        ▼
[2] 소재 여부 및 의미 구조화
    - Qwen semantic verification
    - claim, scope, polarity, intensity, evidence, visuality
        │
        ▼
[3] 사람 검수
    - Good / Bad / Edit
    - 같은 리뷰의 모든 sibling span 확인
    - Add Missing Span
    - Full Review Checked
        │
        ▼
[4] 리뷰·claim 정제
    - 동일 사용자 반복 제거
    - semantic deduplication
    - polarity 보존
    - 사용자 수·합의도·confidence 계산
        │
        ▼
[5] 텍스트/리뷰/상품 공간 구성
    Claim → Review → Product
    weighted mean / set encoder / GNN 비교
        │
        ▼
[6] 이미지 모델 학습 M1~M5
    이미지 → 리뷰·상품 target 또는 관계·순위 예측
        │
        ▼
[7] 소재 검색 평가
    같은 카테고리 안에서 다른 소재를 구분하는지 측정
        │
        ▼
[8] 추천 및 접지 생성
    질의 이미지 → 유사 상품 → 실제 리뷰 근거
    → LLM이 검색된 근거 안에서만 소재 설명
```

---

## 4. 기본 연구 가설

### H1. Domain grounding 가설

리뷰 소재 공간을 학습한 이미지 임베딩은 동결된 Qwen/CLIP 이미지 임베딩보다 소재 기반
검색 성능이 높다.

### H2. Category shortcut 방지 가설

성능 향상이 단순히 의류 종류를 더 잘 맞힌 결과가 아니라, 같은 카테고리 안의 서로 다른
두께·질감·신축성 등을 구분한 결과여야 한다.

### H3. Review-complete grounding 가설

한 리뷰나 대표 문장만 사용하는 것보다, 중복과 사용자 편향을 제거한 여러 review/claim을
사용하는 것이 상품 소재 표현을 더 안정적으로 만든다.

### H4. Grounded generation 가설

이미지에서 소재 설명을 직접 생성하는 것보다, 유사 상품의 실제 리뷰를 검색한 뒤 근거
범위 안에서만 생성하면 환각을 줄이고 설명의 추적 가능성을 높일 수 있다.

---

## 5. 데이터와 누수 통제

### 현재 pilot

| 항목 | 값 |
|---|---:|
| 리뷰 | 1,000개 |
| 상품 | 931개 |
| 고유 사용자 | 999명 |
| 상품당 최대 리뷰 | 2개 |
| split | train only |
| protected test | 미사용 |

표본은 seed 42와 SHA-256 기반으로 결정적으로 선택했다. 상품당 최대 2개 리뷰만 pilot에
포함해 리뷰가 많은 일부 상품이 초기 실험을 지배하지 않도록 했다.

이 제한은 추출·검수 prompt를 개발하기 위한 pilot 설계이며, 최종 상품 공간에서는 한
상품의 유효한 전체 리뷰를 사용해야 한다.

---

## 6. Stage 1 — 소재 exact span 추출

### 목적

리뷰에서 소재에 관한 표현을 요약하거나 정규화하지 않고 원문 그대로 복사한다.

예시:

```text
Review:
"The fabric is thick but not see-through."

Exact evidence:
- "The fabric is thick"
- "not see-through"
```

### v1 규칙

- 고정 소재 label을 출력하지 않는다.
- `not`, `very`, `slightly`, 비교 표현, 세탁 조건을 보존한다.
- 소재와 무관한 배송·가격·색상·핏은 제외한다.
- 모든 quote는 코드로 원문 exact substring 여부를 검사한다.
- 리뷰 하나에서 최대 10개 후보를 허용했다.

### v1 자동 결과

| 지표 | 결과 |
|---|---:|
| evidence가 1개 이상인 리뷰 | 406 / 1,000 (40.6%) |
| 유효 exact span | 669개 |
| 반환 후보 | 698개 |
| 원문 불일치 | 29개 |
| exact quote 유효율 | 95.8% |
| 고유 quote 문자열 | 564개 |
| 리뷰당 평균 span | 0.669개 |
| 리뷰당 중앙값 | 0개 |

### v1 해석

exact quote 유효율은 높았지만 이는 의미 정확도나 recall을 뜻하지 않는다. Qwen이 원문을
정확히 복사했는지는 알 수 있지만, 소재가 아닌 표현을 뽑았는지 또는 리뷰의 다른 소재
표현을 놓쳤는지는 별도 검증이 필요하다.

---

## 7. Stage 2 — 소재 의미 검증과 구조화

각 exact span을 원문 리뷰와 함께 다시 Qwen에 입력해 소재 근거인지 판정하고 다음 정보를
구조화했다.

| 필드 | 의미 |
|---|---|
| `claim` | 문맥을 보존한 짧은 자유 텍스트 소재 주장 |
| `scope` | main fabric, lining, component, whole garment 등 |
| `property_status` | present, absent, comparative, uncertain, mixed |
| `intensity` | none, slight, moderate, strong, unknown |
| `sentiment` | positive, negative, neutral, mixed, unknown |
| `evidence_basis` | touch, worn experience, visual, product behavior 등 |
| `visual_observability` | high, medium, low, unknown |

### v1.1 자동 결과

| 지표 | 결과 |
|---|---:|
| 입력 span | 669개 |
| schema 검증 성공 | 669개 |
| Qwen accepted | 630개 |
| Qwen rejected | 39개 |
| 자동 acceptance rate | 94.2% |

94.2%는 Qwen의 자체 채택률이지 사람 기준 precision이 아니다. 1차와 2차가 같은 Qwen
계열이므로 오류가 상관될 수 있고, 사람 검수가 필수다.

---

## 8. Stage 3 — 사람 검수 설계

### 최초 v1 audit 표본

- Qwen accepted 중 결정적 표본 100개
- Qwen rejected 39개 전체
- 총 139 span
- 119개 상품, 120개 리뷰

### 검수 UI 기능

- 상품 고해상도 이미지
- Extracted Span과 Full Review 동시 표시
- Qwen normalized claim과 metadata
- Good, Bad, Edit, Reset
- Previous, Good & Next, 방향키 이동
- 같은 span을 다시 검토하면 최신 판정으로 원자적 덮어쓰기
- Add Missing Span 추가·수정·삭제
- 서버 exact quote 검사
- Full Review Checked 상태
- Judgment, Missing, Recall CSV 분리 내보내기
- 새 v2에서는 같은 리뷰의 모든 sibling span을 한 화면에서 표시
- `New V2` 필터로 새 수집 후보만 우선 검토

### 현재 사람 검수 상태

| 항목 | 현재 값 |
|---|---:|
| 완료 | 21 / 139 |
| Qwen accepted 표본 검수 | 21개 |
| Qwen rejected 표본 검수 | 0개 |
| Human accepted | 21개 |
| Human rejected | 0개 |
| Annotator | 2명 |

현재 21개에서는 모두 일치했지만 표본이 작고 rejected 표본을 아직 검토하지 않았으므로
Qwen precision이나 false-negative rate가 좋다고 결론 내릴 수 없다. Wilson 95% 구간도
약 84.5%~100%로 넓다.

### 품질 gate

중간 판정은 다음 최소 표본 이후에만 사용한다.

| 조건 | 최소값 |
|---|---:|
| 전체 사람 라벨 | 50개 |
| Qwen accepted 라벨 | 30개 |
| Qwen rejected 라벨 | 15개 |
| metadata 비교쌍 | 25개 |

최종 목표:

| 지표 | 기준 |
|---|---:|
| Accepted precision | 90% 이상 |
| Rejected false-negative rate | 15% 이하 |
| Scope agreement | 90% 이상 |
| Property-status agreement | 90% 이상 |
| Visual-observability agreement | 80% 이상 |

---

## 9. 누락 문제 분석과 중요한 정정

검수 중 다음 리뷰에서 수축 span만 화면에 보여 두께와 단단함이 누락된 것으로 보였다.

```text
These are the thickest fabric masks I've gotten so far.
The firmer material creates an open pocketing in front of my mouth.
They shrank a little the first time but still fit.
```

원시 추출 결과를 역추적한 결과, Qwen v1은 실제로 세 표현을 모두 추출했고 semantic
verification도 세 개 모두 accepted했다.

문제는 두 가지였다.

1. 기존 UI가 한 리뷰의 span을 별도 Item으로 분리해 현재 span 하나만 강조했다.
2. span 단위 audit 표본을 만들면서 같은 리뷰의 일부 sibling span이 표본 밖으로 빠졌다.

따라서 이 사례 자체는 Stage 1 추출 누락이 아니라 **audit sampling과 UI 가시성 문제**다.
하지만 139개 audit은 추출된 span의 precision 중심 표본이라 corpus recall을 측정하지
못한다는 문제는 여전히 존재한다.

### 반영한 수정

- 같은 리뷰의 모든 extracted sibling span을 한 화면에 표시
- 선택한 audit 리뷰는 v2에서 모든 후보 span을 함께 포함
- 실제 누락은 기존 span을 바꾸지 않고 Add Missing Span으로 별도 보존
- 리뷰 전체를 확인했는지 Full Review Checked로 기록
- 추출 span이 0개였으나 v2가 새로 찾은 리뷰도 audit cohort에 추가

---

## 10. Recall 중심 재수집 v2

### 설계 원칙

v2는 기존 결과를 폐기하지 않는다.

```text
v2 union = v1 exact spans
         ∪ surface/use lens 결과
         ∪ behavior/care lens 결과
```

### Lens 1 — Surface / Use

- 소재 정체성
- 촉감과 표면
- 두께, 무게, 비침, 직조와 광택
- 신축, 회복, 드레이프, 형태 유지
- 보온, 통기, 수분 반응
- 피부 자극과 착용 반응

### Lens 2 — Behavior / Care

- 세탁과 건조
- 수축과 늘어남
- 보풀, 털 빠짐, 찢어짐, 풀림
- 주름, 말림, 형태 변화
- 흡수, 땀, 건조 속도
- 시간 경과에 따른 소재 변화

두 checklist는 고정 output class가 아니라 Qwen이 리뷰 전체를 다시 훑게 하는 attention
lens다. 최종 출력은 계속 open-vocabulary exact quote다.

### v2 추가 보완

- Qwen이 `[{"quote": ...}]` 대신 문자열 배열을 반환해도, 문자열이 exact substring이면
  안전하게 수용한다.
- v1 quote와 포함 관계인 짧은 v2 quote는 새 검수 항목으로 늘리지 않고 동일 근거로 병합한다.
- v1 판단은 재사용하고 신규 span만 semantic verification해 GPU 비용을 줄인다.
- 새 후보의 fit·construction false positive는 2차 verifier에서 제거한다.

### v2 smoke test

13개 리뷰에서 형식 보완과 포함 중복 제거 후 다음 변화가 나타났다.

| 항목 | v1 | v2 union |
|---|---:|---:|
| span | 7 | 13 |
| evidence가 있는 리뷰 | 4 | 6 |

새로 찾은 예:

- `they do stretch very well`
- `after just one wash on the delicate cycle it is already coming undone`
- `One of the pockets came undone at the stitch`

### 전체 재수집 최종 결과

동일한 train-only 1,000개 리뷰에서 두 lens 2,000개 작업을 모두 완료했다.

| 항목 | 최종 값 |
|---|---:|
| 완료 lens task | 2,000 / 2,000 (100%) |
| 대상 리뷰 | 1,000개 |
| v1 span | 669개 |
| v2 deduplicated union | 898개 |
| 후보 증가 | +229개 (+34.2%) |
| v1 evidence 리뷰 | 406개 |
| v2 evidence 리뷰 | 468개 |
| v1 0개에서 회복된 리뷰 | 62개 |

추출 단계에서 1,973개 lens task는 완전 성공, 27개는 일부 invalid quote를 제거한 뒤 exact
quote만 보존했다. 최종 898개 후보는 모두 semantic verification schema를 통과했다.

| 의미 검증 항목 | 결과 |
|---|---:|
| 전체 후보 | 898개 |
| 재사용한 v1 판단 | 669개 |
| 신규 검증 후보 | 229개 |
| 신규 Qwen accepted | 157개 |
| 신규 Qwen rejected | 72개 |
| 신규 Qwen acceptance rate | 68.6% |

최초 RECALL V2 검수 pool은 기존 audit 120개 리뷰와 v1 0건에서 회복된 30개 리뷰를 합친
150개 리뷰, 342개 후보였다. 수동 검수 부담을 줄이기 위해 2026-08-09에 활성 검수 세트를
정확히 100개 span으로 축소했다. 단순히 앞 100개를 자르지 않고 리뷰 단위로 선택하여 같은
리뷰의 sibling을 모두 보존했다.

| 활성 100-span 검수 세트 | 개수 |
|---|---:|
| 리뷰 | 47개 |
| 기존 audit 리뷰의 span | 86개 |
| v1 0건에서 회복된 리뷰의 span | 14개 |
| New V2 span | 26개 |
| Qwen accepted | 80개 |
| Qwen rejected | 20개 |

표본 seed는 `20260809`로 고정했다. 342개 세트에서 먼저 기록했던 Good 5개·Edit 1개는
활성 세트에서 초기화했으며 복구 가능한 archive에 보존했다. 따라서 현재 100개 세트는
판정 0개에서 새로 시작한다. 기존 v1 사람 판정 21개도 별도 archive에 계속 보존한다.

후보 수 증가와 실제 recall 증가는 같지 않다. v2의 최종 효과는 새 후보의 사람 precision과
Full Review Checked 표본의 missing span 수를 함께 보고 판단한다.

---

## 11. Span 개수에 대한 판단 원칙

span은 많을수록 좋은 것이 아니다.

좋은 목표:

> 서로 다른 소재 정보를 빠짐없이 수집하되, 같은 의미를 반복해서 세지 않는다.

- 서로 다른 두께·단단함·수축은 별도 claim으로 보존한다.
- 같은 `부드럽다` 표현의 반복은 semantic deduplication한다.
- 부정과 비교를 긍정 claim과 합치지 않는다.
- 한 문장에 여러 속성이 있으면 source evidence는 공유할 수 있지만 atomic claim은 나눈다.
- 추천·학습 가중치로 원시 span 개수를 그대로 사용하지 않는다.

향후 권장 구조:

```text
Review
  └─ Evidence span
       ├─ Atomic claim A: thick
       ├─ Atomic claim B: firm
       └─ Atomic claim C: not breathable
```

현재 UI의 missing span schema는 기본적으로 한 quote에 한 claim이다. 한 exact sentence가
분리하기 어려운 여러 소재 속성을 포함할 경우 `Evidence → Claims` 1:N 구조로 확장하는 것이
향후 보완점이다.

---

## 12. 사람 검수 후 텍스트 target 생성

사람 검수가 성공하면 다음 순서로 리뷰 공간을 구성한다.

```text
accepted exact spans
→ atomic claim 분리
→ 동일 사용자 반복 제거
→ semantic duplicate 제거
→ polarity·scope 보존
→ 사용자 수와 합의도 계산
→ confidence·시각 관찰 가능성 가중
→ review embedding
→ product target embedding
```

### 한 상품에 리뷰가 여러 개일 때

대표 리뷰 하나를 고르지 않는다. 모든 유효 review/claim을 사용하되 다음 원칙으로 특정
사용자나 반복 표현의 과도한 영향을 막는다.

- 동일 사용자·동일 상품의 반복은 한 표로 제한
- 같은 의미의 반복은 semantic deduplication
- 상반되는 claim은 제거하지 않고 polarity를 보존
- 서로 다른 사용자 수와 합의도를 weight에 반영
- 이미지에서 관찰하기 어려운 속성은 학습 가중치를 낮추거나 별도 평가

단순 전체 평균은 반복 리뷰와 모순 표현을 뭉개므로 최종 기본값으로 사용하지 않는다.

---

## 13. 상품 리뷰 공간과 GNN 방향

리뷰를 node로 두는 GNN은 가능하지만, review node만 연결하면 배송·핏·색상 같은 비소재
정보가 섞이므로 claim node가 필요하다.

권장 이종 그래프:

```text
User ─writes→ Review ─about→ Product
                  │
                states
                  ▼
                Claim

Claim ─agrees_with→ Claim
Claim ─contradicts→ Claim
Claim ─similar_to→ Claim
```

### 후보 aggregation 비교

1. weighted mean
2. Deep Sets
3. Set Transformer
4. GraphSAGE
5. HGT

GNN 자체를 M6로 추가하기보다, 먼저 M1의 상품 target aggregation 방법을 위 다섯 가지로
비교한다. 가장 좋은 aggregation을 고정한 뒤 M1~M5 학습 목적을 비교해야 실험 축이 섞이지
않는다.

### 누수 주의

이미지 student가 예측할 target을 만드는 product graph teacher에 동일 이미지 임베딩을
넣으면 순환 누수가 생긴다. teacher target은 사용자·리뷰·claim 관계로만 구성하고 이미지는
student 입력으로만 사용한다.

---

## 14. 이미지 학습 실험 M1~M5

### M1. 리뷰 임베딩 회귀

이미지가 상품의 review/product target embedding을 직접 예측한다.

- 가장 단순하고 해석하기 쉬운 주 baseline
- 먼저 이 방법으로 target aggregation 비교

### M2. 관계 구조 증류

텍스트 상품 공간에서 상품 간 거리·이웃 구조를 이미지 공간이 보존하도록 학습한다.

- 절대 target보다 상대적 구조에 강할 수 있음
- teacher 관계 품질에 민감

### M3. M1 + M2 결합

target 회귀와 관계 구조 증류를 함께 사용한다.

- 절대 위치와 이웃 구조를 동시에 보존
- loss weight 조정 실험 필요

### M4. 확률적 임베딩 회귀

상품 소재 target을 하나의 점이 아니라 평균과 불확실성으로 예측한다.

- 리뷰 간 의견 충돌과 근거 부족을 표현 가능
- calibration과 uncertainty 평가 필요

### M5. 순위 학습

이미지가 정답 상품 또는 소재상 가까운 상품을 다른 상품보다 위에 놓도록 학습한다.

- 실제 retrieval 목적과 직접 정렬
- positive/negative 정의가 핵심

### 실험 순서 권장안

```text
1. 동결 Qwen/CLIP 검색 baseline
2. category-only baseline
3. M1 + weighted mean
4. M1에서 aggregation 비교
5. 선택된 aggregation으로 M2~M5 비교
6. 최고 방법의 ablation과 동일 카테고리 평가
```

M1~M5를 처음부터 모든 aggregation과 조합하면 실험 수가 폭발하고 원인을 해석하기 어렵다.

---

## 15. 대조학습의 negative 문제와 현재 방향

초기에는 같은 상품의 이미지·리뷰를 positive, 다른 상품을 negative로 하는 InfoNCE/CLIP
방식을 고려했다. 그러나 다른 상품이라고 해서 항상 소재가 다른 것은 아니다.

- 서로 다른 상품이 모두 `부드럽고 신축성 있음`일 수 있다.
- 이를 무조건 밀어내면 실제 소재 구조를 왜곡한다.
- 카테고리 차이를 소재 차이로 학습할 위험이 있다.

따라서 단순 instance contrastive learning만을 주 방법으로 두지 않고, review target 회귀,
관계 증류, 확률적 회귀, ranking을 비교하는 M1~M5 구조로 확장했다. 대조학습을 사용하더라도
semantic positive, graded similarity, hard negative와 category-controlled negative가 필요하다.

---

## 16. 검색·추천 시스템 반영안

### 검색 단계

```text
질의 상품 이미지
→ 소재 인식 image embedding
→ 동일/호환 카테고리 후보 안에서 material similarity 검색
→ 유사 상품과 실제 accepted review claims 반환
```

카테고리와 소재 검색은 분리하거나 hybrid score로 결합하는 것이 안전하다.

```text
final_score = α · category/shape similarity
            + β · material similarity
            + γ · evidence confidence
```

### 설명 생성 단계

LLM에는 검색된 실제 리뷰 evidence만 제공한다.

```text
근거:
- "도톰하다" — 사용자 4명
- "비치지 않는다" — 사용자 3명
- "약간 뻣뻣하다" — 사용자 2명

생성:
"구매자들은 도톰하고 비침이 적다고 평가했으며,
 일부는 약간 뻣뻣하다고 언급했습니다."
```

권장 안전장치:

- 근거 없는 속성 생성 금지
- claim별 인용 리뷰 ID와 사용자 수 보존
- 합의가 낮으면 `일부 구매자`, `의견이 엇갈림`으로 표현
- 이미지에서 보이지 않는 세탁·피부 반응은 검색 리뷰 근거임을 명시
- 추천 카드에 confidence와 evidence count 표시

---

## 17. 평가 설계

### Extraction

- exact quote validity
- human precision
- full-review span recall
- duplicate/redundancy rate
- atomicity
- zero-extraction review recovery

### Semantic verification

- accepted precision
- rejected false-negative rate
- scope agreement
- property-status agreement
- visual-observability agreement

### Embedding / Retrieval

- Recall@K, Precision@K, nDCG@K
- same-category material retrieval
- material claim neighbor agreement
- category-only baseline 대비 향상
- 새 상품과 long-tail 상품 성능

### Generation

- evidence faithfulness
- unsupported claim rate
- citation correctness
- 사용자 평가: 유용성, 구체성, 신뢰성

### Uncertainty

- 리뷰 수와 모델 confidence 관계
- 합의도와 예측 분산의 calibration
- 상충 claim이 있는 상품의 성능

---

## 18. 현재 검토할 점과 보완점

### 반드시 해결할 점

1. v2 신규 후보의 실제 사람 precision
2. Full Review Checked 표본의 실제 missing span 수
3. 추출 0개 리뷰를 포함한 별도 무작위 recall audit
4. 한 evidence span에서 여러 atomic claim을 표현하는 1:N schema
5. 동일 사용자 반복과 semantic duplicate 제거 기준
6. 상반된 리뷰를 평균으로 지우지 않는 polarity-aware aggregation
7. 이미지 관찰 가능성이 낮은 claim의 학습·평가 방식
8. category shortcut을 배제한 같은 카테고리 평가
9. 두 번째 annotator 독립 표본과 inter-annotator agreement

### 현재 확정하면 안 되는 주장

- Qwen accepted rate 94.2%가 사람 precision 94.2%라는 주장
- 후보 span 수 증가가 recall 개선을 증명한다는 주장
- 21개 일치만으로 prompt가 통과했다는 주장
- 현재 139개 표본만으로 corpus-wide recall을 계산했다는 주장
- GNN이 단순 weighted mean보다 반드시 좋다는 주장

---

## 19. 향후 실행 순서

### 완료된 즉시 작업

1. v2 1,000-review two-lens 재수집 완료
2. 신규 후보 229개 semantic verification 완료
3. v1 audit review의 모든 sibling span과 recovered review를 포함한 새 manifest 생성
4. v1 사람 판정 21개와 품질 산출물 archive 보존
5. 검수 서비스를 `RECALL V2` 데이터로 전환하고 API 상태 확인

### 사람 검수

1. `New V2` 필터로 신규 후보 precision 우선 확인
2. sibling 목록에서 기존 v1 근거와 중복 여부 확인
3. 리뷰 전체를 읽고 실제 누락만 Add Missing Span으로 추가
4. 모든 기존 후보를 판정한 뒤 Full Review Checked
5. 최소 quality gate 충족 후 prompt 수정 여부 결정

### 검수 통과 후

1. train 전체 리뷰에 동결 prompt 적용
2. 동일 사용자 반복 제거
3. semantic deduplication과 atomic claim 구성
4. weighted product target 생성
5. M1 baseline 및 aggregation 비교
6. M2~M5 비교
7. same-category retrieval과 grounded generation 평가

---

## 20. 주요 산출물 위치

### Prompt와 코드

| 경로 | 설명 |
|---|---|
| `prompts/span_extraction_v1.txt` | 최초 exact span prompt |
| `prompts/span_extraction_v2_surface.txt` | surface/use recall lens |
| `prompts/span_extraction_v2_behavior.txt` | behavior/care recall lens |
| `prompts/semantic_verification_v1_1.txt` | 의미 검증 prompt |
| `material_span/extract.py` | v1 추출과 exact quote parser |
| `material_span/extract_recall.py` | v2 two-lens union 추출 |
| `material_span/verify.py` | v1 의미 검증 |
| `material_span/verify_recall.py` | v2 신규 후보 의미 검증 |
| `material_span/human_audit.py` | 사람 품질 지표와 gate |

### 데이터와 실험

| 경로 | 설명 |
|---|---|
| `data/input/reviews_pilot.jsonl` | train-only 1,000 리뷰 |
| `data/output/span_extractions.jsonl` | v1 exact span |
| `data/output/semantic_verifications.jsonl` | v1 구조화 결과 |
| `data/v2/` | 완료된 recall v2 추출·검증 산출물 |
| `experiments/01_span_extraction/` | v1 추출 결과 |
| `experiments/02_semantic_verification/` | v1 의미 검증 결과 |
| `experiments/03_human_semantic_audit/` | 사람 검수 품질 상태 |
| `experiments/04_recall_extraction_v2/` | v2 최종 비교 결과와 예시 |

### 검수 앱

| 경로 | 설명 |
|---|---|
| `audit_app/server.py` | dependency-free backend |
| `audit_app/static/` | 검수 HTML/CSS/JavaScript |
| `audit_app/data/annotations.json` | v1 사람 판정 원본 |
| `audit_app/data/missing_spans.json` | v1 누락 span·review check |
| `audit_app/data/v2/` | 이전 342-span RECALL V2 검수 데이터 |
| `experiments/03_human_semantic_audit/archives/v1_before_recall_v2/` | v1 판정 21개 및 전환 직전 품질 산출물 |
| `audit_app/data/v2_100/` | 현재 활성화된 100-span 검수 세트 |
| `experiments/03_human_semantic_audit/archives/v2_342_cancelled_20260809/` | 취소한 342-span 세트와 기존 판정 6개 |

---

## 21. 최종 의사결정 기준

이 연구의 성공 기준은 span을 많이 생성하는 것이 아니다.

```text
좋은 extraction
= 높은 소재 coverage
+ 높은 사람 precision
- 의미 중복
- 카테고리·핏·배송 오염
```

```text
좋은 추천 시스템
= 같은 카테고리 안의 소재 구분 능력
+ 실제 리뷰에 근거한 설명
+ 불확실성과 사용자 합의 표현
- 근거 없는 소재 환각
```

최종적으로 학습 방식 1이 기성 임베딩 baseline보다 일관되게 우수하고, category-only
baseline을 넘어 같은 품목의 소재 차이를 구분하며, 생성 문장이 실제 리뷰 근거에 충실할
때 도메인 소재 grounding의 기여를 주장할 수 있다.

---

## 22. 2026-08-10 진행 결과 업데이트

### 사람 검수 완료

- RECALL V2 100/100 span 판정 완료
- Human accepted 76, rejected 24
- Qwen accepted precision 93.75%, 전체 decision accuracy 94.0%
- Full Review Checked 47/47, 사람이 추가한 missing span 0
- 단, recall 100%는 검수된 47개 리뷰 내부의 관측값이며 corpus-wide recall이 아님

### product-dense 데이터 준비

- 전체 2,500,939 리뷰 스캔
- train·이미지 조건 리뷰 152,878개
- 고유 사용자 5명 이상인 상품 8,498개
- 확장용 500상품·4,158리뷰 표본 준비
- 단순 실험용 100상품×서로 다른 사용자 5명, 총 500리뷰 표본 처리
- 375 exact span 중 Qwen semantic accepted 340개
- 최종 소재 target 89상품, 그중 다중 사용자 target 68상품

### M0/M1 핵심 결과

| 실험 | Material cosine@5 Δ | nDCG@5 Δ | Same-category cosine@5 Δ |
|---|---:|---:|---:|
| Sparse 438상품 | +0.0505 | +0.0477 | +0.0584 |
| Dense 89상품 only | +0.0038 | -0.0049 | -0.0049 |
| Sparse 학습 보조, dense 평가 | +0.0394 | +0.0192 | +0.0183 |

Sparse 실험의 nDCG@5와 same-category 지표는 95% CI가 0보다 컸다. 반면 dense 실험과
학습 보조 dense 실험은 모든 핵심 CI가 0을 포함했다. 따라서 M1은 유망한 baseline으로
유지하되 최종 우월성은 아직 주장하지 않는다.

M0는 정의를 바로잡아 원본 동결 Qwen feature에 L2 normalization만 적용했다. 개발
통계로 표준화한 이미지 baseline은 진단용으로만 분리했다.

상세 protocol, 수치, 한계, 재현 명령과 다음 의사결정 gate는
`notion/08_M0_M1_SIMPLE_EXPERIMENTS.md`에 정리했다.

## 23. 최신 권장 진행 순서

1. 현재 prompt·target·평가 protocol을 고정한다.
2. 이미 준비한 500상품·4,158리뷰 product-dense corpus를 추출·검증한다.
3. 별도 dense gold evaluation 150~300상품을 만든다.
4. M0 raw frozen과 M1 Ridge를 같은 category 안에서 다시 비교한다.
5. M1 개선이 반복되면 관계 구조 증류와 순위 학습을 진행한다.
6. GNN은 충분한 다중 사용자·관계 edge가 확보된 뒤 마지막에 비교한다.

---

## 24. 2026-08-13 시간순 추천 평가 환경

Amazon Fashion interaction 272,606개를 이용하는 offline ranking evaluator를 추가했다.

- 사용자별 시간순 train/validation/test
- test target 1개와 동일한 고정 negative 100개
- Recall@10, Hit Rate@10, nDCG@10, MRR, Precision@10, MAP@10
- TactileMatch@10과 profile/item coverage
- cold-start·long-tail·head item cohort
- sparse·medium·rich user-history cohort
- baseline 대비 paired bootstrap 95% CI

실제 평가 case는 332개다. 현재 소재 target coverage가 낮아 TactileMatch는
`insufficient_coverage`이며, tactile 결합의 ranking 개선도 아직 확인되지 않았다. 이는
평가 환경이 데이터 병목을 정상적으로 드러낸 결과다.

상세 protocol과 결과, BPR/CF 연결 계약은
`notion/11_OFFLINE_RECOMMENDATION_EVALUATION.md`에 정리했다. 최신 결과는 실행 중인
추천 backend의 `/api/evaluation`, `/api/evaluation/protocol`에서도 조회할 수 있다.

---

## 25. 2026-08-13 추천 프로토타입용 상품 소재 target

M0/M1 재평가는 건너뛰고 Recall v2.1 semantic accepted claim 4,527개로 상품 소재
target을 우선 생성했다. 500상품 중 495상품에 384차원 단위 벡터가 생성됐으며, 이 중
470상품은 서로 다른 사용자 2명 이상의 근거를 갖는다.

- target: `data/derived/dense_500_v2_1_targets/product_material_targets.npz`
- 상품 인덱스·통계: `data/derived/dense_500_v2_1_targets/products.json`
- 설명 근거: `data/derived/dense_500_v2_1_targets/evidence.jsonl`
- 생성 계약·해시: `data/derived/dense_500_v2_1_targets/manifest.json`

현재 산출물은 전체 리뷰를 집계한 추천 **프로토타입용**이다. 시간순 오프라인 성능을
보고할 때는 평가 시점 이후 리뷰가 target에 들어가지 않도록 time-aware target을 별도로
생성해야 한다. 상세 결과는 `notion/15_DENSE_500_V21_PRODUCT_TARGETS.md`에 정리했다.

---

## 26. 2026-08-13 Tactile-aware 추천 프로토타입 통합 완료

495상품 v2.1 target을 공통 backend로 연결해 상품 tactile 설명, concern, 비교, 대안,
일반 reranking, 자연어 Agent와 통합 demo UI를 구현했다. 기존 438상품 M0/M1 API는 회귀
호환성을 위해 유지했으며 이번 작업에서는 M0/M1을 재평가하지 않았다.

- Demo: `http://127.0.0.1:8877/tactile-demo`
- 신규 API: `/v1/tactile/*`, `/v1/products/*/tactile*`,
  `/v1/recommendations/tactile-*`
- 최종 자동 테스트: 94/94 통과
- live E2E 및 systemd service active 확인
- 시간순 332-case 4전략 ablation에서 Recall/NDCG 개선은 관찰되지 않음
- 주요 병목: test target coverage 5/332, candidate tactile coverage 3.25%

설명·comparison의 표시 evidence exact support는 100%, Agent intent fixture 5/5,
invented product는 0건이었다. 다만 독립 human label이 없는 concern precision과 alternative
relevance는 측정하지 못했으며, 현재 target이 time-aware가 아니므로 추천 수치는 진단용이다.

상세 결과는 `notion/16_TACTILE_RECOMMENDATION_PROTOTYPE.md`, 최종 설계·구현 보고서는
`docs/tactile/FINAL_REPORT.md`에 있다.
