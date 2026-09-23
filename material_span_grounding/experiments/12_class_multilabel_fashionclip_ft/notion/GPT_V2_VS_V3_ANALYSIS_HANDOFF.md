# GPT 분석 요청용 전달 문서: 기존 v2 Phase 0–11 vs atomic-class v3

## GPT에게 요청할 작업

아래에 제공된 사실과 수치를 바탕으로 한국어 연구 분석 보고서를 작성해 주세요.

1. 기존 v2 실험과 이번 v3 실험의 목적, 라벨 표현, Qwen grounding, 이미지 모델 학습 방식, 평가 방식의 차이를 설명해 주세요.
2. 이번 v3 실험의 전체 흐름을 데이터 입력부터 locked-test 평가까지 단계별로 재구성해 주세요.
3. v3의 전체 ablation과 class별 결과를 분석하고, 어떤 regime이 무엇을 개선하거나 악화시켰는지 설명해 주세요.
4. 기존 v2 결과와 v3 결과를 비교하되, 서로 다른 task와 metric을 같은 숫자처럼 직접 비교하지 마세요.
5. 결과가 지지하는 결론, 아직 지지하지 못하는 결론, 오류 가능성, class imbalance, category shortcut, pseudo-label 한계를 구분해 주세요.
6. 다음 실험의 우선순위를 구체적인 ablation 및 평가 설계와 함께 제안해 주세요.

답변에서는 다음 표기를 권장합니다.

- **관측 사실**: 아래 산출물에서 직접 확인되는 내용
- **해석**: 관측 사실로부터 가능한 설명
- **추가 검증 필요**: 현재 실험만으로 확정할 수 없는 주장

중요한 비교 규칙:

- v2는 bipolar axis의 방향 target을 예측하는 회귀/순위 문제이고 주 지표는 축별 Spearman이다.
- v3는 atomic class의 masked multi-label classification이고 주 지표는 macro/micro F1과 average precision이다.
- 따라서 v2 Spearman과 v3 F1/AP의 절대값을 직접 비교해 어느 실험이 더 우수하다고 결론 내리면 안 된다.
- locked test에서 우연히 더 높은 모델을 사후 선택하지 말고, development 기준으로 미리 선택된 모델을 주 결과로 유지해야 한다.
- 두 실험 모두 사람이 검증한 ground truth가 아니라 Qwen pseudo-label 기반 feasibility 실험이다.

---

## 1. 공통 데이터 기반과 누수 방지

두 실험은 동일한 전체 적격 Amazon Fashion 풀과 동일한 family-disjoint split을 사용한다.

| 항목 | 값 |
|---|---:|
| 전체 상품 | 8,498 ASIN |
| 선택 리뷰 | 70,943 |
| lexical high-recall candidate span | 26,126 |
| train | 6,300 ASIN / 5,295 family |
| development | 1,077 ASIN / 1,035 family |
| locked test | 1,121 ASIN / 1,035 family |
| family 중복 | 0 |

- split 단위는 ASIN이 아니라 parent product family다.
- 기존 v1에 등장했던 family 471개는 train에만 강제 배치했다.
- test는 taxonomy, threshold, hyperparameter, fine-tuning depth 선택에 사용하지 않았다.
- v3는 v2의 원문 리뷰, 원래 span, open-vocabulary claim, Phase 0–11 산출물을 수정하거나 재실행하지 않고 파생 표현을 별도 실험 디렉터리에 만들었다.

## 2. 핵심 설계 차이

