# 논문 방향 결정을 위한 방법론 탐색 실험 계획

> 작성일: 2026-08-19  
> 목적: 졸업프로젝트 완성 전에 짧은 탐색 실험을 수행해 4-page Short Paper의 핵심 연구 질문과 방법론을 결정한다.

---

## 1. 지금 결정해야 하는 것

현재 가능한 접근은 많지만, 4페이지 논문에서는 하나의 명확한 가설과 그 가설을 검증하는 비교 실험이 필요하다. 따라서 지금은 전체 시스템을 확장하기보다 다음 세 질문에 먼저 답한다.

1. **촉감 표현 방식**: Open-vocabulary span embedding, N-class taxonomy, 두 방식을 결합한 Hybrid 중 무엇이 좋은가?
2. **이미지→촉감 방법**: 학습하지 않은 pure VLM, 일반 이미지 임베딩, Ridge/MLP, class 예측 중 무엇이 좋은가?
3. **추가 정보의 가치**: 카테고리와 소재 조성정보가 이미지 기반 촉감 예측을 실제로 개선하는가?

추천 알고리즘과 GNN은 위 세 질문의 결과를 확인한 뒤 논문 범위에 포함할지 결정한다.

---

## 2. 논문 후보 방향

### 방향 A — 촉감 표현 방식 비교

> 리뷰의 자유 표현을 그대로 임베딩하는 것보다, LLM으로 정규화한 촉감 class 또는 class+span Hybrid 표현이 이미지 기반 cold-start 촉감 검색을 개선하는가?

비교:

```text
Open-span embedding
vs N-class multi-label
vs Class + Open-span Hybrid
```

현재 교수님 의견과 기존 파이프라인을 가장 자연스럽게 연결할 수 있어 **우선순위가 가장 높은 방향**이다.

### 방향 B — Pure VLM과 Review-supervised 모델 비교

> 별도 학습 없이 pure VLM이 이미지에서 생성한 촉감 설명보다, 실제 구매자 리뷰로 학습한 모델이 더 정확하고 근거 있는 촉감 표현을 제공하는가?

비교:

```text
Pure VLM zero-shot
vs Raw FashionCLIP
vs Review-supervised Ridge/Classifier
vs Hybrid model
```

사람 평가를 포함할 수 있다면 사용자 관점에서 설명하기 좋은 방향이다.

### 방향 C — 추천 알고리즘에 촉감 정보 결합

> 기존 추천 점수에 촉감 적합도를 결합하면 일반 추천 정확도 또는 cold-start·long-tail 성능이 개선되는가?

```text
final score = base recommendation score + α × tactile score
```

현재 평가 후보의 촉감 coverage가 3.25%로 낮기 때문에, 단기간 논문 주제로 선택하기에는 위험하다. Coverage가 충분히 확대된 경우에만 논문 후보로 올린다.

### 방향 D — 상품·소재·촉감 Graph

상품, 촉감 class, 소재 조성, 사용자 interaction을 이웃으로 연결할 수 있지만 현재는 class와 edge가 확정되지 않았고 데이터 규모도 작다. 이번 방향 탐색의 1차 후보에서는 제외하고 후속 연구로 둔다.

---

## 3. 공통 평가용 Gold Set 먼저 만들기

방법을 비교하기 전에 모델과 독립된 평가 데이터를 만들어야 한다. 기존 Qwen prompt 개발에 사용된 표본과 현재 결과를 이미 확인한 70개 test 상품은 최종 논문용 독립 test로 사용하지 않는다.

### 3.1 리뷰 Gold Set

새로운 미사용 리뷰를 선정해 사람이 다음을 표시한다.

- 모든 소재·촉감 exact span
- span의 채택·거절
- 촉감 class
- 방향 또는 극성
- 강도
- 부위 또는 scope
- 착용·세탁 등의 조건
- 이미지에서 관찰 가능한 정도

권장 탐색 규모:

- 리뷰 150~200개
- 최소 20~30%는 두 명이 독립적으로 annotation
- disagreement는 합의 또는 제3자 adjudication

평가 지표:

- Span precision, recall, F1
- Class micro/macro F1
- Direction·condition·scope 정확도
- Annotator agreement

### 3.2 상품 촉감 Gold Set

같은 카테고리 상품 쌍 또는 상품별 후보 목록을 만들고 사람이 다음을 평가한다.

- 두 상품의 촉감 유사성
- 특정 촉감 조건에 대한 적합성
- 이미지에서 판단 가능한지 여부
- 리뷰 근거가 평가와 일치하는지 여부

권장 탐색 규모:

- 상품군 80~120개
- 상품당 같은 카테고리 후보 3~5개
- 최소 일부는 두 명 이상 평가

