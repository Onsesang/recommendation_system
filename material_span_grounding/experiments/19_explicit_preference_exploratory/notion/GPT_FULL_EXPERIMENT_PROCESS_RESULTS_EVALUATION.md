# GPT 전달용: 촉감 이미지 모델과 명시적 선호 기반 추천 실험

## 0. GPT에게 요청하는 분석

이 문서만을 근거로 다음을 한국어로 분석해 주세요.

1. 연구 목적과 이미지 촉감 예측 → 사용자 선호 추출 → 추천으로 이어지는 실험 흐름.
2. 기존 추천 실험16과 이번 실험19의 차이 및 공정하게 비교할 수 있는 범위.
3. 이미지 예측 성능과 추천 성능이 서로 다른 결론을 보이는 이유에 대한 가설.
4. 전체 결과, 지원 사용자 subset, cold-start 관련 결과, ablation 및 신뢰구간 해석.
5. 데이터 희소성, 후보 검색, 선호 추출 오류, 점수식, 평가 설계 중 어떤 한계가 관찰됐는지.
6. 현재 증거로 주장할 수 있는 것과 없는 것, 졸업논문에 쓸 수 있는 결론.
7. 후속 실험의 우선순위와 각 실험이 검증할 가설. 제안과 이미 수행된 실험을 구분할 것.

주의: human audit은 사용자 요청으로 생략됐다. AI 간 일치와 자동 출력 검증을 정답 정확도라고 부르지 말 것. 일반 추천 정답은 다음 review/rating interaction이지 촉감 때문에 구매했다는 증거가 아니다. 수치가 없는 성능, 유의성, 실행 시간, 원인을 추측해 확정하지 말 것.

## 1. 현재 완료 상태와 핵심 결론

- 실험19의 자동 추출, 출력 보정 재시도, 선호 프로필 구성, validation 가중치 선택, test 추천 평가, paired bootstrap, 코드 테스트, 결과 문서화가 완료됐다.
- 코드 테스트 11개가 통과했다. 이는 구현된 규칙에 대한 검증이며 모든 종류의 누수나 의미 오류가 없다는 증명은 아니다.
- 사람에 의한 의미 검증, 실제 사용자 만족도 조사, 실제 구매·클릭 A/B 테스트는 하지 않았다.
- Test 3,283명에서 category 기반 NDCG@10은 **0.050544**, 명시적 촉감 선호 추가는 **0.050652**였다.
- 차이는 **+0.00010725**, paired bootstrap 95% CI는 **[-0.00044850, +0.00074556]**이다. 0을 포함하므로 이 평가에서 확실한 추가 개선을 확인하지 못했다. 촉감 정보가 항상 무효라는 결론도 아니다.
- 상태 표기: `complete_exploratory_human_audit_skipped`. 탐색 실험 완료이지 사람 검증 완료가 아니다.

## 2. 연구 배경과 두 가지 다른 과제

Amazon Fashion 상품 이미지로 촉감 속성을 예측하고, 사용자 리뷰에서 추출한 촉감 선호와 결합해 추천을 개선하려는 연구다.

| 과제 | 입력과 출력 | 평가가 말해 주는 것 |
|---|---|---|
| 이미지 촉감 예측 | 이미지 → 14개 속성 확률 | 리뷰에서 만든 약한 정답과 이미지 예측의 일치 |
| 명시적 촉감 선호 추천 | 과거 리뷰의 local like/dislike + 상품 촉감 → 추천 순위 | 다음 review/rating interaction 순위의 변화 |

속성이 있다는 사실과 사용자가 좋아한다는 사실은 다르다. 또한 이미지 예측이 잘된다고 그 속성이 다음 interaction을 설명한다고 볼 수 없다.

14개 출력 class는 `soft, firm, smooth, rough, non_elastic, elastic, thin, thick, flexible, stiff, warm, cool, spongy, crisp`이다. 원문 표현 자체는 별도로 보존하며 연결할 수 없는 표현은 `unmapped`로 남긴다.

