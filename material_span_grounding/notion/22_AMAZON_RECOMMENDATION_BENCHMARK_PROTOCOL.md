# Amazon 추천 성능 논문 비교 프로토콜

> 기준일: 2026-08-19  
> 목적: Amazon의 사용자–상품 상호작용을 정답으로 사용해 촉감 정보의 추천 기여도를 기존 논문과 공정하게 비교

## 1. 결론

Amazon 데이터에는 `추천 여부`라는 별도 정답 라벨이 없다. Top-K 추천에서는 사용자가 실제로 남긴 리뷰/평점 기록을 **관측된 상호작용**으로 보고, 숨겨 둔 상호작용 상품을 추천 모델이 상위 K개 안에 복원하는지를 평가한다.

논문 비교용 주 실험은 다음 프로토콜이 가장 적합하다.

```text
Amazon Clothing 5-core
→ 사용자별 interaction 무작위 80% / 10% / 10%
→ train / validation / test
→ 모든 미관측 상품을 후보로 하는 full-ranking
→ Recall@10, Recall@20, NDCG@10, NDCG@20
→ BPR, LightGCN, VBPR, LATTICE, BM3 또는 FREEDOM과 비교
→ 동일 backbone + texture를 ablation으로 비교
```

현재 프로젝트의 `Amazon_Fashion 2023 + 시간순 마지막 상품 + negative 100개` 평가는 실서비스 시나리오를 위한 보조 실험으로 유지한다. 두 프로토콜의 숫자는 한 표에서 직접 비교하지 않는다.

## 2. Amazon 데이터에서 무엇이 정답인가

한 행은 다음과 같은 의미다.

```text
(user_id, parent_asin, rating, timestamp)
          ↓
사용자 u가 시점 t에 상품 i에 리뷰/평점을 남긴 관측된 interaction
```

### Top-K 추천

- 정답: validation/test로 숨겨 둔 사용자의 실제 interaction 상품
- 입력: train interaction과 train 시점에 사용 가능한 상품 정보
- 오답 후보: 사용자가 관측상 상호작용하지 않은 상품
- 주의: 미관측 상품은 실제로 싫어한 상품이 아니라 단지 기록이 없는 상품이다. 따라서 엄밀한 인간 선호 음성 라벨이 아니다.

멀티모달 추천 논문의 대표 설정은 별점 값을 만족도로 회귀하지 않고, **별점이 존재하는 모든 리뷰 기록을 positive interaction으로 이진화**한다. 따라서 1점 리뷰도 구매/사용 후 리뷰를 남긴 행동 기록으로 취급된다.

### Rating prediction과의 차이

별점 1–5 자체를 정답으로 예측하면 RMSE/MAE를 쓰는 rating prediction 문제가 된다. 이는 “Top-K에 어떤 상품을 추천할 것인가”와 다른 문제이므로 현재 논문의 주 평가로 섞지 않는다.

## 3. 조사한 대표 논문 프로토콜

### LATTICE / BM3 / FREEDOM 계열

이 계열은 Amazon의 Baby, Sports, Clothing 데이터를 5-core로 가공하고, 사용자별 interaction을 8:1:1로 나눈 뒤 full-ranking으로 Recall과 NDCG를 측정한다.

| 항목 | 공통적인 설정 |
|---|---|
| 데이터 | Amazon Baby / Sports / Clothing |
| 전처리 | 사용자와 상품 모두 최소 5 interactions인 5-core |
| positive | rating이 존재하는 review interaction |
| split | 사용자별 random 80% train / 10% validation / 10% test |
| 후보군 | 사용자가 interaction하지 않은 모든 상품 |
| 지표 | Recall@10/20, NDCG@10/20 |
| 튜닝 | validation 지표만 사용 |
| 비교 모델 | BPR, LightGCN, VBPR, MMGCN, GRCN, LATTICE 등 |

FREEDOM이 사용한 Clothing 데이터 통계는 사용자 39,387명, 상품 23,033개, interaction 278,677개다. 같은 논문에 보고된 참고 수치는 아래와 같다.

| Clothing | R@10 | R@20 | N@10 | N@20 |
|---|---:|---:|---:|---:|
| BPR | 0.0206 | 0.0303 | 0.0114 | 0.0138 |
| LightGCN | 0.0361 | 0.0544 | 0.0197 | 0.0243 |
| VBPR | 0.0281 | 0.0415 | 0.0158 | 0.0192 |
| LATTICE | 0.0492 | 0.0733 | 0.0268 | 0.0330 |
| FREEDOM | 0.0629 | 0.0941 | 0.0341 | 0.0420 |

이 수치는 구현 검산의 참고값이다. 데이터 파일, split, feature, seed, 구현이 조금이라도 다르면 그대로 직접 비교하지 않고 같은 코드베이스에서 baseline을 다시 실행한다.

### VBPR