사람이 상품 이미지만 보는 평가는 `시각적으로 예상되는 촉감`만 검증할 수 있다. 실제 부드러움, 가려움, 세탁 후 수축 등은 이미지와 함께 리뷰 합의, 소재 정보 또는 실물을 기준으로 별도 평가한다.

---

## 4. 실험 E1 — Open-span vs N-class vs Hybrid

### E1-A. Open-span

현재 방식이다.

```text
Exact span → 정규화 claim → 문장 embedding
→ 사용자별 평균 → 상품별 평균
```

장점:

- 자유로운 촉감 표현 보존
- 새로운 표현을 class 밖으로 버리지 않음

위험:

- 표현 희소성과 pseudo-label 노이즈
- BGE 공통 평균 방향
- 소규모 상품 데이터에서 불안정한 target

### E1-B. N-class multi-label

기존 4,527개 claim을 이용해 촉감 taxonomy 후보를 만들고, LLM이 각 span을 하나 이상의 class에 배정한다.

```text
"soft but became loose after washing"
→ softness: positive
→ shape_retention: negative
→ condition: after_washing
```

N은 임의로 고정하지 않는다. 다음 기준을 함께 확인해 결정한다.

- Gold claim coverage
- class별 최소 표본 수
- class imbalance
- 사람 간 agreement
- 이미지 예측 macro-F1
- downstream retrieval 성능

### E1-C. Hybrid

원문과 class를 모두 보존한다.

```text
학습 신호: N-class multi-label + open-span embedding
설명 근거: exact review span
```

비교 지표:

- 이미지→촉감 class micro/macro F1
- 이미지→open embedding centered cosine
- 사람 label 기반 tactile Recall@K·nDCG@K
- class coverage와 tail-class 성능
- 설명에 사용할 수 있는 exact evidence coverage

### E1 의사결정

- N-class가 명확히 우세: class 기반 논문
- Hybrid가 양쪽 지표에서 우세: Hybrid supervision 논문
- Open-span이 유지되거나 우세: taxonomy 필요성 주장을 철회하고 open-vocabulary grounding 논문 유지

---

## 5. 실험 E2 — Qwen 8B vs 더 큰 Teacher

전체 4,158개 리뷰를 먼저 재처리하지 않는다. 동일한 리뷰 Gold Set에서 모델 크기만 바꿔 비교한다.

```text
동일 리뷰
동일 출력 schema
동일 exact-span 규칙
동일 사람 Gold
```

비교 항목:

- Span precision·recall·F1
- 촉감 class macro-F1
- 부정, 조건, 부위 보존율
- JSON/schema 성공률
- 처리 시간과 GPU 비용

확대 실행 기준:

- 큰 모델이 사람 Gold에서 의미 있는 precision/recall 또는 class F1 개선을 보임
- exact quote 오류와 schema 오류가 증가하지 않음
- 전체 데이터 처리 비용이 일정 안에서 감당 가능함

이 기준을 통과한 경우에만 A100에서 전체 corpus를 다시 생성한다.

---

## 6. 실험 E3 — 텍스트 임베딩 모델 비교

현재 BGE-small을 고정된 정답처럼 사용하지 않고, 같은 claim과 같은 split에서 문장 임베딩 모델을 비교한다.

비교군은 다음 역할을 충족하는 최소 후보로 구성한다.

- 현재 384차원 경량 baseline
- 더 큰 영어 retrieval embedding
- 다른 계열의 강한 sentence embedding
- 한국어 질의를 직접 임베딩할 경우 multilingual embedding

평가 항목:

- 사람이 평가한 촉감 문장 쌍과 cosine의 상관
- 같은 class claim의 군집 응집도와 다른 class 분리도
- 이미지→촉감 centered cosine
- 같은 카테고리 tactile Recall@5·nDCG@5
- 메모리, 임베딩 속도, Ridge 출력 차원

모델은 Development에서 선택하고 새로운 최종 test에는 한 번만 적용한다.

---

## 7. 실험 E4 — 이미지→촉감 방법 비교

표현 방식이 정해지기 전에는 frozen image encoder와 작은 head를 사용해 빠르게 비교한다. 처음부터 end-to-end 대형 모델을 학습하지 않는다.

### 비교 방법

| 방법 | 학습 여부 | 입력 | 출력 |
|---|---|---|---|
| Category-only | 없음 | 카테고리 | 카테고리 평균 촉감 |
| Raw FashionCLIP | 없음 | 이미지 | 이미지 유사도 |
| Pure VLM | 없음 | 이미지·prompt | 촉감 class·설명 |
| Ridge-open | 학습 | 이미지+카테고리 | open-span 촉감 벡터 |
| Linear/MLP-class | 학습 | 이미지+카테고리 | N-class multi-label |
| Hybrid | 학습 | 이미지+카테고리 | class + open embedding |