## 3. 선행 실험과 재사용한 모델

### 3.1 v2에서 v3로의 변경

v2는 7개 bipolar axis와 frozen 이미지 encoder를 사용했다. v3는 14개 atomic-class masked multi-label 예측으로 바꾸고 FashionCLIP vision encoder의 학습 범위를 비교했다.

- v3 grounding: Qwen3-VL-32B-Instruct, 4-bit NF4, candidate span 26,126개 전체 처리.
- 이미지 실험 풀: 8,498 ASIN, 선택 리뷰 70,943개.
- Family-disjoint split: train 6,300 ASIN / development 1,077 / test 1,121.
- 미관측 class는 무조건 negative로 채우지 않고 mask를 사용했다. 관측 product-class pair는 34,168개이며 counterpart negative 생성 규칙이 포함돼 있다.
- 학습 손실은 masked BCE. 모델 깊이와 class별 threshold는 development에서 선택했다.

| FashionCLIP 학습 범위 | Dev macro-F1 | Test macro-F1 | Test micro-F1 | Test macro-AP |
|---|---:|---:|---:|---:|
| Frozen encoder, head만 | 0.6294 | 0.5784 | 0.7621 | 0.5607 |
| Projection + head | 0.6631 | 0.6166 | 0.7824 | 0.6143 |
| 마지막 vision block 1개 + projection/head | 0.6922 | 0.6050 | 0.8145 | 0.6412 |
| 마지막 vision block 2개 + projection/head | 0.6975 | 0.6010 | 0.8216 | 0.6232 |
| 전체 vision encoder | 0.6736 | 0.5801 | 0.8066 | 0.6073 |

공식 선택은 development macro-F1이 가장 높은 **Last2**다. Test macro-F1이 더 높은 projection으로 사후 교체하지 않았다.

학습된 이미지 모델 경로:

```text
experiments/12_class_multilabel_fashionclip_ft/models/fashionclip_last2.pt
SHA-256: 073b542a9d6bd4450aa1f48596c756cc0812b1b5d914945e8f94f7c3fda1934a
```

이번 실험19에서는 Last2를 재학습하지 않고 기존 continuous probability를 재사용했다. 새로운 이미지 checkpoint가 생성된 실험은 아니다.

### 3.2 Category shortcut 진단

실험13의 category-only 속성 예측기는 category ID → 64차원 embedding → 14 logits 구조다. 이미지와 리뷰를 입력하지 않는다.

| 속성 예측 모델 | Test macro-F1 | Test micro-F1 | Test macro-AP |
|---|---:|---:|---:|
| Category-only | 0.5797 | 0.7120 | 0.5359 |
| FashionCLIP Last2 | 0.6010 | 0.8216 | 0.6232 |

실험14는 같은 category/class 안에서 positive와 negative 상품을 구별하는 post-hoc 진단이다. Valid cell은 107개, positive·negative가 각각 10개 이상인 cell은 28개였다.

| Same-category 속성 ranking 지표 | Category-only | Last2 |
|---|---:|---:|
| Macro-cell AUROC | 0.5000 | 0.6568 |
| Pair-weighted AUROC / pairwise accuracy | 0.5000 | 0.7528 |
| Macro AP lift | 0.0000 | 0.1928 |

이는 동일 category 내부의 속성 구분에 관한 결과다. 사용자 개인화나 실제 촉감 만족도의 검증이 아니다. 이번 실험19에서 같은-category 추천 pairwise human evaluation을 새로 수행한 것도 아니다.

## 4. 기존 추천 실험16

공식 Amazon Reviews 2023 leave-last-out interaction을 사용했다. Item은 parent_asin이며 8,498 child ASIN의 이미지 예측을 parent별 평균해 7,365개 카탈로그를 만들었다.