VBPR은 이미지 특징을 BPR 기반 개인화 랭킹에 추가한 고전적인 시각 추천 baseline이다. 원 논문은 사용자당 positive가 5개 미만인 사용자를 제거하고 AUC를 보고했으며, 최근 MMRec 계열 논문에서는 동일한 8:1:1/full-ranking 환경에 다시 구현되어 Recall/NDCG baseline으로 사용된다. 따라서 원 논문의 AUC 숫자보다 통합 프레임워크에서 재실행한 VBPR을 비교 대상으로 삼는다.

### Amazon Reviews 2023 공식 split

Amazon Reviews 2023은 중복 user–`parent_asin` 리뷰 중 최초 기록을 남긴 pure-ID 파일과 다음 split을 제공한다.

- Leave-last-out: 사용자별 마지막 interaction=test, 끝에서 두 번째=validation, 나머지=train
- Absolute timestamp: 모든 도메인을 공통 시각 `t1`, `t2`로 나눔

공식 5-core 목록에는 `Amazon_Fashion`이 없고 `Clothing_Shoes_and_Jewelry`가 있다. 또한 2023의 `Amazon_Fashion`과 과거 멀티모달 논문의 `Clothing`은 같은 벤치마크가 아니다. 이름만 보고 양쪽 숫자를 직접 비교하면 안 된다.

## 4. 우리 프로젝트에 권장하는 2개 평가 트랙

### Track A — 기존 논문과 직접 비교하는 주 표

`MMRec Clothing 5-core`와 그 고정 split/feature를 사용한다.

목표 질문:

> 같은 interaction과 같은 후보군에서 기존 이미지·텍스트 멀티모달 정보에 촉감 표현을 추가하면 추천 정확도가 향상되는가?

최소 모델 표:

| 역할 | 모델 |
|---|---|
| 비개인화 하한 | Popularity |
| 협업 필터링 | BPR-MF |
| 강한 CF | LightGCN |
| 이미지 baseline | VBPR |
| 멀티모달 baseline | LATTICE 또는 FREEDOM |
| 제안 1 | BPR/LightGCN + texture |
| 제안 2 | 기존 multimodal + texture |

촉감 방식의 기여를 분리하기 위한 핵심 ablation:

```text
ID interaction only
ID + image
ID + text
ID + image + text
ID + texture
ID + image + text + texture
```

### Track B — 현재 프로젝트의 현실적인 시간순 검증

현재 `Amazon_Fashion 2023` 시간순 evaluator를 유지하되, 논문 주 표와 구분해 robustness/cold-start 표로 보고한다.

- 다음 상품 예측
- 추천 시점 이후의 interaction·리뷰 사용 금지
- cold-start / long-tail / sparse-history cohort
- Recall/NDCG/MRR와 tactile coverage
- 기존 sampled-100 결과와 별도로 가능하면 full-ranking도 추가

Track B는 “실제 미래를 예측하는가”에 더 가깝지만, 기존 MMRec 논문의 공개 수치와 직접 비교하는 표는 아니다.

## 5. Track A의 정확한 평가 절차

### 5.1 데이터 고정

1. 논문/공개 코드와 동일한 Amazon Clothing interaction 파일을 받는다.
2. `(user, item)` 반복 처리, 5-core, item ID 정의를 manifest에 기록한다.
3. 공개 split이 있으면 그대로 사용한다. 새로 나누면 seed와 각 split hash를 저장한다.
4. 모든 모델이 동일한 train/validation/test와 item universe를 사용한다.

### 5.2 특징 생성 전 split

반드시 **split을 먼저 만든 뒤** 특징을 생성한다.

```text
전체 reviews
→ interaction split 확정
→ train review text만 texture extraction/aggregation에 사용
→ validation으로 hyperparameter와 alpha 선택
→ test는 마지막 한 번만 평가
```

다음은 금지한다.

- test 사용자의 test 리뷰 문장을 texture feature 생성에 사용
- test 이후에 작성된 다른 사용자의 리뷰를 시간순 실험 feature로 사용
- 전체 리뷰로 tactile vocabulary/classifier를 만든 뒤 같은 test에서 평가
- test 결과를 보고 texture 가중치 `alpha` 선택

상품 이미지·제조사 소재 정보처럼 추천 시점에 이미 공개된 정적 정보는 사용할 수 있지만, 가용 시점에 대한 가정을 명시한다.

### 5.3 학습과 validation

- 모든 baseline과 제안 모델의 embedding size, epoch budget, early stopping 조건을 최대한 통일한다.
- 모델별 hyperparameter와 texture 결합 가중치 `alpha`는 validation의 NDCG@20 또는 사전 고정한 하나의 지표로 선택한다.
- test는 최종 설정이 잠긴 뒤 평가한다.
- 서로 다른 모델에 같은 candidate universe와 exclusion rule을 적용한다.

### 5.4 Full-ranking

