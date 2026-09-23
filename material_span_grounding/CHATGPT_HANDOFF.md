# ChatGPT 대화 인수인계 문서

> 작성일: 2026-08-20  
> 용도: 이 파일을 ChatGPT에 업로드하거나 아래 내용을 새 대화의 첫 메시지로 전달해 Codex와 진행하던 논의를 이어간다.  
> 현재 프로젝트: `/home/user/onsesang/material_span_grounding`  
> 주의: `/home/user/onsesang/texture_project`는 이전 버전이며 현재 프로젝트가 아니다.

---

## 0. ChatGPT가 먼저 읽어야 할 지시사항

나는 아래 프로젝트의 연구 방향, 실험 설계, 추천 평가 방법과 졸업프로젝트 구현 범위를 계속 논의하고 싶다. 아래 내용을 현재 상태로 간주하고, 처음부터 프로젝트를 다시 추측하지 말아 달라.

답변할 때 다음 원칙을 지켜 달라.

1. 한국어로 설명한다.
2. **이미 확인된 사실**, **현재 해석**, **앞으로의 제안**을 구분한다.
3. Amazon 데이터에 사람 손으로 부여한 촉감 정답이 있다고 가정하지 않는다.
4. Qwen이 채택한 claim을 human gold label로 부르지 않는다. 이는 pseudo-label이다.
5. 이미지 기반 cold-start 평가의 리뷰 벡터는 proxy ground truth이지 실제 촉감 정답이 아니다.
6. 서로 다른 Amazon 버전·카테고리·split·candidate protocol의 논문 수치를 직접 비교하지 않는다.
7. 사용자가 이미지를 업로드해 검색하는 서비스라고 가정하지 않는다. 이미지는 주로 리뷰가 없는 상품의 촉감을 내부적으로 예측하는 데 사용한다.
8. 고정 taxonomy를 실험하더라도 원문 exact span과 open-vocabulary 표현을 삭제하지 않는다. Class는 보조 표현 또는 학습 신호로 추가한다.
9. Test 리뷰나 미래 리뷰로 상품 촉감 feature를 만들지 않는다. 데이터 누수를 항상 점검한다.
10. 아직 결정되지 않은 사안을 확정된 결정처럼 쓰지 말고, 비교 가능한 실험으로 제시한다.
11. 나는 단순 동의를 원하는 것이 아니다. 연구 논리의 약점, confounder, 평가 오류를 구체적으로 지적해 달라.
12. 지금은 코드를 바로 작성하기보다 논문 방향과 최소 검증 실험을 우선 논의한다. 내가 구현을 요청하면 그때 구현 계획을 구체화한다.

이 문서를 읽은 뒤에는 프로젝트를 다시 요약하는 데 답변 대부분을 쓰지 말고, 내가 이어서 묻는 질문에 바로 답해 달라.

---

## 1. 프로젝트 한 줄 설명

시각장애인의 온라인 의류 쇼핑을 돕기 위해 Amazon 상품 리뷰에서 실제 구매자가 언급한 소재·촉감 근거를 추출하고, 이를 상품 검색·비교·추천과 근거 기반 설명에 활용하는 프로젝트다.

핵심 아이디어는 다음과 같다.

```text
실제 구매자 리뷰에서 촉감 표현 추출
→ 상품별 촉감 표현 구성
→ 리뷰가 없는 상품은 이미지로 촉감 표현 예측
→ 자연어 검색·유사상품·방향성 대안·개인화 추천에 사용
→ 가능한 경우 실제 리뷰 문장을 근거로 제시
```

---

## 2. 해결하려는 문제

일반적인 의류 쇼핑 이미지와 상품 설명만으로는 다음 정보를 충분히 알기 어렵다.