- 공식 전체 interaction: 2,474,375개 / 전체 item: 825,869개.
- 이미지 촉감 카탈로그: 7,365개, 전체 item의 약 0.892%.
- Validation 사용자: 1,110명. Test 사용자: 3,283명.
- 기존 사용자 촉감 프로필: 과거 interaction 상품들의 이미지 촉감 확률 평균. 직접적인 like/dislike는 아니다.
- BPR Top-300 후보에 category 빈도 점수와 촉감 cosine 점수를 결합했다.
- Validation 선택: category 가중치 beta=0.15, 촉감 가중치 alpha=0.

| 실험16 방법 | Test NDCG@10 | HR@10 | MRR@10 |
|---|---:|---:|---:|
| Popularity | 0.046859 | 0.092294 | 0.032755 |
| BPR | 0.013416 | 0.024063 | 0.010165 |
| Category-aware | 0.017149 | 0.029851 | 0.013311 |
| Tactile-aware | 0.017149 | 0.029851 | 0.013311 |

Test Candidate Recall@300은 0.177277이었다. Alpha=0 때문에 category와 tactile-aware는 같은 ranking이었다.

## 5. 실험17~18: 명시적 선호 추출의 준비

실험17에서 로컬 원문 **2,500,939개 리뷰 전체**를 lexical screen으로 조사하고 공식 interaction 2,474,375개를 연결했다. 키워드가 있다는 것은 촉감 또는 명시적 선호의 정답이라는 뜻이 아니다.

실험18에서는 64개 표현을 Qwen으로 추출했다. 최초 자동 검증은 62개 통과했으며, 이후 Codex가 64개를 AI 예비 검토했다. 비교 가능한 62개 중 class 50개, state 48개, attitude 33개가 일치했다. 이것은 AI 간 일치일 뿐 human gold가 아니다.

예비 검토에서 날씨·색상의 crisp/cool, 소재가 아닌 동작의 stretching, 상품 총평과 촉감 선호의 혼동 같은 오류 후보를 확인해 실험19 prompt에 반영했다. 따라서 기존 pilot holdout을 미사용 검증 표본이라고 주장하지 않는다. 사람이 직접 하는 audit은 사용자 요청으로 생략했다.

## 6. 실험19의 데이터 범위

| 항목 | 값 |
|---|---:|
| 평가 카탈로그 | 7,365 parent 상품 |
| Validation / test 사용자 | 1,110 / 3,283 |
| 평가 사용자와 관련된 공식 키워드 리뷰 | 3,923 |
| 해당 리뷰의 고유 사용자 | 2,083 |
| 모든 lexical occurrence | 5,865 |
| Train / validation / test occurrence | 2,841 / 1,467 / 1,557 |

전체 원문은 실험17에서 조사했지만 **250만 리뷰 전체를 Qwen으로 처리한 것은 아니다.** 기존 평가 사용자에 해당하는 공식 키워드 리뷰의 모든 occurrence를 처리했다. 키워드 없는 리뷰와 카탈로그 밖 전체 Amazon 상품까지 추천 평가한 것은 아니다.

Test 표현 1,557건은 미래 리뷰 비교용으로도 추출했지만, 사용자 프로필이나 추천 점수 생성에는 포함하지 않는다. 추출한 총량과 실제 history 선호로 사용한 양은 다르다.

## 7. 실험19 처리 순서와 모델

```text
평가 사용자 관련 전체 lexical occurrence 확정 및 hash 고정
  → Qwen32B NF4로 속성·상태·태도·부위·조건·원문 근거 추출
  → schema / 허용 값 / 정확한 focal 위치를 포함하는 원문 인용 검사
  → 실패 항목만 최대 두 차례 형식 보정 재시도, 여전히 실패하면 제외
  → 추천 시점 이전 history에서 category별 명시적 선호 프로필 구성
  → validation에서 후보 생성 방식과 beta/alpha 선택·고정
  → 같은 후보를 공유하는 방법들의 test ranking 평가
  → subset / paired bootstrap / 미래 리뷰 pseudo consistency
  → 코드 테스트 결과 및 한계와 함께 보고
```