| 차원 | 기존 v2 Phase 0–11 | 이번 v3 atomic-class 실험 |
|---|---|---|
| 연구 질문 | 리뷰에서 얻은 bipolar 촉감 방향을 이미지에서 회귀/순위 예측할 수 있는가 | 독립 atomic 촉감 class를 이미지에서 masked multi-label로 예측할 수 있는가 |
| 의미 표현 | 7개 bipolar axis, 방향 중심 `-1/0/+1`; 강도는 진단용 보존 | 14개 atomic class: soft, firm, smooth, rough, non_elastic, elastic, thin, thick, flexible, stiff, warm, cool, spongy, crisp |
| 구조 | `soft ↔ firm`처럼 두 pole이 하나의 축을 공유 | 각 pole이 독립 output class이며 한 span에서 여러 class 허용 |
| Qwen | `Qwen3-VL-8B-Instruct` | `Qwen3-VL-32B-Instruct`, official BF16 snapshot을 로딩 시 bitsandbytes NF4 4-bit double quantization, BF16 compute로 양자화 |
| Qwen 입력 범위 | reviewer-first 대표 8,641개 구절; 상품별 결정론적 대표 축 및 제한된 second-reviewer sample | lexical candidate 26,126개 전부 |
| Qwen 출력 | mappable, axis, direction, intensity, scope, confidence의 제한 코드 | class별 present/absent/confidence 목록과 unmappable flag |
| 유효 grounding | 5,710 mapped, 2,931 rejected | 26,126개 응답 모두 구문 검증 완료; 초기 parse 오류 24건 재질의 후 0건 |
| 미언급 처리 | axis mask=0, `REVIEW_UNOBSERVED` | class mask=0; negative로 취급하지 않음 |
| negative 생성 | bipolar direction target | 명시적 absent는 해당 class의 negative. present class만 설정된 배타 counterpart에 negative supervision을 제공하며, absent에서 반대 class를 추론하지 않음 |
| reviewer aggregation | 같은 reviewer의 span을 먼저 축약한 뒤 상품 수준 평균 | 같은 reviewer/class의 span을 confidence-weighted 평균한 뒤 상품/class 수준 confidence-weighted 평균 |
| 이미지 encoder | FashionCLIP과 DINO를 모두 freeze하여 embedding 추출 | FashionCLIP에 head를 붙이고 freeze 깊이를 바꾸는 5개 ablation |
| downstream | category-only, linear, Ridge, image+category Ridge, ordinal, pairwise, tiny MLP | masked BCE classification head; frozen, projection, last1, last2, full |
| 주 평가 | 축별 Spearman, MAE, direction/pairwise accuracy | observed pair에서 class별 precision/recall/F1, macro/micro F1, macro AP, AUROC 가능 시 계산 |
| 추가 평가 | 외부 전이, abstention/risk-coverage, tactile retrieval | 이번 실행에는 외부 전이, abstention, retrieval 비교가 없음 |

### 표현 변경의 의미

- v2는 두 pole의 순서와 반대 관계를 하나의 연속적/순서적 축으로 모델링한다.
- v3는 각 pole을 별도 class로 예측하므로 multi-label 표현과 class별 오류 분석이 쉽지만, 축의 순서 구조와 방향 거리 정보는 직접 사용하지 않는다.
- v3의 atomic class는 원래 open-vocabulary evidence를 대체하지 않는 파생 표현이다.
- v2에서 support gate를 통과하지 못한 `sponginess` 축도 v3에서는 `spongy`, `crisp` class로 남겼다. 다만 매우 희소하므로 결과가 불안정하다.

## 3. 기존 v2 실험 흐름

1. 전체 데이터 census와 family-safe train/development/locked-test split 생성.
2. 70,943개 리뷰에서 lexical high-recall 방식으로 26,126개 candidate span 보존.
3. reviewer-first 대표 8,641개 구절을 Qwen3-VL-8B가 문맥 검증.
4. 5,710개를 axis/direction에 mapping하고 2,931개를 거절. 21건은 명백한 코드 위치 오류를 결정론적으로 교정하고, 복원 불가능한 3건은 unmappable로 처리.
5. train-only coverage/pole/reviewer/category/confidence gate로 active axis 선택.
6. reviewer-first product-axis target 생성. 미언급은 중립 0이 아니라 mask=0.
7. 모든 상품 이미지에서 frozen FashionCLIP과 frozen DINO feature 추출.
8. category-only, 선형/Ridge, image+category, ordinal, pairwise, tiny MLP 비교.
9. MLLM-Fabric 외부 전이, confidence/recoverability 기반 abstention, same-category retrieval 평가.
10. development에서 선택하고 locked family test에서 최종 보고.

### v2 label 및 coverage