- 부드러움, 까끌함, 뻣뻣함
- 두께, 무게, 비침
- 신축성과 회복성
- 통기성, 보온성, 땀 흡수
- 드레이프와 형태 유지
- 세탁 후 수축, 보풀, 늘어남, 변형
- 안감이나 특정 부위의 소재 특성
- 피부 자극과 착용 중 소재 반응

특히 시각장애인은 이미지 중심의 상품 탐색에서 더 큰 정보 격차를 경험할 수 있다. 최종 서비스는 촉감 조건을 자연어 또는 음성으로 요청하고, 추천 이유와 실제 리뷰 근거를 들을 수 있는 형태를 목표로 한다.

---

## 3. 사용자가 상품을 찾는 방식

이 프로젝트를 “사용자가 이미지로 검색하는 시스템”으로만 이해하면 안 된다. 고려하는 사용자 흐름은 여러 가지다.

### 자연어·음성 조건 검색

```text
“세탁 후 잘 늘어나지 않는 치마를 찾아줘.”
“피부에 까끌거리지 않는 얇은 여름 상의를 찾아줘.”
```

질의를 카테고리와 촉감 조건으로 구조화한 뒤 후보를 검색·재정렬한다.

현재 프로토타입은 단순 한국어·영어 표현을 규칙 기반으로 구조화한다. 복잡한 질의는 향후 structured-output LLM을 사용할 수 있지만, Qwen 사용 여부는 확정되지 않았다.

### 현재 상품에서 이어지는 탐색

- 현재 상품과 촉감이 비슷한 상품
- 현재 상품보다 더 부드러운 상품
- 덜 얇거나 덜 비치는 상품
- 세탁 후 형태 유지가 더 좋은 대안

### 일반 개인화 추천

사용자의 과거 interaction으로 계산한 기본 추천 점수에 촉감 적합도를 결합하는 방식이다.

```text
final_score = base_recommendation_score + alpha × tactile_score
```

이 방향은 연구 후보이며, 현재 촉감 coverage 부족 때문에 효과가 확인된 상태는 아니다.

### 이미지의 역할

이미지는 사용자가 반드시 입력하는 검색 질의가 아니다. 리뷰가 없거나 부족한 신규 상품에도 촉감 표현을 부여하기 위한 cold-start 입력으로 사용한다.

---

## 4. 현재 데이터와 파이프라인

### 데이터 구성

현재 핵심 촉감 데이터는 Amazon Fashion에서 선정한 다음 규모다.

| 항목 | 현재 값 |
|---|---:|
| 상품 | 500개 |
| 리뷰 | 4,158개 |
| exact span | 6,345개 |
| Qwen이 채택한 claim | 4,527개 |

중요한 해석:

- 6,345개 span은 리뷰 원문에서 그대로 복사한 후보 근거다.
- 4,527개 claim은 Qwen 의미 검증기가 채택한 pseudo-label이다.
- 4,527개 전체가 독립적인 사람 검수로 정답 확인된 것은 아니다.

### 1단계: Exact span 추출

Qwen이 리뷰에서 소재·촉감 관련 문장을 요약하지 않고 원문 그대로 추출한다.

```text
Review: “The fabric is thick but not see-through.”
Span:
- “The fabric is thick”
- “not see-through”
```

부정어, 강도, 비교, 세탁 조건을 보존하고, 코드로 원문 exact substring인지 검사한다.

### 2단계: 의미 검증과 구조화

추출 span과 전체 리뷰 문맥을 다시 Qwen에 넣어 실제 소재·촉감 근거인지 판정하고 다음을 구조화한다.

- 짧은 자유 텍스트 claim
- scope 또는 부위
- 존재·부재·비교·불확실성
- 긍정·부정 및 강도
- 직접 촉감, 착용 경험, 세탁 후 변화 등의 evidence basis
- 이미지에서 관찰 가능한 정도

### 3단계: 사람 검수

별도의 검수 UI가 있으며 다음 기능을 지원한다.

- Good / Bad / Edit
- 누락 span 추가
- 원문 전체와 sibling span 동시 확인
- Full Review Checked
- 정확도와 recall을 분리해서 검수