- 추출 모델: `Qwen/Qwen3-VL-32B-Instruct`.
- Revision: `0cfaf48183f594c314753d30a4c4974bc75f3ccb`.
- 4-bit NF4 double quantization + BF16 compute. VL 모델이지만 여기서는 리뷰 텍스트만 입력했다.
- A100 80GB, torch 2.5.1+cu121, transformers 5.7.0.dev0, bitsandbytes 0.49.2.
- 생성은 do_sample=False, max_new_tokens=256. 초기 batch 16에서 운영상 128로 변경해 저장된 출력부터 재개했다.
- 원문·offset·최초 응답·재시도 응답·거절 사유를 보존했다.

### 7.1 추출 결과

| 항목 | 수 |
|---|---:|
| 처리 대상 occurrence | 5,865 |
| 최초 자동 검증 실패 | 391 |
| 재시도 후 통과 | 5,540 |
| 최종 실패·제외 | 325 |
| 정확한 focal을 포함한 원문 인용 검사 실패 | 242 |
| 허용된 enum 값 위반 | 83 |

5,540은 형식과 근거 위치 검증 통과 수이지 의미적으로 맞는 라벨 수가 아니다. 남은 325개를 임의로 정답 처리하지 않았다.

| Local attitude | 수 | Property state | 수 |
|---|---:|---|---:|
| unknown | 2,694 | present | 5,055 |
| like | 1,940 | absent | 403 |
| dislike | 902 | uncertain | 63 |
| mixed | 4 | not_tactile | 19 |

선호 규칙 필터를 통과한 occurrence는 2,139개다. 이는 category 연결과 시간 필터를 적용하기 전 수이며 사용자 수가 아니다.

## 8. 사용자 선호와 점수식

### 8.1 시간·의미 필터

- Validation 프로필은 train만, test 프로필은 train+validation만 사용한다.
- Evidence timestamp는 해당 추천 시점보다 엄격히 이전이어야 한다.
- Target parent 상품은 사용자 history에서 제외한다. 이미 본 상품은 후보에서 제거한다.
- 명시적 like/dislike와 present/absent만 선호로 변환한다.
- unknown, mixed, uncertain, not_tactile, unmapped는 해당 primary 선호에서 보류한다.
- Scope는 whole_garment 또는 unknown, condition은 unknown만 허용한다. 부분·상황·타인 경험은 evidence로 보존하지만 primary에서 제외한다.
- 같은 category만 matching하고, other 및 category가 연결되지 않는 경우는 제외한다. 카테고리 간 전이 가중치는 0이다.

### 8.2 상태와 태도의 조합

| 속성 상태 | 태도 | 해당 class의 desired_presence |
|---|---|---:|
| present | like | 1 |
| present | dislike | 0 |
| absent | like | 0 |
| absent | dislike | 1 |

예를 들어 “두껍지 않아 좋다”는 thick의 낮은 확률을 선호하는 matching 방향이다. thin이라는 반대 class의 정답을 새로 생성하지 않는다. 이 변환과 조건 필터가 실제 개인의 선호를 충분히 표현하는지는 검증되지 않은 모델링 가정이다.

같은 리뷰에서 반복된 동일 class는 먼저 평균해 한 리뷰 이상의 가중치를 갖지 않게 한다. 리뷰 간 평균을 category/class별 선호로 사용한다. 충돌 평균이 0.5이면 방향성이 0이다.

### 8.3 Matching과 가중치

```text
category_score = (1-beta) × base_percentile + beta × category_percentile
B = percentile_rank(category_score within candidate set)

U = supported class 평균[
      (2 × desired_presence - 1)
      × (item_probability - 0.5)
      × n / (n + 2)
    ]

final_score = (1-alpha) × B + alpha × U
```

n은 해당 category/class의 고유 리뷰 수다. 희소 프로필의 기여를 n/(n+2)로 줄인다. 전체 후보에서 지원 evidence가 없으면 U=0이어서 순위는 category 기준선과 같다. B와 U는 값의 범위가 다르므로 alpha=0.2가 동일 척도 정보의 정확한 20% 기여라는 뜻은 아니다.