각 사용자에 대해 validation에서는 train에서 이미 본 상품을 제외하고, test에서는 train과 validation에서 이미 본 상품을 제외한다. 정답 test 상품은 후보에 남기고 나머지 전체 상품의 점수를 계산한다. test에 여러 정답 상품이 있으면 그 상품들이 상위 K개에 얼마나 들어오는지 측정한다.

100개 negative만 뽑는 sampled 평가는 더 쉬운 문제이며 sampler에 따라 숫자가 크게 달라진다. 따라서 기존 논문의 full-ranking 숫자와 sampled-100 숫자를 비교하지 않는다.

### 5.5 지표

주 지표는 `NDCG@20`으로 고정하고 `Recall@10/20`, `NDCG@10`을 함께 보고한다.

- Recall@K: test 정답 상품 중 Top-K가 찾아낸 비율
- NDCG@K: 정답을 찾았는지뿐 아니라 더 위에 배치했는지를 반영
- 단일 정답 leave-one-out에서는 Recall@K와 Hit Rate@K가 동일
- 다중 정답 8:1:1 split에서는 Recall과 Hit Rate가 동일하지 않음

보조 지표:

- Coverage@K: texture feature가 존재하는 추천 상품 비율
- cold/long-tail/head cohort의 Recall/NDCG
- texture relevance 또는 TactileMatch는 별도 진단 지표

TactileMatch가 높아도 실제 test 상품을 못 찾을 수 있으므로 일반 추천 지표를 대체하지 않는다.

### 5.6 통계 보고

- 최소 5개 random seed 평균과 표준편차
- 같은 사용자 결과를 짝지은 paired bootstrap 95% confidence interval
- 가장 강한 baseline 대비 상대 개선율
- 가능하면 paired t-test 또는 randomization test와 p-value
- 실패한 seed를 임의로 제외하지 않음

## 6. 촉감 coverage 문제

제안 모델만 촉감 정보가 있는 상품으로 test 대상을 줄이면 쉬운 subset에서 평가하는 셈이 된다. 다음 중 하나가 필요하다.

1. Clothing benchmark의 모든 상품에 이미지 기반 texture representation을 생성한다.
2. 결측 상품에는 명시적인 missing mask를 두고 모든 모델을 같은 전체 item universe에서 평가한다.

그리고 반드시 다음을 같이 보고한다.

- 전체 상품 중 texture feature coverage
- test 정답 중 texture feature coverage
- Top-K 추천 중 texture feature coverage
- coverage가 있는 공통 subset의 보조 결과

공통 subset 결과는 분석용이며 전체 benchmark 결과를 대신하지 않는다.

## 7. 논문에서 주장할 수 있는 형태

가장 안전한 주장은 다음과 같다.

> 표준 Amazon Clothing full-ranking benchmark에서 동일한 collaborative/multimodal backbone에 촉감 표현을 추가했을 때 Recall/NDCG가 향상되며, 향상 폭은 interaction이 적은 상품과 사용자에서 더 크게 나타난다.

이 주장을 위해 최소한 다음 결과가 필요하다.

1. `Backbone` 대 `Backbone + texture`의 전체 추천 성능
2. image/text feature만 추가한 경우와 texture까지 추가한 경우의 ablation
3. cold-start/long-tail cohort 결과
4. texture extraction 품질의 사람 평가
5. coverage와 누수 방지 규칙

## 8. 당장 진행할 순서

1. MMRec Clothing 데이터와 split을 확보하고 FREEDOM 논문의 데이터 통계를 재현한다.
2. 기존 공개 구현으로 Popularity, BPR, LightGCN, VBPR을 먼저 실행한다.
3. 공개 논문 수치와 크게 다르면 texture 모델을 붙이기 전에 split/feature/evaluator 차이를 해결한다.
4. 같은 item ID에 이미지 기반 texture representation과 missing mask를 연결한다.
5. `LightGCN`과 `LightGCN + texture`를 첫 핵심 비교로 실행한다.
6. validation에서 texture 결합 가중치를 고정하고 locked test를 평가한다.
7. FREEDOM 또는 LATTICE에 texture modality를 추가해 강한 multimodal baseline과 비교한다.

## 9. 참고 자료

- [Amazon Reviews 2023 공식 사이트](https://amazon-reviews-2023.github.io/)
- [Amazon Reviews 2023 공식 benchmark scripts](https://github.com/hyp1231/AmazonReviews2023/tree/main/benchmark_scripts)
- [Amazon Reviews 2023 5-core와 split 설명](https://amazon-reviews-2023.github.io/data_processing/5core.html)
- [LATTICE: Mining Latent Structures for Multimedia Recommendation](https://arxiv.org/abs/2104.09036)
- [BM3: Bootstrap Latent Representations for Multi-modal Recommendation](https://arxiv.org/abs/2207.05969)
- [FREEDOM: A Tale of Two Graphs](https://arxiv.org/abs/2211.06924)
- [VBPR: Visual Bayesian Personalized Ranking](https://arxiv.org/abs/1510.01784)
- [MMRec 통합 구현](https://github.com/enoche/MMRec)