독립적인 최종 human gold set은 추가 구축이 필요하다.

### 4단계: 상품 촉감 벡터

현재 채택된 claim을 `BAAI/bge-small-en-v1.5`로 384차원 임베딩했다.

```text
Claim embedding
→ 같은 사용자의 중복 완화 및 사용자별 평균
→ 상품 안에서 사용자별 동일 가중 평균
→ review-derived product tactile vector
```

현재 보고된 상태:

- 500개 상품 중 495개에 review-derived 촉감 벡터가 있음
- 그중 470개는 서로 다른 사용자 2명 이상의 촉감 근거가 있음
- BGE 벡터는 공통 평균 방향이 강해 raw cosine뿐 아니라 centered cosine을 함께 봐야 함

`BGE-small`은 확정된 최종 모델이 아니라 초기 경량 baseline이다. 더 큰 영어 retrieval/sentence embedding과 multilingual embedding을 비교할 계획이다.

### 5단계: 이미지로 촉감 벡터 예측

현재 방식은 다음과 같다.

```text
FashionCLIP image embedding 512차원
+ category one-hot 11차원
→ Ridge 또는 MLP
→ review tactile space 384차원
```

중복 상품을 product family 단위로 묶은 465개 상품군을 사용했다.

| Split | 상품군 |
|---|---:|
| Train | 321 |
| Development | 70 |
| Locked test | 70 |

현재 test 결과:

| 방법 | Centered cosine | Same-category Recall@5 | NDCG@5 |
|---|---:|---:|---:|
| Category-only | 0.0998 | 0.1400 | 0.7367 |
| Raw FashionCLIP image | - | 0.2171 | 0.7762 |
| MLP | 0.1323 | 0.2371 | 0.7990 |
| Ridge | **0.2006** | **0.2657** | **0.8093** |

Ridge가 현재 비교군 중 가장 높았지만 다음 한계가 있다.

- 정답은 사람이 직접 부여한 실제 촉감이 아니라 review-derived product vector다.
- 총 461개 family만 review target을 가진 소규모 실험이다.
- review target은 시간 인식 방식으로 만들어지지 않았다.
- 동일 BGE 공간의 공통 방향 때문에 raw cosine이 과도하게 높다.

따라서 이 결과는 “Ridge가 실제 촉감을 정확히 맞힌다”가 아니라 “현재 review proxy 공간을 비교 방법보다 잘 복원했다”는 의미다.

### 6단계: 리뷰·이미지 Hybrid

- 리뷰가 충분하면 review vector 비중을 높임
- 리뷰가 부족하면 image-predicted vector 비중을 높임
- 리뷰가 없으면 image prediction만 쓰고 `이미지 기반 예상`으로 표시

현재 중복 제거된 465개 상품군 가운데 461개는 리뷰와 이미지를 결합하고, 4개는 이미지 예측만 사용한다.

이미지 예측값을 실제 구매자 리뷰처럼 표현하면 안 된다. 서비스 설명에서도 `review-derived evidence`와 `image-derived estimate`를 구분한다.

---

## 5. 현재 추천 평가 상태

현재 내부 시간순 evaluator는 다음 프로토콜이다.

```text
Amazon_Fashion 2023 interaction
→ rating 4~5만 positive
→ 같은 사용자·상품 반복 제거
→ positive 4개 이상 사용자
→ 마지막 interaction=test
→ 끝에서 두 번째=validation
→ 이전 interaction=train
→ test 정답 1개 + sampled negative 100개
```

| 항목 | 값 |
|---|---:|
| 원본 interaction | 272,606 |
| positive dedup interaction | 194,528 |
| 평가 사용자 | 332명 |
| 상품 universe | 20,198개 |
| case당 후보 | 101개 |
| cold-start target | 86 cases |
| long-tail target | 184 cases |