## 9. 후보 생성과 validation 선택

후보 생성은 validation Recall@300이 높은 방식을 선택했다. 동률이면 BPR이다.

| 후보 생성 | Validation Recall@300 | Validation NDCG@10 |
|---|---:|---:|
| 기존 BPR | 0.138739 | 0.005544 |
| Popularity | 0.212613 | 0.035020 |

선택된 인기도 기반 Top-300을 모든 main 방법이 공유한다. Test target을 후보에 강제로 추가하거나 target category로 후보를 제한하지 않는다.

- Beta grid: 0, 0.05, 0.1, 0.15, 0.2, 0.3, 0.5.
- Alpha grid: 0, 0.05, 0.1, 0.2, 0.3, 0.5.
- 선택 지표: validation NDCG@10, 동률이면 작은 가중치.
- Beta 선택: **0.05**. 각 branch의 alpha는 별도 선택했다.

| Branch | 설명 | 선택 alpha |
|---|---|---:|
| explicit | 명시적 like/dislike + Last2 이미지 확률 | 0.2 |
| shuffled | 다른 사용자 evidence를 수신자 cutoff로 다시 필터해 프로필 교환 | 0.5 |
| likes_only | local like만 사용, absent+like도 포함 | 0.2 |
| history_mean | 과거 상품 이미지 촉감 평균 기반 비교 | 0 |
| review_only | 이번 cohort-history 리뷰에서 만든 sparse 상품 속성 | 0.1 |
| hybrid | 리뷰 속성의 누락을 이미지로 보충 | 0.2 |

Shuffled는 seed 20260906의 단일 permutation이다. 동일 alpha 통제나 여러 shuffle에 대한 유의성 검정은 아니다. Review-only는 상품 리뷰 전체를 사용한 oracle가 아니다. 다른 사용자의 리뷰도 cutoff 이전·허용 history split만 쓰고 평가 사용자 자신을 제외한다. Hybrid는 v3 test-family 상품에 대해 항상 이미지 feature를 사용한다.

## 10. 성능평가 프로토콜과 지표 정의

사용자마다 held-out target interaction 하나를 정답으로 평가한다. 확인되지 않은 나머지 상품을 사용자가 싫어한다고 판단하는 것은 아니다.

- **HR@10**: 정답 상품이 Top-10에 포함된 사용자 비율.
- **NDCG@10**: 정답 순위 r≤10이면 1/log2(r+1), 아니면 0을 사용자별 평균. 단일 정답이므로 이상적인 DCG는 1이다.
- **MRR@10**: 정답 순위 r≤10이면 1/r, 아니면 0의 평균.
- **Candidate Recall@300**: 정답이 재정렬 후보 안에 들어온 사용자 비율.
- 후보 밖 정답은 ranking 계산에서 301로 처리한다. 이는 실제 전체 순위가 아니라 censoring이며 Top-10 지표에는 0점이다.
- 동점은 기존 후보 위치로 결정한다. Popularity 후보 생성의 동점은 정렬된 item 순서를 따른다.
- Paired bootstrap: 동일 사용자에서 branch와 category의 NDCG@10 차이를 구하고, 사용자 단위 복원추출 1,000회, seed 20260906, percentile 95% CI.
- 여러 branch/subset 비교에 대한 다중검정 보정은 없다. 독립 seed 반복 학습 결과도 아니다.

## 11. 전체 test 성능 — 3,283명

| 방법 | NDCG@10 | HR@10 | MRR@10 |
|---|---:|---:|---:|
| Base: Popularity 후보 기본 순서 | 0.046859 | 0.092294 | 0.032755 |
| Category | 0.050544 | 0.102955 | 0.034373 |
| Explicit preference | 0.050652 | 0.102955 | 0.034534 |
| Shuffled preference | 0.050299 | 0.102955 | 0.034117 |
| Likes only | 0.050676 | 0.102955 | 0.034555 |
| History mean | 0.050544 | 0.102955 | 0.034373 |
| Review only | 0.050419 | 0.102650 | 0.034291 |
| Hybrid | 0.050277 | 0.102955 | 0.034071 |
| Popularity full eligible catalog 참고선 | 0.046859 | 0.092294 | 0.032755 |