### 평가를 두 층으로 분리

1. **벡터·class 복원**
   - Centered cosine
   - Micro/macro F1
   - AUROC 또는 Average Precision
   - confidence calibration

2. **실제 검색·설명 품질**
   - 사람 Gold 기반 Recall@K·nDCG@K
   - 조건 적합도
   - 촉감 설명 정확도
   - 근거 일치도

Pure VLM은 이미지로 관찰 가능한 속성과 관찰하기 어려운 속성을 분리해 보고한다.

---

## 8. 실험 E5 — 소재 조성정보 Ablation

소재 조성정보가 확보되는 상품에 한해 입력을 단계적으로 추가한다.

```text
A. Image
B. Image + Category
C. Image + Category + Material composition
```

소재 정보 예시:

```text
Polyester 95%, Cotton 5%
```

소재 조성은 촉감 정답이 아니라 prior이므로 리뷰 Gold 또는 사람 Gold에 대한 성능으로 효과를 판단한다.

선택 기준:

- 여러 split에서 일관된 개선
- 특정 소재나 카테고리 shortcut이 아님
- Cold-start와 관찰하기 어려운 촉감 속성에서 실제 개선

---

## 9. 추천·GNN으로 넘어가는 Gate

### 추천 결합 실험 진입 조건

- 추천 catalog의 leakage-safe 촉감 target coverage 50% 이상
- 사용자 tactile profile coverage 50% 이상
- 추천 후보 tactile coverage 50% 이상
- 촉감 표현 방식과 image cold-start 모델 확정

조건을 통과하면 Development에서 α를 선택한다.

```text
score = base score + α × tactile score
```

비교:

```text
Base recommender
Base + 일반 content
Base + tactile
Base + content + tactile
```

### GNN 진입 조건

- 안정적인 촉감 class 확정
- 상품-촉감·상품-소재 edge coverage 확보
- Ridge/MLP/추천 fusion baseline보다 그래프가 필요한 이유가 명확함

현재는 두 조건 모두 충족하지 않아 후순위로 둔다.

---

## 10. 2주 방향 탐색 일정

### 1주차 — 평가 기준과 표현 방식

1. 논문 가설 후보와 지표 동결
2. 미사용 리뷰·상품 Gold 표본 선정
3. 촉감 taxonomy 초안 생성
4. Open-span, N-class, Hybrid target 생성
5. Qwen 8B와 큰 teacher를 Gold Set에서 비교

### 2주차 — 시각 모델과 방향 선택

1. Pure VLM zero-shot 결과 생성
2. Raw FashionCLIP, Ridge-open, class classifier, Hybrid 비교
3. 가능한 범위에서 소재 조성 ablation
4. 사람 평가와 오류 사례 분석
5. 논문 방향 하나를 선택하고 최종 protocol 동결

2주가 끝날 때 전체 corpus 재처리 여부와 논문 중심 가설을 결정한다.

---

## 11. 최종 방향 선택표

| 관찰 결과 | 선택할 논문 방향 |
|---|---|
| N-class가 open-span보다 안정적으로 우수 | Taxonomy 기반 tactile grounding |
| Hybrid가 class와 open-span 모두보다 우수 | Hybrid open/class supervision |
| Review-supervised 모델이 pure VLM보다 우수 | Review-grounded cold-start prediction |
| Pure VLM이 학습 모델과 비슷하거나 우수 | Zero-shot VLM의 가능성과 한계 분석 |
| 소재 조성이 일관되게 개선 | Image+composition multimodal tactile prediction |
| 추천 coverage 확보 후 tactile fusion이 개선 | Tactile-aware recommendation |
| 자동 지표는 개선되지만 사람 평가는 차이 없음 | 모델 성능 주장보다 grounded explanation·human evaluation 중심으로 전환 |

---

## 12. 현재 권장안

현재 가장 현실적인 1차 논문 가설은 다음과 같다.

> **리뷰에서 정규화한 촉감 class와 open-vocabulary 표현을 결합한 Hybrid supervision이, pure VLM과 일반 이미지 임베딩보다 리뷰 없는 상품의 촉감 표현 및 같은 카테고리 촉감 검색을 개선하는가?**

이 가설은 다음 교수님 의견을 하나의 비교 실험으로 연결한다.

- Span 표현 과다와 overfitting 우려
- LLM 기반 N-class 정규화
- 더 큰 teacher 사용
- 더 강한 text embedding 비교
- Pure VLM zero-shot baseline
- 리뷰가 없는 상품의 촉감 설명

Agent, 추천 fusion과 GNN은 이 핵심 실험 결과를 확인한 뒤 후속 범위로 결정한다.