현재 tactile 추천 성능이 개선되지 않았지만 촉감 정보가 무효라고 결론 내릴 수 없다. 평가 상품 20,198개에 비해 촉감 벡터가 있는 상품이 매우 적고, test 정답 촉감 coverage도 극히 낮기 때문이다.

이 평가는 내부 서비스·시간순 robustness 평가로는 의미가 있지만 기존 추천 논문의 공개 숫자와 직접 비교할 수 없다.

---

## 6. Amazon 추천 정답과 논문 비교에 대한 현재 결론

### Amazon에는 별도 추천 정답 라벨이 없다

Top-K 추천에서는 실제로 관측된 리뷰/평점 interaction 중 일부를 숨기고, 해당 상품을 모델이 복원하는지를 평가한다.

- held-out interaction: positive 정답
- unobserved item: 평가 후보이지만 실제 dislike 정답은 아님
- rating 1~5 자체를 예측하면 별도의 rating prediction 문제이며 RMSE/MAE를 사용함

### 기존 멀티모달 논문과 직접 비교할 주 프로토콜

LATTICE, BM3, FREEDOM 계열과 비교하려면 다음 별도 Track A가 필요하다.

```text
Amazon Clothing 5-core
→ 모든 rating/review interaction을 positive로 처리
→ 사용자별 random 80% train / 10% validation / 10% test
→ 사용자가 상호작용하지 않은 모든 상품 대상 full-ranking
→ Recall@10, Recall@20, NDCG@10, NDCG@20
```

최소 baseline:

- Popularity
- BPR-MF
- LightGCN
- VBPR
- LATTICE 또는 FREEDOM
- LightGCN + texture
- Multimodal model + texture

핵심 ablation:

```text
ID only
ID + image
ID + text
ID + image + text
ID + texture
ID + image + text + texture
```

### 현재 Amazon_Fashion 2023과 논문 Clothing은 다르다

- 현재 프로젝트: Amazon Reviews 2023의 `Amazon_Fashion`
- 기존 MMRec 논문: 과거 Amazon의 `Clothing, Shoes and Jewelry` 5-core 가공본
- Amazon Reviews 2023 공식 5-core에는 `Clothing_Shoes_and_Jewelry`가 있지만 `Amazon_Fashion`은 없음

따라서 현재 332-user sampled-100 숫자를 기존 Clothing full-ranking 논문 표에 붙이면 안 된다.

권장하는 2-track 구성:

```text
Track A: 표준 Clothing benchmark
         기존 논문과 정량 비교하는 main table

Track B: Amazon_Fashion 2023 chronological
         현실성, cold-start, long-tail robustness table
```

### 필수 누수 방지

```text
interaction split을 먼저 고정
→ train review만 texture extraction/aggregation에 사용
→ validation에서 모델과 alpha 선택
→ locked test는 마지막 한 번만 사용
```

금지 사항:

- test 사용자의 test 리뷰 문장을 상품 texture feature에 사용
- 시간순 평가에서 추천 시점 이후 다른 사용자의 리뷰를 사용
- 전체 리뷰로 taxonomy/classifier를 만든 뒤 같은 test에서 평가
- test 결과를 보고 결합 가중치 alpha를 선택
- 제안 모델만 texture coverage가 있는 쉬운 subset에서 평가

---

## 7. 교수님 미팅에서 나온 피드백

### 1. Open span만 사용했을 때의 희소성과 과적합 우려

서로 다른 span 종류가 많아 이미지 모델이 작은 데이터에서 개별 문장을 외우거나 희소한 target을 학습할 수 있다는 우려가 있었다. LLM으로 한 번 더 정규화해 N개의 촉감 class로 나누는 방안을 실험하자는 의견이 나왔다.

현재 해석:

- 이 문제를 단순히 “span 개수가 많으면 overfitting”이라고 단정하지 않는다.
- Open-span, N-class multi-label, class+span hybrid를 같은 human gold와 downstream 평가에서 비교해야 한다.
- Class를 쓰더라도 exact span은 설명 근거와 open-vocabulary tail 보존을 위해 남긴다.