여기서 full catalog는 전체 Amazon이 아니라 7,365개 적격 카탈로그다. Test Candidate Recall@300은 **0.322875 = 1,060/3,283**이다. 2,223명의 정답은 후보 밖이므로 재정렬로 복구할 수 없다.

### 11.1 Category 대비 추가 효과

| 비교 | Δ NDCG@10 | Paired 95% CI |
|---|---:|---|
| Explicit − Category | +0.00010725 | [-0.00044850, +0.00074556] |
| Shuffled − Category | -0.00024522 | [-0.00138652, +0.00096677] |
| Likes only − Category | +0.00013177 | [-0.00042694, +0.00073530] |
| History mean − Category | 0 | [0, 0] |
| Review only − Category | -0.00012556 | [-0.00059199, +0.00027885] |
| Hybrid − Category | -0.00026759 | [-0.00113172, +0.00061196] |

Explicit의 평균은 소폭 높지만 CI가 0을 포함하고 전체 HR@10은 같다. Likes only가 test에서 가장 높다고 이를 사후 공식 선택 모델로 바꾸면 안 된다. History mean은 alpha=0으로 선택돼 category와 같다.

## 12. 실제 선호 지원 범위와 subset

| 지원 범위 | Validation | Test |
|---|---:|---:|
| 전체 사용자 | 1,110 | 3,283 |
| 프로필이 있는 사용자 | 141 | 427 |
| 후보에 category/class 지원이 있는 사용자 | 141 | 415 |
| 지원이 있는 후보의 비율 | 2.4889% | 2.4598% |
| 리뷰 feature와 매칭 지원이 있는 사용자 | 116 | 366 |

프로필 존재와 후보에 실제 적용 가능한 정보 존재는 다르다. 아래 `profile_supported`는 후자인 415명이다. 지원 class가 있어도 선호 충돌 등으로 utility가 0일 수 있다.

| Test subset | n | Category NDCG@10 | Explicit NDCG@10 | Δ의 95% CI |
|---|---:|---:|---:|---|
| 전체 | 3,283 | 0.050544 | 0.050652 | [-0.00044850, +0.00074556] |
| Profile supported | 415 | 0.055220 | 0.056069 | [-0.00365497, +0.00587167] |
| 정답이 Top-300에 포함 | 1,060 | 0.156545 | 0.156877 | [-0.00147705, +0.00233458] |
| 이미지 학습에서 제외된 family target | 410 | 0 | 0 | [0, 0] |
| Review feature supported | 366 | 0.053527 | 0.054131 | [-0.00500321, +0.00611605] |

지원 subset은 조건부 진단이며 전체 평가를 대체하지 않는다. 410명 subset의 Top-10 지표가 모든 방법에서 0이라고 Last2의 속성 예측력이 0이라는 뜻은 아니다. 이 표만으로 후보 검색 실패와 재정렬 실패를 분리할 수 없다. 또한 이 subset은 image-training-unseen family이지, 상호작용까지 없는 신규 상품 또는 전역 시간 누수 없는 cold-start의 증거가 아니다.

## 13. 미래 리뷰와의 비교

가중치 선택 이후 과거 프로필과 held-out 미래 리뷰의 동일 category/class 선호를 비교했다.

- 지원: 22명, 24개 user/category/class pair.
- 선호 방향 동률 제외 후 24개, Qwen 추출 간 방향 일치 24/24.
- 추천 점수와 가중치 선택에는 사용하지 않았다.