| 축 | pole | train mapped span | 상품 | 상태 |
|---|---|---:|---:|---|
| softness | soft ↔ firm | 488 | 476 | ACTIVE |
| surface_texture | smooth ↔ rough | 160 | 152 | ACTIVE |
| elasticity | non_elastic ↔ elastic | 2,001 | 1,928 | ACTIVE |
| thickness | thin ↔ thick | 1,167 | 1,139 | ACTIVE |
| flexibility | flexible ↔ stiff | 98 | 91 | ACTIVE |
| warmth | warm ↔ cool | 317 | 293 | ACTIVE |
| sponginess | spongy ↔ crisp | 2 | 2 | INACTIVE |

- 관측 product-axis pair: 5,482
- 미관측 product-axis pair: 45,506
- reviewer-axis record: 5,680

## 4. 기존 v2 주요 결과

아래 표는 locked family test의 축별 Spearman이다.

| 방법 | softness | surface_texture | elasticity | thickness | flexibility | warmth |
|---|---:|---:|---:|---:|---:|---:|
| category_only | 0.071 | 0.396 | 0.328 | 0.086 | -0.297 | -0.009 |
| fashionclip_linear | 0.024 | -0.040 | 0.340 | 0.251 | 0.018 | -0.161 |
| fashionclip_ridge | 0.071 | -0.066 | 0.356 | 0.322 | 0.092 | -0.110 |
| image_category_ridge | 0.079 | -0.093 | 0.364 | 0.318 | 0.129 | -0.087 |
| dino_ridge | -0.058 | -0.423 | 0.357 | 0.249 | 0.314 | -0.069 |
| ordinal | 0.089 | -0.026 | 0.260 | 0.264 | 0.092 | 0.018 |
| pairwise | 0.046 | -0.053 | 0.192 | 0.241 | 0.092 | 0.018 |
| tiny_mlp | 0.019 | 0.040 | 0.327 | 0.303 | 0.351 | 0.060 |

해석 시 중요한 v2 관측:

- elasticity와 thickness는 여러 이미지 모델에서 양의 Spearman이 비교적 일관되었다.
- softness와 surface_texture는 이미지 모델이 category-only를 안정적으로 넘지 못했다.
- flexibility는 tiny MLP 0.351, DINO Ridge 0.314였지만 support 자체가 작다.
- warmth는 대부분 0 근처 또는 음수여서 시각 신호가 약했다.
- category-only보다 못하면 이미지가 촉감이 아니라 상품 category shortcut을 학습했을 가능성을 배제할 수 없다.

추가 결과:

| 선택적 예측 방법 | AURC↓ | nominal 80%의 실제 coverage | 해당 risk(MAE)↓ |
|---|---:|---:|---:|
| confidence_only | 0.601 | 0.776 | 0.659 |
| recoverability_only | 0.763 | 0.925 | 0.672 |
| product | 0.717 | 0.806 | 0.670 |
| learned_calibrator | 0.621 | 0.773 | 0.648 |

review-cold-start retrieval은 locked test에서 query가 10개뿐이었다. 주요 NDCG@10은 category-only 0.504, proposed calibrator u0 0.642, structured no-abstention 0.656이었다. 표본이 매우 작고 bootstrap CI가 넓다.

## 5. 이번 v3 실험 흐름

### Stage A — 입력과 schema 동결

- 동일한 8,498개 상품, 26,126개 candidate span, family-disjoint split을 재사용.
- 원문과 open-vocabulary span은 보존하고 14개 atomic class를 파생 schema로 추가.
- exclusive pair: soft/firm, smooth/rough, non_elastic/elastic, thin/thick, flexible/stiff, warm/cool, spongy/crisp.

### Stage B — Qwen32B 전체 span grounding

- 모델: `Qwen/Qwen3-VL-32B-Instruct`
- revision: `0cfaf48183f594c314753d30a4c4974bc75f3ccb`
- official snapshot을 bitsandbytes NF4 4-bit, double quantization, BF16 compute로 로딩.
- batch size 128, input 최대 768 token, output 최대 80 token, deterministic decoding.
- 모든 26,126개 span에 대해 material tactile evidence만 보수적으로 class mapping.
- fit, size, 일반적 comfort/quality/appearance, 환경 온도, 신체 감각은 명시적 소재 촉감 근거가 없으면 거절.
- 최초 parse 오류 24건을 별도 repair 단계에서 재질의하여 잔여 오류 0건.