### 2. 졸업프로젝트와 WSDM Short Paper 분리

- 졸업프로젝트: 실사용 중심으로 빠르게 완성, 예정 마감 10월 말
- Short Paper: 더 엄밀한 가설·비교·평가, 예정 마감 11월 말

졸업프로젝트에서 서비스 전체 흐름을 먼저 완성하고, 논문에서는 한 가지 명확한 방법론 기여와 정량 검증에 집중하는 방향이다.

### 3. 검토 가능한 연구·서비스 방향

1. 상품을 선택했을 때 cold-start 제품까지 항상 촉감 설명 제공
2. 위 기능을 agent 형태로 제공
3. 기존 추천 점수에 texture score를 더하는 추천 모델
4. 상품·촉감·소재 정보 관계를 이용한 GNN
5. 리뷰뿐 아니라 `Polyester 95%, Cotton 5%` 같은 소재 조성 정보 추가

한 번에 모두 논문에 넣기보다 2~3개 접근을 빠르게 비교해 가장 논리가 강한 방향을 선택한다.

### 4. 모델 크기

Qwen-VL 8B가 작을 수 있으므로 A100에서 더 큰 teacher/VLM을 시험하고, 텍스트 임베딩도 더 강한 모델과 비교하라는 의견이 있었다.

전체 데이터를 즉시 재처리하지 않고 같은 human gold subset에서 Qwen 8B와 큰 모델을 비교한 후 확대 여부를 결정한다.

### 5. Pure VLM zero-shot 확인

별도 학습 없이 기존 VLM이 이미 이미지에서 촉감 설명을 잘 생성할 수 있는지 먼저 확인해야 한다. 사람 평가로 다음을 비교한다.

```text
Pure VLM zero-shot
vs Raw image embedding
vs Review-supervised Ridge/classifier
vs Hybrid
```

이미지에서 볼 수 있는 속성과 실제 착용·세탁 후에만 알 수 있는 속성을 분리해서 평가해야 한다.

---

## 8. 현재 논문 방향 후보

### 후보 A: Open-span vs N-class vs Hybrid

연구 질문:

> 리뷰의 자유 촉감 표현을 그대로 임베딩하는 방식보다 LLM으로 정규화한 촉감 class 또는 class+span hybrid가 이미지 기반 촉감 예측과 검색을 개선하는가?

비교:

```text
Open-span embedding
N-class multi-label
Class + open-span hybrid
```

현재 가장 우선순위가 높은 방법론 탐색이다.

### 후보 B: Pure VLM vs Review-supervised model

연구 질문:

> 학습하지 않은 VLM보다 실제 구매자 리뷰로 supervision한 모델이 더 정확하고 근거 있는 촉감 표현을 제공하는가?

사람 평가를 포함하면 서비스와 연구 양쪽에서 설명하기 좋다.

### 후보 C: 추천 모델에 촉감 추가

연구 질문:

> 기존 collaborative/multimodal recommender에 tactile modality를 추가하면 전체·cold-start·long-tail Recall/NDCG가 개선되는가?

논문 비교는 분명하지만 benchmark 전체 상품에 촉감 feature를 제공해야 하므로 coverage 확장이 선행되어야 한다.

### 후보 D: 소재 조성정보의 추가 가치

```text
Image
vs Image + Category
vs Image + Category + Material composition
```

소재 조성은 실제 촉감 정답이 아니라 prior이므로 human/review gold에서 효과를 검증해야 한다.

### 후보 E: GNN

상품–촉감 class–소재 조성–사용자 interaction graph를 만들 수 있지만 현재 class와 edge 정의, coverage가 확정되지 않았다. 단순히 GNN을 사용했다는 이유만으로 논문 기여가 되지 않으므로 우선순위가 낮다.