이 100%는 같은 Qwen으로 추출한 선택된 작은 교집합의 pseudo-label consistency다. 독립적인 정답 정확도·전체 사용자 선호 예측 정확도·촉감 만족도가 아니다. 이 수치로 논문의 성공을 주장할 수 없다.

## 14. 코드 테스트와 보존 검증

기록된 실행 로그: `logs/tests.log`, **Ran 11 tests / OK**.

1. Absent+like가 같은 class의 낮은 확률을 보상하는지.
2. Unknown/mixed/uncertain/not_tactile/조건/부위/타인/unmapped를 보류하는지.
3. 다른 category와 누락된 review feature가 기여하지 않는지.
4. 합성 데이터로 선호 프로필 → component 생성이 동작하는지.
5. 후보에 없는 정답을 강제로 넣지 않는지.
6. 인용이 단순히 같은 단어가 아니라 선택된 정확한 occurrence를 포함하는지.
7. 동일 리뷰의 반복 표현이 리뷰 수 가중치를 부풀리지 않는지.
8. Review item feature에서 본인·미래·test evidence를 제외하는지.
9. Property state와 attitude 조합이 분리돼 처리되는지.
10. Split·timestamp·target history 제외 규칙이 적용되는지.
11. Alpha=0 및 전체 후보에 프로필 지원 없음에서 기준 순위가 유지되는지.

실제 평가 시에도 사용자 시간 검사와 seen-item 검사를 통과했다. `protocol.json`에 지정한 12개 입력 hash가 동일함을 확인했다. 이는 보호 대상으로 지정한 파일의 검증이며 원문과 프로젝트 전체 파일에 대한 전수 hash 검증이라는 뜻은 아니다.

## 15. 기존 결과와 비교할 때 지켜야 할 것

| 항목 | 실험16 | 실험19 |
|---|---|---|
| Primary 사용자 촉감 프로필 | 과거 상품 이미지 확률 평균 | 과거 리뷰의 명시적 local like/dislike |
| Primary 후보 생성 | BPR | Popularity, validation에서 선택 |
| Category beta | 0.15 | 0.05 |
| Primary tactile alpha | 0 | 0.2 |
| Test Recall@300 | 0.177277 | 0.322875 |
| Category NDCG@10 | 0.017149 | 0.050544 |
| Primary tactile NDCG@10 | 0.017149 | 0.050652 |
| 내부 category 대비 차이 | 0 | +0.00010725, CI에 0 포함 |

실험16→19 전체 수치 상승에는 후보 생성·가중치·점수식 변경이 동시에 포함된다. 그 차이를 명시적 촉감 선호만의 효과로 귀속하면 안 된다. 가장 직접적인 비교는 **실험19 내부 explicit vs category**다.

## 16. 해석의 한계와 현재 가능한 결론

관찰된 사실:

- 이미지 모델은 같은 category 안에서도 리뷰-derived 촉감 target을 구별하는 신호를 보였다.
- 명시적 선호의 실제 추천 후보 지원 범위는 작았다.
- Validation은 explicit alpha>0을 선택했지만 test의 추가 개선은 작고 불확실했다.
- History mean은 이번에도 alpha=0이 선택됐다.
- Review-only와 hybrid는 전체 평균에서 category보다 낮았지만 차이의 CI는 0을 포함했다.

검증되지 않은 가설:

- 추출 오류, 희소 history, 추천 후보 검색 한계, 엄격한 조건 필터, 약한 점수 보정이 작은 효과의 원인일 수 있다. 각각의 인과적 원인은 이 실험만으로 확정되지 않았다.

필수 한계:

- 사람 검증 없음. 형식 통과는 의미 정확도를 보증하지 않는다.
- 이미 앞선 실험에서 열람한 cohort를 재사용했다. Validation에서만 가중치를 골랐어도 새 독립 확증 test는 아니다.
- 사용자별 history는 시간 필터를 적용했지만 기존 Last2 학습 데이터와 집단 추천 학습 데이터 전체가 전역 시간 cutoff 기준으로 재구축된 것은 아니다.
- 카탈로그는 제한적이고 lexical screen 밖 촉감 표현의 recall도 측정하지 않았다.
- 조건·부위·타인 경험의 자동 추출 자체에도 오류가 있을 수 있다.
- Category-local 추천과 같은-category human pairwise 만족도 평가는 다르며 후자는 미수행이다.
- 실제 만족도, interaction-cold-start 효용, 대규모 온라인 추천 개선은 입증하지 않았다.