### Stage C — reviewer-first masked target

- confidence 0.55 미만 evidence 제외.
- 한 reviewer가 같은 class를 여러 번 언급해도 먼저 reviewer 수준에서 confidence-weighted 평균.
- 그 다음 product-class 수준에서 reviewer 결과를 confidence-weighted 평균.
- 명시적으로 관측되지 않은 product-class는 값 0이 아니라 mask=0.
- present class는 설정된 exclusive counterpart에만 negative를 생성.
- 최종 관측 product-class pair: 34,168.

### Stage D — FashionCLIP fine-tuning ablation

공통 설정:

- FashionCLIP revision: `7e3ba62ce16b379a1ab479346b66f192e76f51b7`
- batch size 128, 최대 30 epoch, patience 5, seed 20260903.
- masked binary cross entropy 사용.
- train의 class imbalance를 반영한 positive weight를 사용하되 0.25~4.0으로 clip.
- class threshold는 development에서 0.10~0.90 범위를 0.05 간격으로 탐색해 class별 F1이 최대가 되도록 결정.
- head learning rate `1e-4`, projection `2e-5`, vision encoder `3e-6`, weight decay `0.01`.

| regime | 학습되는 부분 |
|---|---|
| frozen | 새 14-class linear head만 학습; FashionCLIP vision encoder와 visual projection 동결 |
| projection | head + visual projection 학습; encoder 동결 |
| last1 | head + projection + 마지막 vision transformer block 1개 + post-layernorm |
| last2 | head + projection + 마지막 vision transformer block 2개 + post-layernorm |
| full | head + projection + 전체 vision encoder |

### Stage E — model selection과 locked test

- regime 선택 기준은 development macro-F1 하나이며 `last2`가 선택됨.
- locked test는 선택에 사용하지 않고 최종 보고에만 사용.
- 모든 metric은 mask=1인 observed product-class pair에서만 계산.

## 6. v3 target 분포

| class | 전체 positive pair | 전체 negative pair | locked-test observed | locked-test positive |
|---|---:|---:|---:|---:|
| soft | 4,588 | 305 | 656 | 618 |
| firm | 87 | 4,608 | 631 | 12 |
| smooth | 600 | 594 | 154 | 88 |
| rough | 555 | 649 | 159 | 64 |
| non_elastic | 161 | 2,919 | 419 | 21 |
| elastic | 2,851 | 536 | 463 | 390 |
| thin | 3,286 | 1,675 | 667 | 461 |
| thick | 1,623 | 3,345 | 667 | 197 |
| flexible | 384 | 479 | 109 | 49 |
| stiff | 459 | 462 | 117 | 54 |
| warm | 1,412 | 524 | 221 | 157 |
| cool | 500 | 1,397 | 216 | 64 |
| spongy | 24 | 58 | 13 | 1 |
| crisp | 39 | 48 | 14 | 10 |

주의: negative 중 상당수는 반대 class의 명시적 present에서 exclusive-pair 규칙으로 생성되었다. 특히 `firm`, `non_elastic` 등은 positive가 극히 적고 반대 pole에서 파생된 negative가 많다. 이것은 class별 F1과 macro-F1의 변동성을 크게 만든다.

## 7. v3 ablation 결과

| regime | best epoch | Dev macro-F1 | Test macro-F1 | Test micro-F1 | Test macro-AP |
|---|---:|---:|---:|---:|---:|
| frozen | 7 | 0.6294 | 0.5784 | 0.7621 | 0.5607 |
| projection | 9 | 0.6631 | **0.6166** | 0.7824 | 0.6143 |
| last1 | 21 | 0.6922 | 0.6050 | 0.8145 | **0.6412** |
| last2 | 28 | **0.6975** | 0.6010 | **0.8216** | 0.6232 |
| full | 17 | 0.6736 | 0.5801 | 0.8066 | 0.6073 |

development 기준 사전 선택 결과:

- 선택 모델: `last2`
- 선택 모델 locked-test macro-F1: 0.6010
- 선택 모델 locked-test micro-F1: 0.8216
- 선택 모델 locked-test macro-AP: 0.6232

### frozen 대비 locked-test 변화

| regime | macro-F1 변화 | micro-F1 변화 | macro-AP 변화 |
|---|---:|---:|---:|
| projection | +0.0382 | +0.0204 | +0.0537 |
| last1 | +0.0266 | +0.0524 | +0.0805 |
| last2 | +0.0227 | +0.0595 | +0.0625 |
| full | +0.0017 | +0.0445 | +0.0466 |

중요한 해석 경계:

- development macro-F1로 선택된 `last2`를 공식 선택 모델로 유지해야 한다.
- test macro-F1만 보면 `projection`이 0.6166으로 가장 높지만 이를 보고 사후에 공식 모델을 바꾸면 locked-test selection leakage가 된다.
- test macro-AP는 `last1`, test micro-F1은 `last2`, test macro-F1은 `projection`이 각각 최고다. 하나의 regime이 모든 지표에서 우월하지 않다.
- encoder를 더 많이 열수록 항상 좋아지지 않았다. `full`은 frozen보다 micro-F1/AP는 높지만 macro-F1 개선이 거의 없고, partial fine-tuning보다 낮다.
- development-test macro-F1 차이는 frozen 약 0.0510, projection 0.0466, last1 0.0872, last2 0.0965, full 0.0934다. 깊은 fine-tuning에서 일반화 간극이 더 컸다는 관측은 가능하지만, 원인을 과적합 하나로 단정하려면 추가 seed와 category 분석이 필요하다.

## 8. 선택 모델(last2)의 class별 locked-test 결과

| class | observed | positive | precision | recall | F1 | AP |
|---|---:|---:|---:|---:|---:|---:|
| soft | 656 | 618 | 0.9421 | 1.0000 | 0.9702 | 0.9541 |
| firm | 631 | 12 | 0.0000 | 0.0000 | 0.0000 | 0.0538 |
| smooth | 154 | 88 | 0.5915 | 0.9545 | 0.7304 | 0.7303 |
| rough | 159 | 64 | 0.4406 | 0.9844 | 0.6087 | 0.6064 |
| non_elastic | 419 | 21 | 0.1000 | 0.0476 | 0.0645 | 0.0891 |
| elastic | 463 | 390 | 0.8423 | 1.0000 | 0.9144 | 0.8923 |
| thin | 667 | 461 | 0.7303 | 0.9458 | 0.8242 | 0.8716 |
| thick | 667 | 197 | 0.5593 | 0.5025 | 0.5294 | 0.5519 |
| flexible | 109 | 49 | 0.5385 | 0.8571 | 0.6614 | 0.6533 |
| stiff | 117 | 54 | 0.4649 | 0.9815 | 0.6310 | 0.6488 |
| warm | 221 | 157 | 0.8122 | 0.9363 | 0.8698 | 0.9037 |
| cool | 216 | 64 | 0.6047 | 0.8125 | 0.6933 | 0.7718 |
| spongy | 13 | 1 | 0.1667 | 1.0000 | 0.2857 | 0.2000 |
| crisp | 14 | 10 | 0.6667 | 0.6000 | 0.6316 | 0.7974 |

관측만으로 말할 수 있는 사항:

- `soft`, `elastic`, `warm`, `thin`은 선택 모델에서 높은 F1/AP를 보였다.
- `firm`과 `non_elastic`은 positive가 각각 12개와 21개뿐이며 성능이 매우 낮다.
- `spongy`는 positive가 1개뿐이라 recall 1.0이나 F1 0.2857을 일반화 성능으로 해석하면 안 된다.
- 여러 class에서 recall이 precision보다 훨씬 높다. class별 development F1 threshold와 불균형 target이 함께 영향을 줬을 수 있다.
- macro-F1은 극희소 class도 동일 가중치로 평균하므로 `firm`, `non_elastic`, `spongy`의 영향이 크다. micro-F1은 빈도가 높은 class에 더 큰 영향을 받는다.

## 9. v2와 v3를 비교할 때 가능한 결론

### 비교 가능한 설계 수준의 변화