---

## 9. 방법론을 고르기 전에 필요한 공통 Gold Set

### 리뷰 Gold Set

기존 prompt 개발에 쓰지 않은 리뷰 150~200개를 권장한다.

사람이 표시할 내용:

- 모든 촉감 exact span
- span 채택/거절
- 촉감 class
- 방향·극성·강도
- scope와 조건
- 이미지에서 관찰 가능한지

20~30% 이상은 두 명이 독립 annotation하고 disagreement를 합의한다.

지표:

- span precision / recall / F1
- class micro / macro F1
- condition·direction·scope 정확도
- annotator agreement

### 상품 촉감 Gold Set

같은 카테고리 안에서 상품 쌍 또는 상품별 후보 목록을 사람이 평가한다.

- 촉감 유사성
- 특정 촉감 조건 적합성
- 이미지로 판단 가능한지
- 리뷰 근거와 설명이 일치하는지

이미지만 보는 사람 평가는 `시각적으로 예상되는 촉감`만 검증한다. 실제 부드러움, 피부 자극, 세탁 후 수축은 리뷰 합의, 소재 정보 또는 실물이 필요하다.

---

## 10. 추천하는 탐색 실험 순서

현재 권장 순서는 다음과 같다.

```text
E0. 독립 human gold set 구축
 ↓
E1. Qwen 8B vs larger teacher의 span/class 품질
 ↓
E2. Open-span vs N-class vs Hybrid 표현 비교
 ↓
E3. BGE-small vs 더 강한 text embedding 비교
 ↓
E4. Pure VLM vs FashionCLIP vs Ridge/classifier/Hybrid
 ↓
E5. Material composition ablation
 ↓
논문 방향 선택
 ↓
필요할 경우 표준 recommendation benchmark로 확장
```

추천 알고리즘을 논문 핵심으로 선택한다면 별도의 MMRec Clothing Track A를 먼저 재현하고, baseline 재현이 확인된 뒤 texture modality를 연결한다.

---

## 11. 아직 확정되지 않은 핵심 질문

ChatGPT와 앞으로 논의할 주요 질문이다.

1. 4-page paper의 한 문장짜리 핵심 contribution을 무엇으로 정할 것인가?
2. Open-span, N-class, Hybrid 중 어떤 표현이 실제로 나은가?
3. N-class를 만든다면 class 수와 taxonomy를 어떤 데이터 기준으로 결정할 것인가?
4. larger LLM/VLM이 Qwen 8B보다 실제 human gold에서 충분히 나은가?
5. Pure VLM이 잘하는 시각 속성과 실패하는 비시각 속성을 어떻게 분리할 것인가?
6. BGE-small을 대체할 embedding 후보를 어떤 최소 세트로 비교할 것인가?
7. 논문의 주 downstream을 이미지→촉감 검색으로 할지 추천 성능으로 할지?
8. 추천을 택한다면 Clothing benchmark 전체 상품의 texture coverage를 어떻게 확보할 것인가?
9. 소재 조성정보가 이미지보다 어떤 속성에서 추가 이득을 주는가?
10. 졸업프로젝트에서 agent까지 구현할지, 단순하고 접근 가능한 검색·비교 UI에 집중할지?
11. 시각장애인 사용자 평가를 어떤 task와 지표로 설계할 것인가?

---

## 12. 절대 혼동하면 안 되는 사항