권장 결론 문장:

> 현재 Amazon Fashion의 제한된 카탈로그와 탐색 프로토콜에서 이미지 촉감 표현 및 명시적 리뷰 선호를 추천에 연결하는 파이프라인을 구현했다. 명시적 선호 기반 재정렬은 category 기준선보다 평균 NDCG@10이 소폭 높았지만, bootstrap 신뢰구간이 0을 포함해 추가 효용을 확실히 확인하지 못했다. 사람 검증이 없는 추출 라벨, 희소한 선호 지원, 후보 검색 및 시간 프로토콜의 한계 때문에 실제 촉감 만족도나 일반적인 추천 개선으로 확대 해석할 수 없다.

## 17. 근거 파일과 재현 정보

프로젝트 루트: `/home/user/onsesang/material_span_grounding`.

이번 문서는 기존 산출물을 읽어 정리한 것이며, 작성 과정에서 추론·학습·가중치 선택·성능평가를 다시 실행하지 않았다. 표의 성능은 표시 목적의 반올림 값이며 원래 정밀도는 JSON에 보존돼 있다.

| 근거 | 프로젝트 기준 상대 경로 |
|---|---|
| 최종 성능·CI·coverage·한계 | experiments/19_explicit_preference_exploratory/artifacts/results.json |
| 고정 표본·모델·원문 hash·prompt | experiments/19_explicit_preference_exploratory/artifacts/protocol.json |
| 평가 규칙 | experiments/19_explicit_preference_exploratory/artifacts/evaluation_protocol.json |
| 후보/가중치 선택 | experiments/19_explicit_preference_exploratory/artifacts/candidate_selection.json 및 selection.json |
| 전체 validation 탐색 | experiments/19_explicit_preference_exploratory/artifacts/validation_search.csv |
| 사용자별 순위 | experiments/19_explicit_preference_exploratory/artifacts/per_user_results.csv |
| 점수 분해 예시 | experiments/19_explicit_preference_exploratory/artifacts/score_breakdowns.json |
| 원문 evidence | experiments/19_explicit_preference_exploratory/artifacts/validated_evidence.parquet |
| 코드 테스트 로그 | experiments/19_explicit_preference_exploratory/logs/tests.log |
| 기존 추천 실험 | experiments/16_recommendation_reranking/notion/RECOMMENDATION_RERANKING_RESULTS.md |
| Category-only 속성 예측 | experiments/13_category_only_baseline/notion/CATEGORY_ONLY_BASELINE_RESULTS.md |
| Same-category 속성 평가 | experiments/14_same_category_evaluation/notion/SAME_CATEGORY_EVALUATION_RESULTS.md |
| v2/v3 배경과 FashionCLIP ablation | experiments/12_class_multilabel_fashionclip_ft/notion/WSDM_Tactile_Aware_Recommendation_Codex_Handoff.md |

원 실험의 실행 순서(이미 완료됨):

```bash
cd /home/user/onsesang/material_span_grounding/experiments/19_explicit_preference_exploratory
# 아래 python은 miniconda3/envs/texture/bin/python 환경을 의미한다.
python pipeline.py prepare
python evaluate.py candidates
python pipeline.py infer
python pipeline.py repair
python pipeline.py repair
python -m unittest -v test_preference.py
python evaluate.py evaluate
python write_report.py
```

단순 결과 검토에는 재실행할 필요가 없다. 새로운 프로토콜·prompt·가중치 탐색은 기존 파일을 덮어쓰지 않고 별도 버전에서 진행해야 한다.