1. Qwen annotation capacity가 8B에서 32B로 커졌고, 대표 구절 일부가 아니라 candidate span 전체를 처리했다.
2. 축마다 한 방향값을 예측하던 문제를 14개 독립 class의 masked multi-label 문제로 바꿨다.
3. FashionCLIP을 frozen feature extractor로만 쓰던 것에서 projection/마지막 block/전체 encoder까지 fine-tuning하는 비교로 확장했다.
4. 두 실험 모두 reviewer-first와 unobserved mask 원칙, family-disjoint split, development-only selection을 유지했다.
5. v3에서는 frozen head 대비 partial fine-tuning이 대부분의 분류 지표를 개선했지만 full fine-tuning은 partial보다 좋지 않았다.

### 직접 비교하면 안 되는 사항

1. v2 축별 Spearman과 v3 class별 F1/AP의 크기를 직접 대조할 수 없다.
2. v3의 observed pair 34,168과 v2의 5,482는 annotation 범위와 negative 생성 규칙이 다르므로 단순히 6.2배 더 많은 ground truth라고 부르면 안 된다.
3. Qwen32B가 Qwen8B보다 의미 정확도가 높다고 현재 결과만으로 단정할 수 없다. 동일 span에 대한 사람 annotation 또는 blind paired audit가 없다.
4. v3가 v2보다 실제 tactile retrieval에 더 좋다고 말할 수 없다. v3에서는 retrieval 실험을 실행하지 않았다.
5. v3가 category shortcut을 극복했다고 말할 수 없다. v3에는 동일 target을 사용한 category-only baseline과 category-stratified/same-category 결과가 최종 산출물에 없다.

## 10. 해석상 핵심 쟁점

### A. representation 개선과 label noise가 함께 변했다

v3는 axis를 atomic class로 분해했을 뿐 아니라 Qwen 크기, 처리 span 수, prompt, negative 생성 규칙까지 동시에 바뀌었다. 성능 차이를 class 표현 하나의 효과로 분리하려면 같은 Qwen annotation을 사용한 axis-vs-class controlled ablation이 필요하다.

### B. partial fine-tuning은 유망하지만 선택 불확실성이 있다

partial regime은 frozen 대비 개선됐지만 `projection`, `last1`, `last2`의 순위가 metric과 split에 따라 달라진다. 단일 seed 결과이므로 여러 seed와 bootstrap CI 없이 작은 차이를 확정적으로 서열화하면 안 된다.

### C. exclusive-pair negative가 불균형을 증폭할 수 있다

예를 들어 soft present가 firm negative를 만들기 때문에 soft/firm처럼 언급 빈도가 크게 다른 쌍에서는 한쪽 negative가 압도적으로 많아진다. 이 negative는 논리적으로 합리적일 수 있지만, 실제 상품이 문맥/부위에 따라 양쪽 특성을 가질 가능성과 span scope 충돌을 검토해야 한다.

### D. full fine-tuning의 부진

full은 train loss가 계속 감소했으나 development 성능이 partial보다 낮았다. 가능한 가설은 작은 observed support, pseudo-label noise, class imbalance, 학습률/정규화 부족, category shortcut, pretrained representation 훼손이다. 현 결과는 이 가설들 중 하나를 확정하지 않는다.

### E. human validation은 여전히 핵심 병목

두 실험 모두 pseudo-label feasibility 결과다. 특히 rare pole, negation, 소재가 아닌 fit/comfort 표현, 서로 다른 garment part/scope, exclusive-pair negative의 타당성을 사람이 확인해야 한다.

## 11. 현재 산출물에 없는 평가

v3 protocol에는 calibration/coverage와 category-stratified 결과가 primary metric 후보로 기록되어 있지만, 현재 최종 `fashionclip_results.json`과 Notion 보고서에는 다음이 포함되지 않는다.

- calibration error, reliability diagram 또는 risk-coverage
- category-only baseline
- category-stratified 또는 same-category 성능
- 여러 random seed와 bootstrap confidence interval
- v3 외부 데이터 전이
- v3 selective prediction/abstention
- v3 tactile retrieval
- Qwen8B와 Qwen32B의 동일 표본 human-audited 비교