- `texture_project`는 이전 프로젝트다. 현재 작업은 `material_span_grounding`이다.
- 4,527 claim은 human gold가 아니라 Qwen pseudo-label이다.
- Amazon interaction은 tactile label이 아니다.
- Review-derived product vector도 실제 촉감 정답이 아니라 proxy다.
- Image prediction은 실제 구매자 evidence가 아니라 예상값이다.
- 사용자는 반드시 이미지로 검색하지 않는다.
- Ridge가 현재 proxy 평가에서 가장 높지만 최종 방법론으로 확정된 것은 아니다.
- 추천 성능 개선은 아직 확인되지 않았다.
- 현재 추천 실패는 texture coverage가 너무 낮아 결론을 내릴 수 없는 상태다.
- Amazon_Fashion 2023과 기존 논문의 Clothing 5-core는 다른 benchmark다.
- Sampled-100 결과와 full-ranking 결과를 직접 비교할 수 없다.
- Class taxonomy를 추가하더라도 exact span과 open-vocabulary 원문을 보존한다.

---

## 13. 현재 프로젝트의 주요 문서

ChatGPT가 로컬 경로를 직접 읽을 수는 없으므로, 더 자세한 논의가 필요하면 아래 파일을 추가로 업로드한다.

| 문서 | 내용 |
|---|---|
| `notion/00_PROJECT_MASTER_SUMMARY.md` | 전체 프로젝트 배경과 초기 설계 |
| `notion/20_PROJECT_PIPELINE_FOR_PROFESSOR.md` | 교수님 설명용 핵심 파이프라인 |
| `notion/21_PAPER_DIRECTION_METHOD_SELECTION_PLAN.md` | 방법론 탐색 실험 계획 |
| `notion/22_AMAZON_RECOMMENDATION_BENCHMARK_PROTOCOL.md` | 추천 논문 비교 프로토콜 |
| `notion/11_OFFLINE_RECOMMENDATION_EVALUATION.md` | 현재 시간순 evaluator와 coverage 한계 |
| `notion/17_MULTIMODAL_DESIGN_TACTILE_COLDSTART.md` | 이미지→촉감 cold-start 설계 |
| `notion/19_FRONTEND_API_PAGE_DATABASE.md` | 졸업프로젝트 서비스/API 설계 |

---

## 14. 참고 논문·데이터

- Amazon Reviews 2023: https://amazon-reviews-2023.github.io/
- Amazon Reviews 2023 benchmark scripts: https://github.com/hyp1231/AmazonReviews2023/tree/main/benchmark_scripts
- MMRec toolbox: https://github.com/enoche/MMRec
- VBPR: https://arxiv.org/abs/1510.01784
- LATTICE: https://arxiv.org/abs/2104.09036
- BM3: https://arxiv.org/abs/2207.05969
- FREEDOM: https://arxiv.org/abs/2211.06924

---

## 15. 새 ChatGPT 대화를 시작할 때 함께 보낼 짧은 메시지

아래 문장을 이 파일과 함께 전달하면 된다.

```text
첨부한 CHATGPT_HANDOFF.md는 지금 진행 중인 시각장애인용 의류 촉감 검색·추천 프로젝트의 현재 문맥입니다. 전체를 읽고, 사실·현재 해석·제안을 구분해 주세요. 특히 Qwen claim과 리뷰 벡터를 human ground truth로 간주하지 말고, 기존 Amazon 추천 논문과의 benchmark 차이 및 데이터 누수를 엄격하게 봐 주세요. 프로젝트를 처음부터 다시 요약하기보다 제가 이어서 묻는 연구 방향과 실험 설계 질문에 바로 답해 주세요.
```

---

## 16. 현재 시점에서 ChatGPT와 이어가기 좋은 첫 질문

```text
위 문맥을 바탕으로 4-page short paper 후보 A(Open-span vs N-class vs Hybrid), 후보 B(Pure VLM vs Review-supervised), 후보 C(Texture-enhanced recommendation)를 novelty, 필요한 데이터, 실험 비용, 정량 평가의 명확성, 실패 위험 측면에서 비교해 줘. 그리고 지금 2주 동안 수행할 최소 실험으로 어느 방향을 선택해야 하는지 판단 기준을 제안해 줘. 아직 하나를 임의로 확정하지 말고, 어떤 관찰 결과가 나오면 어떤 방향을 선택할지 decision table로 정리해 줘.
```