따라서 GPT의 분석에서는 이를 완료된 결과처럼 서술하지 말고 후속 실험으로 구분해야 한다.

## 12. 권장 후속 실험 우선순위

1. 고정 stratified human audit: rare class, negation, opposite-pair 충돌, scope별 표본을 포함해 Qwen8B/32B와 사람 label을 blind 비교.
2. 동일 pseudo-label로 axis head와 atomic multi-label head를 같은 FashionCLIP backbone에서 비교해 representation 효과만 분리.
3. v3 category-only 및 image+category baseline과 same-category 평가 추가.
4. `projection`, `last1`, `last2`를 여러 seed로 반복하고 paired bootstrap CI 및 per-class variance 보고.
5. rare pole을 위한 sampling/weighted loss/focal loss/class-balanced loss 비교. 단, locked test 분포와 threshold는 유지.
6. independent sigmoid 외에 exclusive-pair consistency regularizer 또는 pair-structured head를 비교하되, multi-part 상품의 양립 가능성을 허용하는 설계 사용.
7. calibration 및 selective prediction을 추가하고 v2의 abstention 프레임과 task에 맞게 연결.
8. v3 output을 동일한 review-cold-start retrieval protocol에 넣어 downstream utility를 직접 비교.

## 13. 재현성과 검증 상태

- v3 grounding records: 26,126개, unique span ID 26,126개.
- parse repair: 24개 복구, remaining 0.
- v3 products: 8,498개.
- v3 regimes: frozen, projection, last1, last2, full 모두 완료.
- v3 단위 테스트: 3/3 통과.
- 기존 v2 핵심 원본/산출물 해시는 실험 후에도 이전 보고 값과 일치했다.
- v3 config SHA-256: `53c522998b844aac55fefacad14d7f23b59283318248920d6a52d5b378a580f5`
- v3 groundings SHA-256: `7a43d29f51e272b6f23bb42bb8b9108f967811e298de542e88b5ac7f6232a691`
- v3 targets SHA-256: `6329a65e11e1845fb527845e17c0b7e5fda3760813d0510693c549a192737db1`

## 14. 원본 근거 파일 경로

GPT가 로컬 파일에 접근할 수 있다면 아래 파일을 우선 확인한다. 접근할 수 없다면 본 문서의 내장 수치만 사용한다.

### 기존 v2

- `tactile_coldstart_qwen_v2_full/notion/TACTILE_COLDSTART_V2_FULL_PHASE_0_TO_11.md`
- `tactile_coldstart_qwen_v2_full/artifacts/phase11_paper_results.json`
- `tactile_coldstart_qwen_v2_full/artifacts/phase6_7_model_results.json`
- `tactile_coldstart_qwen_v2_full/artifacts/phase9_selective_results.json`
- `tactile_coldstart_qwen_v2_full/artifacts/phase10_retrieval_results.json`
- `tactile_coldstart_qwen_v2_full/configs/experiment.yaml`

### 이번 v3

- `experiments/12_class_multilabel_fashionclip_ft/PROTOCOL.md`
- `experiments/12_class_multilabel_fashionclip_ft/config.json`
- `experiments/12_class_multilabel_fashionclip_ft/artifacts/fashionclip_results.json`
- `experiments/12_class_multilabel_fashionclip_ft/manifests/ground_classes.json`
- `experiments/12_class_multilabel_fashionclip_ft/manifests/repair_groundings.json`
- `experiments/12_class_multilabel_fashionclip_ft/manifests/build_targets.json`
- `experiments/12_class_multilabel_fashionclip_ft/manifests/train_fashionclip.json`
- `experiments/12_class_multilabel_fashionclip_ft/notion/TACTILE_CLASS_MULTILABEL_QWEN32B_FASHIONCLIP_FT.md`

## 15. 최종 답변 형식 제안

1. Executive summary
2. 기존 v2와 v3의 차이 표
3. v3 end-to-end 실험 흐름
4. v3 ablation 결과 분석
5. class별 성공/실패 분석
6. v2와 v3의 공정한 비교
7. 결론의 증거 수준과 한계
8. 우선순위가 있는 다음 실험 계획

