# 촉감 기반 의류 검색·추천 프로젝트 — 전체 실험 인수인계 (GPT용)

> 작성일: 2026-09-17
> 프로젝트 경로: `/home/user/onsesang/material_span_grounding`
> 이 문서 하나로 실험 01~21과 서비스 구현까지의 현재 상태가 모두 전달되도록 작성했다.
> 이전 버전 `CHATGPT_HANDOFF.md`(2026-08-20)는 실험 15까지만 반영돼 있으므로 이 문서가 대체한다.

---

## 0. GPT가 먼저 읽어야 할 지시사항

나는 이 프로젝트의 연구 방향, 실험 해석, 논문 프레이밍, 남은 실험 설계를 계속 논의하고 싶다. 아래 내용을 현재 상태로 간주하고 프로젝트를 처음부터 다시 추측하지 말아 달라.

답변할 때 다음 원칙을 지켜 달라.

1. 한국어로 설명한다.
2. **이미 확인된 사실**, **현재 해석**, **앞으로의 제안**을 항상 구분한다.
3. Amazon 데이터에 사람이 부여한 촉감 정답이 있다고 가정하지 않는다.
4. Qwen이 추출·채택한 claim을 human gold label로 부르지 않는다. 전부 pseudo-label이다.
5. 리뷰에서 만든 상품 촉감 벡터는 proxy target이지 실제 촉감 정답이 아니다.
6. 이미지 예측값(Last2 확률)은 실제 구매자 근거가 아니라 예상값이다.
7. 서로 다른 Amazon 버전·카테고리·split·candidate protocol의 논문 수치를 직접 비교하지 않는다.
8. 사용자가 이미지를 업로드해 검색하는 서비스라고 가정하지 않는다. 이미지는 리뷰가 없는 상품의 촉감을 내부적으로 예측하는 데 쓴다.
9. 고정 taxonomy를 쓰더라도 원문 exact span과 open-vocabulary 표현은 삭제하지 않는다.
10. Test 리뷰나 미래 리뷰로 상품 촉감 feature를 만들지 않는다. 데이터 누수를 항상 점검한다.
11. **가장 중요**: 아래 실험 결과의 상당수는 명확한 **음성(negative) 결과**다. 이를 긍정적으로 포장하거나 "개선 가능성이 있다"로 얼버무리지 말고, 왜 실패했는지와 그 실패가 논문에서 어떤 의미를 가질 수 있는지를 직설적으로 다뤄 달라.
12. 나는 단순 동의를 원하지 않는다. 연구 논리의 약점, confounder, 평가 오류를 구체적으로 지적해 달라.
13. 아직 결정되지 않은 사안을 확정된 결정처럼 쓰지 말고, 비교 가능한 실험으로 제시한다.

이 문서를 읽은 뒤에는 프로젝트를 다시 요약하는 데 답변 대부분을 쓰지 말고, 내가 이어서 묻는 질문에 바로 답해 달라.

---

## 1. 프로젝트 한 줄 설명

시각장애인의 온라인 의류 쇼핑을 돕기 위해, Amazon 상품 리뷰에서 실제 구매자가 언급한 소재·촉감 근거를 추출하고 이를 상품 검색·비교·추천과 근거 기반 설명에 활용하는 졸업프로젝트 + 논문 프로젝트다.

```text
실제 구매자 리뷰에서 촉감 표현 추출 (Qwen exact span)
→ 상품별 촉감 표현 구성 (open span 또는 14-class)
→ 리뷰 없는 상품은 이미지로 촉감 예측 (FashionCLIP fine-tune = "Last2")
→ 자연어 검색 · 유사상품 · 방향성 대안 · 개인화 추천에 사용
→ 가능한 경우 실제 리뷰 문장을 근거로 제시
```

---

## 2. 현재 상태 한눈에 보기 (가장 중요한 요약)

| 질문 | 현재 답 | 근거 실험 |
|---|---|---|
| 리뷰에서 촉감 span을 뽑을 수 있는가? | **가능**. exact substring 검증 통과 | 01~05, 10~12 |
| 그 span을 14-class로 정규화할 수 있는가? | **가능**. 단 class별 편차 큼 | 12 |
| 이미지로 촉감 class를 예측할 수 있는가? | **부분적**. category-only baseline 대비 이득이 작음 | 12, 13, 14 |
| 같은 category 안에서 이미지가 촉감을 구별하는가? | **어느 정도 가능** (pair-weighted AUROC 0.7528) | 14 |
| 촉감을 일반 추천(next-item)에 더하면 개선되는가? | **아니다. 4번 독립적으로 실패** | 16, 17, 19, 20 |
| 명시적 촉감 질의 정렬은 잘 되는가? | **잘 된다** (NDCG@10 0.475→0.765). 단 exploratory | 16 |
| 외부 fabric 데이터셋으로 일반화되는가? | **아니다. AUROC 0.58, 거의 우연 수준** | 21 |
| 사람 검수(human gold)가 있는가? | **거의 없다** (160개 중 5개만 완료) | 15, 18 |
| 서비스/데모는 동작하는가? | **동작한다** (825,840 상품 catalog, 공개 URL 배포까지 완료) | shopping_agent v1 |

**한 문장 요약: 파이프라인은 끝까지 구현됐고 촉감 표현 자체는 뽑히지만, (a) 추천 성능 개선은 4개 실험에서 모두 실패했고 (b) 외부 데이터셋 일반화도 실패했으며 (c) 실패의 근본 원인이 pseudo-label의 positive 편향과 retrieval bottleneck으로 진단된 상태다.**

---

## 3. 데이터

### 3.1 리뷰 grounding 데이터 (두 개의 서로 다른 규모가 있으니 혼동 금지)

| 구분 | 규모 | 용도 |
|---|---|---|
| **Dense-500 (v2.1)** | 상품 500개 / 리뷰 4,158개 / exact span 6,345개 / 채택 claim 4,527개 | 초기 open-span 파이프라인, tactile profile 프로토타입 |
| **v3 8,498 (class)** | 상품 8,498개 / 후보 span 26,126개 / 관측된 product-class pair 34,168개 | 14-class multi-label 학습(Last2) |
| **전체 원문** | 리뷰 2,500,939개 / 사용자 2,035,490명 / parent item 825,869개 | 추천 실험, lexical screen |

### 3.2 추천 데이터 (Amazon Reviews 2023, `Amazon_Fashion`)

- Raw: users 2,035,490 / items 825,869 / reviews 2,500,939
- Processed 공식 leave-last-out split: interactions 2,474,375
- Train / validation / test events: 157,490 / 281,395 / 2,035,490
- **user history 분포가 극도로 sparse**: test 사용자 2,035,490명 중 1,754,095명(86.2%)이 zero-history, history≥3은 29,991명(1.5%)뿐

### 3.3 이미지 촉감 카탈로그

- Last2 inference 완료: **825,840 / 825,869 items (100.00%)**
- 기존 8,498개 대비 97.18배 확장
- 실패 29개(HTTP 28 + no-URL 1)는 catalog에서 제거하지 않고 tactile adjustment를 neutral로 유지

### 3.4 외부 데이터셋 (FabricVST)

- 출처: https://sites.google.com/view/multimodalzsl (Cao et al., RAS 2024)
- fabric 50종 / attribute 24종 / annotator 5명 / `visual_cropped` 11,250장
- 공식 split 파일은 배포되지 않음 → 모델을 여기서 학습하지 않았으므로 50개 fabric 전체를 held-out으로 사용

---

## 4. 파이프라인

```text
[1] Qwen exact span 추출     리뷰 원문 그대로 복사, 코드로 substring 검증
        ↓
[2] Qwen semantic verification   소재 여부 / scope / 극성 / evidence basis 구조화
        ↓
[3] (선택) 14-class 정규화    open span은 삭제하지 않고 병행 보존
        ↓
[4] 상품 촉감 표현
      - open span 경로: BGE-small 384D → 사용자별 1표 → 상품 벡터
      - class 경로: 14-class masked multi-label target
        ↓
[5] 이미지 예측 (Last2)      FashionCLIP vision encoder 마지막 2블록 + projection fine-tune
                             → linear head → 독립 sigmoid 14개
        ↓
[6] downstream               검색 / 유사상품 / 대안 / 추천 reranking / Agent 설명
```

핵심 모델 버전:

- span/semantic: `Qwen3-VL-8B-Instruct` (vLLM 0.27.1, BNB 4-bit)
- class/preference 추출: `Qwen/Qwen3-VL-32B-Instruct` rev `0cfaf48183f594c314753d30a4c4974bc75f3ccb`, NF4 + BF16
- 이미지: `patrickjohncyh/fashion-clip` rev `7e3ba62ce16b379a1ab479346b66f192e76f51b7`
- 공식 checkpoint: `experiments/12_class_multilabel_fashionclip_ft/models/fashionclip_last2.pt`
  SHA-256 `073b542a9d6bd4450aa1f48596c756cc0812b1b5d914945e8f94f7c3fda1934a` (이후 전부 inference-only)

14 classes: `soft, firm, smooth, rough, non_elastic, elastic, thin, thick, flexible, stiff, warm, cool, spongy, crisp`

---

## 5. 실험 전체 목록

| # | 실험 | 상태 | 한 줄 결론 |
|---|---|---|---|
| 01 | span extraction | 완료 | exact span 추출 파이프라인 확립 |
| 02 | semantic verification | 완료 | scope/극성/evidence basis 구조화 |
| 03 | human semantic audit | 완료(소규모) | 초기 검수 UI 및 표본 |
| 04 | recall extraction v2 | 완료 | 2개 lens 추가로 recall 보강 |
| 05 | product dense readiness | 완료 | 상품 단위 밀도 조건 정의 |
| 06~09 | simple/dense M0·M1, 500 protocol | 완료 | GNN 이전 단순 검색 baseline |
| 10 | vLLM rerun | 완료 | vLLM 백엔드로 재현 |
| 11 | vLLM dense-500 human audit | 완료(소규모) | 사람 검수 |
| 12 | **class multilabel + FashionCLIP FT** | 완료 | `last2` 선택, test macro-F1 0.6010 |
| 12b | dense-500 v2.1 AI recall | 완료 | span 2,866→6,345, claim 2,591→4,527 |
| 13 | **category-only baseline** | 완료 | category만으로 macro-F1 0.5797 → shortcut 큼 |
| 14 | **same-category evaluation** | 완료 | Last2 pair-weighted AUROC 0.7528 (positive 신호) |
| 15 | human audit | **미완료** | manifest 160개 중 5개만 완료 |
| 16 | recommendation reranking (구버전) | 폐기됨 | catalog를 촉감 교집합으로 축소한 설계 실패 |
| 16b | **strong recommender + tactile** | 완료 | alpha=0 선택 → 촉감 효과 0 |
| 17 | tactile preference feasibility | 완료 | 조건부 GO, 표본은 작음 |
| 17b | **history≥3 recommender refresh** | 완료 | history≥3에서도 alpha=0, delta 0 |
| 18 | tactile preference pilot | **사람 검증 대기** | 64건 추출, 사람 판정 0건 |
| 19 | **explicit preference exploratory** | 완료 | delta +0.000107, CI가 0 포함 |
| 20 | **tactile recommender spec completion** | 완료 | in-model tactile도 primary contrast 음수 |
| 21 | **FabricVST external** | 완료 | 외부 일반화 실패, 원인은 label 편향 |

---

## 6. 촉감 표현·이미지 예측 실험 (12 ~ 15)

### 6.1 실험 12 — 14-class multi-label + FashionCLIP fine-tuning

Family-disjoint split: train 6,300 / development 1,077 / locked test 1,121.
관측되지 않은 class는 negative가 아니라 **unobserved(masked)** 로 처리했다.

| Regime | Dev macro-F1 | Test macro-F1 | Test micro-F1 | Test macro-AP |
|---|---:|---:|---:|---:|
| frozen | 0.6294 | 0.5784 | 0.7621 | 0.5607 |
| projection | 0.6631 | 0.6166 | 0.7824 | 0.6143 |
| last1 | 0.6922 | 0.6050 | 0.8145 | 0.6412 |
| **last2 (선택)** | **0.6975** | **0.6010** | **0.8216** | 0.6232 |
| full | 0.6736 | 0.5801 | 0.8066 | 0.6073 |

선택은 development macro-F1만으로 했다. class별 편차가 매우 크다: `soft` F1 0.9702(positive 618/656)인 반면 `firm` 0.0000(positive 12/631), `non_elastic` 0.0645(positive 21/419). 즉 **빈도가 높은 class만 잘 맞히고 희소 class는 전혀 못 맞힌다.**

### 6.2 실험 13 — category-only baseline (통제 실험)

이미지를 전혀 쓰지 않고 category ID → 64D embedding → 14 logits만으로 학습:

| Split | Macro-F1 | Micro-F1 | Macro-AUROC |
|---|---:|---:|---:|
| Development | 0.6317 | 0.7202 | 0.6030 |
| Locked test | **0.5797** | 0.7120 | 0.5749 |

**해석: Last2의 test macro-F1 0.6010과 category-only 0.5797의 차이는 0.0213뿐이다. 즉 실험 12의 macro-F1 대부분은 이미지가 아니라 category shortcut으로 설명된다.** 이것이 이후 실험 14가 필요했던 이유다.

### 6.3 실험 14 — same-category evaluation (shortcut 제거 후 평가)

각 `(category, tactile class)`를 독립 binary ranking cell로 두고, category를 고정한 상태에서 Last2가 positive를 negative보다 위로 정렬하는지 측정했다. valid cell 107/154, reliable-support cell 28개.

| Metric | Category-only | Last2 | 차이 |
|---|---:|---:|---:|
| Macro-cell AUROC | 0.5000 | **0.6568** | +0.1568 |
| Pair-weighted AUROC | 0.5000 | **0.7528** | +0.2528 |
| Macro AP lift | 0.0000 | 0.1928 | +0.1928 |
| Pairwise accuracy | 0.5000 | 0.7528 | +0.2528 |

class별로는 `cool` 0.8002, `warm` 0.7966, `thick` 0.7794, `thin` 0.7663이 높고 `soft` 0.4766(우연 이하)이 가장 낮다. soft는 positive가 618/656으로 거의 전부 positive라 구별할 여지가 없다.

**이 결과가 현재 프로젝트에서 가장 명확한 양성 신호다.** 다만 target이 Qwen pseudo-label이라는 한계는 그대로다.

### 6.4 실험 15 — human audit (미완료)

manifest 160개 중 live CSV에 completed 5개. 작성자 provenance가 artifact에 기록되지 않아 정량 결과로 통합하지 않았다. **현재 프로젝트 전체에 human gold set이 사실상 없다.**

---

## 7. 추천 실험 (16 ~ 20) — 네 번의 독립적인 실패

### 7.0 왜 이 절이 중요한가

촉감 정보를 추천에 더하는 방향은 **서로 다른 네 가지 설계로 네 번 시도했고 네 번 모두 개선에 실패했다.** 설계가 달랐기 때문에 "구현 실수"로 설명하기 어렵고, 공통 원인을 진단해야 한다.

### 7.1 폐기된 구버전 실험 16 (recommendation_reranking)

추천 catalog를 촉감 라벨 교집합으로 먼저 줄인 설계였다. catalog 7,365/825,869 (0.89%), test 유효 사용자 3,283명, candidate Recall@300 = 0.177. validation이 alpha=0을 선택했다. **coverage/retrieval bottleneck과 촉감 무용성이 분리되지 않아 폐기.**

### 7.2 실험 16b — strong recommender + tactile (전체 catalog 재설계)

825,869개 전체 catalog에서 학습·후보 생성. 이미지 없는 상품도 제거하지 않음.

Backbone validation NDCG@10 (전체 281,395 target):

| Backbone | validation NDCG@10 |
|---|---:|
| Popularity | 0.0045832 |
| BPR | 0.0042348 |
| LightGCN | 0.0045305 |
| **SASRec (선택)** | **0.0046928** |
| eSASRec | 0.0046335 |

Candidate recall은 K=3000에서도 0.1086 (SASRec). **사전 규칙 Recall≥0.80 미충족 → retrieval bottleneck 미해소 상태로 진행.**

Test 결과 (all-user):

| Method | NDCG@10 | HR@10 | MRR@10 |
|---|---:|---:|---:|
| popularity | 0.005765 | 0.009468 | 0.004615 |
| bpr | 0.005686 | 0.009313 | 0.004559 |
| lightgcn | 0.005727 | 0.009374 | 0.004594 |
| **sasrec** | **0.005787** | 0.009394 | 0.004665 |
| esasrec | 0.005716 | 0.009405 | 0.004571 |
| **Strong + Tactile (alpha=0)** | **0.005787** | 0.009394 | 0.004665 |
| SMORE (generic image+text) | 0.005683 | 0.009287 | 0.004562 |
| SMORE + Last2 tactile | 0.005683 | 0.009287 | 0.004562 |

**결정적 사실: alpha search에서 validation이 alpha=0을 선택했다.** 최선의 양수 alpha 조합(`rating_ge_4`, 8-class, alpha=0.05)은 NDCG@10 0.004543으로 alpha=0(0.004693)보다 낮았다. 따라서 test의 delta=0, CI=[0,0]은 **촉감 효과에 대한 독립 검정이 아니라 validation 단계에서 tactile 항이 비활성화된 결과**다. 이 점을 GPT가 혼동하면 안 된다.

주목할 점: personalized backbone들이 popularity보다 거의 나을 게 없다 (0.005787 vs 0.005765). test 사용자의 86.2%가 zero-history라 popularity fallback으로 수렴하기 때문이다.

### 7.3 실험 16b의 유일한 양성 결과 — 명시적 tactile query

user ID 없이 "이 촉감을 원한다"는 질의만 주는 별도 benchmark:

| Method | Mean tactile NDCG@10 | Mean Precision@10 |
|---|---:|---:|
| Non-tactile popularity | 0.475245 | 0.568750 |
| **Last2 tactile** | **0.765099** | **0.831250** |
| Dev-selected fusion | 0.783492 | 0.850000 |

Family bootstrap Last2 − non-tactile Δ NDCG@10 = **0.295028, 95% CI [0.203259, 0.391518]**.

class별로 `thin` 1.000, `cool` 0.936, `warm` 0.915, `smooth` 0.890이 높고 `flexible`만 popularity보다 낮다(0.614 vs 0.870).

**단, 이 benchmark는 (a) user ID가 없어 baseline이 personalized 모델이 아닌 popularity이고 (b) 실험 14에서 같은 test를 이미 관찰했으므로 exploratory replication이지 fresh confirmatory evidence가 아니다.**

### 7.4 실험 17b — history≥3 cohort refresh

zero-history 사용자가 평균을 희석한다는 가설을 검증하려고, 평가 대상을 history≥3인 사용자로 제한했다 (validation 14,731명 / test 29,991명). **학습 데이터는 줄이지 않았다.** BERT4Rec, GRU4Rec도 추가했다.

Test (29,991명 동일 집단):

| Model | NDCG@10 | HR@10 | MRR@10 |
|---|---:|---:|---:|
| Popularity | 0.00281439 | 0.00606849 | 0.00183312 |
| BPR-MF | 0.00137083 | 0.00270081 | 0.00096922 |
| **SASRec (선택)** | **0.00349417** | 0.00576840 | 0.00280234 |
| eSASRec | 0.00321906 | 0.00603514 | 0.00236740 |
| BERT4Rec | 0.00304059 | 0.00536828 | 0.00231645 |
| GRU4Rec | 0.00306869 | 0.00516822 | 0.00241713 |
| SMORE-derived | 0.00117644 | 0.00190057 | 0.00095120 |

여기서는 SASRec이 popularity를 확실히 앞선다(0.00349 vs 0.00281). **즉 개인화 자체는 history가 있으면 작동한다.**

그런데 tactile alpha search는 **또 alpha=0을 선택했다.** 전체 grid에서 alpha>0인 모든 조합이 alpha=0보다 낮았다. 결과:

- SASRec vs SASRec+Tactile: NDCG@10 둘 다 0.00349417
- paired delta 0.00000000, 95% CI [0, 0]
- improved/unchanged/worsened = 0 / 29,991 / 0
- history 3-4 / 5-9 / 10+ 구간 모두 delta 0

tactile profile 자체는 충분했다: test 29,991명 전원(100%)에게 profile이 생성됐고, target과 같은 category의 과거 tactile support가 있는 사용자도 18,277명(60.94%)이었다. **데이터 부족이 아니라 신호가 없는 것이다.**

### 7.5 실험 19 — 명시적 like/dislike 선호 기반 추천

실험 16의 "과거 상품 이미지 촉감 벡터 평균"이 선호의 증거가 아니라는 비판에 대응해, **과거 리뷰에서 Qwen이 명시적으로 추출한 like/dislike**를 썼다.

추출 결과 (5,865 occurrence 시도):

- valid schema + anchored quote: 5,540
- attitudes: unknown 2,694 / like 1,940 / dislike 902 / mixed 4
- states: present 5,055 / absent 403 / uncertain 63 / not_tactile 19

`"I like that it is not thick"`의 absent+like를 thick 선호 +1로 바꾸지 않도록 state와 attitude를 분리했고, cross-category transfer는 0으로 뒀다.

Test 결과:

| Method | NDCG@10 |
|---|---:|
| Category baseline | 0.050544 |
| Category + explicit tactile preference | 0.050652 |
| **Delta** | **+0.00010725** |
| Paired bootstrap 95% CI | **[-0.00044850, +0.00074556]** |

**CI가 0을 포함한다. 확실한 개선을 확인하지 못했다.** 사람 검증은 사용자 요청으로 생략됐다(`complete_exploratory_human_audit_skipped`).

다만 실험 16/17b와 달리 **이 실험에서는 validation이 양수 alpha(0.2)를 선택했다.** 즉 tactile 항이 꺼지지 않았는데도 test delta가 통계적으로 구별되지 않았다. 실험 16/17b의 "alpha=0이라 효과가 0"과는 성격이 다른 실패이므로 구분해서 해석해야 한다.

주의: 이 NDCG(0.0505)는 실험 16(0.0058)과 **평가 모집단·후보 생성이 완전히 달라** 직접 비교 불가다. 핵심 비교는 이 실험 내부의 explicit − category뿐이다.

### 7.6 실험 20 — in-model tactile modality (가장 엄밀한 설계)

실험 16이 post-hoc reranking이었다는 한계를 없애기 위해, **모델 내부에 전용 tactile branch를 넣은 5개 변형**을 preregistration으로 설계했다.

- `I`: interaction branch만
- `I_T`: interaction + 전용 tactile branch
- `I_VX`: interaction + generic FashionCLIP image(V) + metadata text(X)
- `I_VX_T`: **primary proposed model**
- `I_VX_T_SHUFFLE`: tactile 벡터를 category × train-count 층 내에서 결정적으로 permute한 대조군 (capacity와 category/popularity 구조를 통제)

Primary contrast는 사전에 **`I_VX_T − I_VX`, NDCG@10, 전체 공식 test target**으로 고정했다.

Test 결과 (all official targets, 2,035,490명):

| Variant | NDCG@10 | HR@10 |
|---|---:|---:|
| I | 0.00572522 | 0.00937710 |
| I_T | 0.00573159 | 0.00939135 |
| I_VX | **0.00579374** | 0.00950287 |
| **I_VX_T (제안)** | **0.00578579** | 0.00948175 |
| I_VX_T_SHUFFLE | 0.00578580 | 0.00947536 |

Contrast:

| Contrast | Mean Δ NDCG@10 | improved / worse / unchanged |
|---|---:|---|
| **primary: I_VX_T − I_VX** | **−0.0000079540** | 38,038 / 38,558 / 1,958,894 |
| aligned − shuffle | −0.0000000169 | 38,263 / 38,327 / 1,958,900 |
| I_T − I | +0.0000063721 | 38,646 / 38,064 / 1,958,780 |

**해석 (매우 중요):**

1. **Primary contrast가 음수다.** 전용 tactile modality를 in-model로 넣으면 generic image+text보다 오히려 미세하게 나빠졌다.
2. **aligned − shuffle ≈ 0 (−1.7e-8).** 진짜 촉감 벡터와 무작위로 섞은 촉감 벡터의 성능이 사실상 동일하다. **즉 tactile branch가 기여한 것은 촉감 정보가 아니라 파라미터 용량뿐이었다.** 이것이 실험 20에서 가장 결정적인 증거다.
3. 후보 K를 3,000에서 **30,000까지 늘렸는데도** `retrieval_bottleneck_unresolved` 상태다. Recall@30000 = 0.2360.

Protocol 상태: `complete_locked_posthoc_exploratory`, `confirmatory: false`. 실험 16이 이미 공식 test를 열었기 때문에, 구현·하이퍼파라미터·validation 선택을 전부 사전 동결했더라도 **confirmatory가 아닌 locked post-hoc exploratory**로만 주장 가능하다.

> ⚠️ **함정 주의**: `experiments/20_.../EXP20_PAUSED_HANDOFF_20260909.md` 문서는 "9/10 실행 중, 재개 필요"라고 적혀 있지만 **stale하다.** 실제로는 2026-09-11에 완료됐다(`protocol_state` = `complete_locked_posthoc_exploratory`). 이 문서를 근거로 `train_select.py`를 재실행하면 안 된다.

### 7.7 네 번의 실패에 대한 현재 진단

| 후보 원인 | 증거 | 평가 |
|---|---|---|
| Retrieval bottleneck | K=30,000에서도 Recall 0.236 | **주요 원인 중 하나.** 후보 안에 정답이 없으면 reranker가 복구 불가 |
| Interaction이 촉감 선호의 label이 아님 | next review ≠ tactile satisfaction | **구조적 한계.** 평가 지표 자체가 촉감을 측정하지 않음 |
| 데이터 sparsity | test 86.2% zero-history | all-user 평균을 희석. 단 17b에서 통제해도 delta 0 |
| 촉감 신호 자체가 없음 | **shuffle과 aligned의 차이 ≈ 0** | 실험 20의 가장 강한 증거 |
| pseudo-label의 positive 편향 | known 중 positive 비율 0.79~0.96 | 실험 21에서 독립적으로 확인된 근본 원인 |

---

## 8. 실험 21 — FabricVST 외부 검증 (가장 최근, 2026-09-16 완료)

### 8.1 목적

두 가지를 물었다. (1) 기존 `last2`가 외부 fabric 데이터셋에서도 작동하는가? (2) taxonomy 자체를 FabricVST 기준으로 재구축하고 Qwen pseudo-labeling부터 다시 하면 나아지는가?

### 8.2 taxonomy 매핑

24개 FabricVST attribute 중 **exact 8 / approximate 2 / unavailable 14**.

- exact: soft, rough, smooth, thick, thin, cool, warm, stiff
- approximate: stretchable↔elastic, fluffy↔spongy
- 의도적 비매핑: `firm`≠`stiff` (last2에서 firm은 soft의 반대축, stiff는 flexible의 반대축), `flexible`≠`stretchable`

### 8.3 PART A — 기존 last2의 외부 평가

50개 fabric 전체, exact-mapped 8개 attribute:

| metric | value |
|---|---:|
| macro_f1 | 0.5661 |
| micro_f1 | 0.6339 |
| macro_recall | 0.7913 |
| **macro_auroc** | **0.5843** |
| macro_average_precision | 0.5810 |

**결론: 일반화하지 않는다.** macro AUROC 0.5843은 우연(0.5)에 거의 붙어 있고, `rough`(0.478)와 `smooth`(0.475)는 **우연 이하**다. F1이 높아 보이는 것은 threshold 전이 실패 때문이다 — 전이된 threshold가 거의 모든 fabric을 positive로 밀어버려서 recall이 1.000이 되고 F1이 base rate로 수렴했다. `cool`은 반대 방향으로 실패해 recall 0.042.

### 8.4 PART B — FabricVST taxonomy로 재labeling + 재학습

Qwen3-VL-32B로 원본 리뷰 **42,158건**을 24-attribute multi-label(positive/negative/unknown)로 재labeling. evidence span이 원문에 그대로 존재하는 비율 0.9847. 상품 8,498개. 새 head: FashionCLIP last2 regime + attribute별 독립 sigmoid, unknown은 gradient 기여 없도록 masking.

내부 held-out test (우리 자체 데이터):

| metric | group B (18 attr) | group A (24 attr) |
|---|---:|---:|
| macro_f1 | 0.8731 | 0.8463 |
| micro_f1 | 0.9123 | 0.9124 |
| **macro_auroc** | **0.6010** | 0.6032 |

**macro F1 0.8731인데 macro AUROC 0.6010이다. 이 격차 자체가 모델이 순위를 못 매긴다는 증거다.**

FabricVST 외부 평가, old vs new:

| Model | Macro F1 | Micro F1 | mAP | Macro Recall | **Macro AUROC** |
|---|---:|---:|---:|---:|---:|
| old last2 | 0.5661 | 0.6339 | 0.5810 | 0.7913 | 0.5843 |
| FabricVST-taxonomy retrained | 0.6513 | 0.6644 | 0.6050 | **1.0000** | **0.5992** |

### 8.5 macro F1 상승이 진짜 개선이 아닌 이유 (degeneracy 분석)

재학습 모델은 **비교 가능한 8개 attribute 전부에서 50개 fabric 모두를 positive로 예측한다** (recall 1.000, predicted positives 50/50). 선택된 threshold 8개 중 6개가 탐색 grid의 바닥값 0.10이다. 즉 가장 관대한 threshold로도 fabric을 분리할 수 없다.

all-positive predictor의 F1 = 2p/(1+p) 이므로 F1이 base rate의 순수 함수가 된다:

| attribute | positives/50 | base-rate F1 | 보고된 new F1 |
|---|---:|---:|---:|
| soft | 38/50 | 0.8636 | 0.8636 |
| rough | 30/50 | 0.7500 | 0.7500 |
| warm | 26/50 | 0.6842 | 0.6842 |
| stiff | 11/50 | 0.3607 | 0.3607 |

**소수점 4자리까지 일치한다.** macro F1 +0.085의 대부분은 `cool`(0.080→0.649) 하나에서 나왔는데, 이는 last2가 반대 방향으로 degenerate했던 것을 다른 방향의 degenerate로 바꾼 것일 뿐 학습이 아니다.

### 8.6 근본 원인 — 이것이 프로젝트 전체에서 가장 중요한 발견

**pseudo-label이 압도적으로 positive에 치우쳐 있다.** attribute가 known인 상품 중 positive 비율이 0.79~0.96이다 (`soft` 0.956, `warm` 0.949, `thin` 0.947, `cool` 0.928).

원인은 명확하다: **리뷰어는 자기가 인지한 속성만 쓰고 부재를 단언하지 않는다.** 따라서 negative evidence가 구조적으로 희소하다. `pos_weight`를 [0.25, 4.0]으로 clip한 상태에서 loss가 이를 보상하지 못하고, 모델이 이미지 증거 대신 class prior로 수렴한다. 추가로 24개 중 7개는 상품의 5% 미만에서만 known이다 (fluffy, bumpy, striped, hairy, embroidered, jacquard, pigment printed).

> **이것은 architecture 문제가 아니라 label 구성(label-construction) 문제이며, 후속 연구를 결정해야 하는 발견이다.**
> 그리고 실험 20의 `aligned − shuffle ≈ 0`과 정확히 같은 방향을 가리킨다: 촉감 벡터에 실제 판별 정보가 거의 담겨 있지 않다.

### 8.7 실험 21이 **지지하지 않는** 주장

- 두 모델 중 어느 것도 외부 fabric에서 촉감을 신뢰성 있게 예측한다
- `soft`/`rough`/`warm`의 높은 F1이 실력을 반영한다 (base rate를 따라간 것)
- 5-fabric paper-style subset의 attribute별 결론 (n=5, 노이즈)
- 재학습이 last2를 개선했다
- 내부 macro F1 0.8731 기반의 어떤 주장이든 (대응 AUROC가 0.6010)

---

## 9. 서비스·데모 구현 (졸업프로젝트 트랙)

연구 결과와 별개로 **실제 동작하는 서비스는 완성돼 있다.**

| 구성요소 | 포트/경로 | 내용 |
|---|---|---|
| `recommendation_api` | 8877 `/tactile-demo` | 438 catalog + tactile 495 profile, 설명/concern/비교/대안/context-gated reranking |
| `shopping_agent/v1` | 8878 `/agent-demo` | 로그인·세션·행동 이벤트·자동 취향 기억·개인화 정렬·장바구니 |
| `demo_agent` | Streamlit 8501 | Last2 14D 확률 기반 촉감 정렬 데모 |

`shopping_agent`는 Cloudflare Quick Tunnel로 공개 배포까지 검증했다 (회원가입 → 쿠키 인증 → 세션 → 라우팅 3종 → 추천 20건 → 취향 자동 저장 → 장바구니 E2E 통과). Catalog 모드 2종: `full` (825,840 전체, 이미지 예측 촉감) / `curated` (465 리뷰 근거).

**서비스에서 지키고 있는 정직성 경계:**

- 전체 catalog의 촉감은 이미지 예측이며 리뷰 근거가 아니다. `tactile_target_source`와 `score_breakdown.evidence_source`로 항상 구분 표시.
- 465개 중 406개만 825K catalog에 존재 → `review_grounded_overlay`로 표시.
- Last2가 표현 못 하는 4개 개념(sheerness/breathability/linting/pilling)은 근사하지 않고 `unsupported_concepts`로 보고.
- proxy 매핑(scratchiness→rough 등)은 가중치 0.6으로 낮추고 fidelity 표기.

---

## 10. 현재까지 확립된 사실 vs 확립되지 않은 것

### 10.1 확립된 사실

1. Qwen으로 리뷰에서 exact span을 뽑고 구조화하는 파이프라인이 동작한다 (evidence verbatim 비율 0.9847).
2. 14-class로 정규화한 뒤 FashionCLIP fine-tuning이 가능하다 (last2, test macro-F1 0.6010).
3. **그러나 그 macro-F1의 대부분은 category shortcut이다** (category-only 0.5797).
4. **같은 category 안에서는 이미지가 촉감을 어느 정도 구별한다** (pair-weighted AUROC 0.7528). 현재 가장 강한 양성 신호.
5. Last2를 전체 825,840 상품으로 확장 inference하는 것이 가능하다 (coverage 100%).
6. 명시적 촉감 질의 정렬에서 Last2가 popularity를 크게 앞선다 (0.475→0.765, CI가 0 제외).
7. **촉감을 일반 next-item 추천에 더하는 것은 네 가지 독립 설계에서 모두 실패했다.**
8. **실험 20의 shuffle 대조군이 aligned와 동일한 성능을 냈다** — 촉감 벡터에 추천에 쓸 판별 정보가 사실상 없다.
9. **외부 fabric 데이터셋으로 일반화되지 않는다** (macro AUROC 0.5843 → 0.5992, 둘 다 우연 근처).
10. **근본 원인은 pseudo-label의 positive 편향이다** (known 중 positive 비율 0.79~0.96). architecture 문제가 아니다.
11. 서비스 전체 흐름(검색·설명·비교·Agent·장바구니)은 구현·배포·E2E 검증됐다.

### 10.2 확립되지 않은 것 / 주장하면 안 되는 것

- 어떤 모델도 실제 촉감을 정확히 예측한다고 말할 수 없다. 모든 target이 pseudo-label 또는 proxy다.
- human gold set이 없다 (실험 15는 160개 중 5개, 실험 18은 64개 중 사람 판정 0개).
- 실험 16의 `delta=0, CI=[0,0]`은 무효효과 검정이 아니다. validation이 alpha=0을 선택해 tactile 항이 꺼진 결과다.
- 실험 20의 결과는 confirmatory가 아니다. 실험 16이 이미 공식 test를 열었으므로 locked post-hoc exploratory다.
- 실험 16의 명시적 tactile query 결과는 실험 14에서 같은 test를 이미 봤으므로 exploratory replication이다.
- 실험 19의 NDCG(0.0505)와 실험 16의 NDCG(0.0058)는 모집단·후보 생성이 달라 비교 불가다.
- Amazon_Fashion 2023과 기존 MMRec 논문의 Clothing 5-core는 다른 benchmark다. sampled 결과와 full-ranking 결과도 비교 불가다.
- eSASRec/SMORE는 환경·scale adapter를 썼으므로 upstream 숫자와 직접 비교 불가다. SMORE는 공식 reproduction이 아니라 "SMORE-derived scalable adaptation"이다.
- category 11종은 공식 taxonomy가 아니라 title keyword 휴리스틱이며 검증되지 않았다.

---

## 11. 새 confirmatory 주장을 하려면 필요한 것

실험 20의 preregistration이 명시한 조건이다. 기존 데이터에서 새 holdout을 잘라내는 것은 **internal robustness analysis이지 fresh confirmatory test가 아니다.**

다음 둘 중 하나만 새 확증 주장을 지지할 수 있다.

1. 이전 학습·개발·평가·설계에 쓰이지 않은 **진짜 미관측 시간 구간의 Amazon Fashion interaction**
2. user/query/candidate manifest와 dev/test 분할이 annotation 전에 hash-lock되고, hidden test label이 모든 선택이 잠긴 뒤에만 열리며, annotator provenance가 기록된 **prospective human relevance benchmark**

---

## 12. GPT와 논의하고 싶은 핵심 질문

### 12.1 논문 프레이밍 (가장 급한 질문)

현재 결과 구조가 이렇다:

- 긍정: same-category AUROC 0.7528, 명시적 tactile query 0.475→0.765
- 부정: 추천 개선 4전 4패, 외부 일반화 실패, shuffle 대조군과 동일
- 진단: pseudo-label positive 편향이라는 구체적 근본 원인

질문:

1. 이걸 **negative result / 진단 논문**으로 프레이밍하는 것이 현실적인가? "리뷰 기반 촉감 pseudo-label은 왜 추천으로 전이되지 않는가"라는 형태로. 4-page short paper에서 이게 통할까?
2. 아니면 **same-category 평가 + 명시적 query** 두 개의 양성 결과만으로 positive 논문을 쓰고, 추천 실패는 limitation으로 미는 것이 나은가? 그게 정직한가?
3. **shuffle 대조군 결과(aligned − shuffle ≈ 0)** 는 논문에서 강점인가 치명타인가? 나는 이게 방법론적으로 엄밀해서 오히려 기여가 될 수 있다고 생각하는데, 리뷰어는 "제안 방법이 작동하지 않는다는 자백"으로 읽지 않을까?

### 12.2 label 구성 문제를 풀 방법

실험 21이 지목한 근본 원인은 negative evidence의 구조적 희소성이다.

4. 리뷰어가 부재를 단언하지 않는다는 구조적 문제를 어떻게 우회할 수 있나? 후보: (a) 같은 category 내 상대 비교로 label을 만들기, (b) 소재 조성(`Polyester 95%`)을 prior로 쓰기, (c) pairwise ranking label로 전환해 absolute positive/negative를 피하기, (d) contrastive/ranking loss로 바꾸기.
5. `pos_weight` clip [0.25, 4.0]을 푸는 것만으로 되는 문제인가, 아니면 label 정의 자체를 바꿔야 하나?
6. positive 비율 0.79~0.96인 상황에서 AUROC를 primary metric으로 고정하는 것이 맞나? 더 적절한 지표가 있나?

### 12.3 추천 트랙을 계속할지

7. retrieval bottleneck(K=30,000에서 Recall 0.236)이 해소되지 않은 상태에서 reranking 개선을 측정하는 것 자체가 무의미한가? 이 bottleneck을 먼저 풀어야 한다면 어떻게?
8. next-item 예측이 촉감 만족도를 측정하지 못한다면, 촉감 추천을 **어떤 task로 평가해야** 하나? 명시적 query 정렬만으로 충분한 downstream인가?
9. 추천 트랙을 접고 **image→촉감 검색**을 주 downstream으로 정하는 것이 나은가?

### 12.4 남은 시간 배분

졸업프로젝트는 서비스가 이미 완성돼 있고, 논문은 아직 방향이 안 정해졌다.

10. 지금 남은 리소스를 (a) human gold set 구축, (b) label 재구성 실험, (c) 명시적 query benchmark 강화 중 어디에 써야 하나?
11. human gold set을 만든다면 최소 몇 개, 어떤 stratification, 어떤 지표로 설계해야 실험 15/18의 미완료 상태를 극복할 수 있나?

---

## 13. 절대 혼동하면 안 되는 사항

- `texture_project`는 이전 프로젝트다. 현재 작업은 `material_span_grounding`이다.
- Dense-500(4,527 claim)과 v3 8,498(class) 데이터는 서로 다른 규모의 별개 데이터셋이다.
- 4,527 claim은 human gold가 아니라 Qwen pseudo-label이다.
- Amazon interaction은 tactile label이 아니다.
- Review-derived product vector도 실제 촉감 정답이 아니라 proxy다.
- Image prediction(Last2 확률)은 실제 구매자 evidence가 아니라 예상값이다.
- 실험 16의 delta=0은 alpha=0 선택의 결과지 무효효과 검정이 아니다.
- 실험 20은 confirmatory가 아니라 locked post-hoc exploratory다.
- 실험 21의 macro F1 개선은 all-positive degeneracy의 artifact다.
- `EXP20_PAUSED_HANDOFF_20260909.md`는 stale하다. 실험 20은 2026-09-11에 완료됐다.
- 실험 19의 NDCG 0.0505와 실험 16의 0.0058은 비교 불가다.
- Amazon_Fashion 2023 ≠ 논문의 Clothing 5-core.
- SMORE-derived는 공식 재현이 아니다.
- category 11종은 검증된 taxonomy가 아니라 title keyword 휴리스틱이다.

---

## 14. 참고 경로 (추가 업로드가 필요할 때)

| 문서 | 내용 |
|---|---|
| `experiments/21_fabricvst_external/FINAL_REPORT.md` | FabricVST 외부 평가 전문 (가장 최신, 가장 중요) |
| `experiments/20_.../notion/EXP20_TACTILE_RECOMMENDER_SPEC_COMPLETION_REPORT.md` | in-model tactile 실험 |
| `experiments/20_.../PREREGISTRATION.md` | 사전등록 설계와 claim boundary |
| `experiments/16_strong_recommender_tactile/notion/STRONG_RECOMMENDER_TACTILE_RESULTS.md` | 전체 catalog 추천 실험 |
| `experiments/17_history3_recommender_refresh/RESULTS.md` | history≥3 cohort |
| `experiments/19_.../notion/GPT_FULL_EXPERIMENT_PROCESS_RESULTS_EVALUATION.md` | 명시적 선호 실험 |
| `experiments/12_.../notion/TACTILE_CLASS_MULTILABEL_QWEN32B_FASHIONCLIP_FT.md` | 14-class + FashionCLIP FT |
| `experiments/13_category_only_baseline/notion/CATEGORY_ONLY_BASELINE_RESULTS.md` | category shortcut 진단 |
| `experiments/14_same_category_evaluation/notion/SAME_CATEGORY_EVALUATION_RESULTS.md` | shortcut 제거 후 평가 |
| `docs/tactile/` | 설계·데이터 계약·평가 계획 |
| `AGENTS.md` | 프로젝트 정직성 규칙 |

---

## 15. 참고 논문·데이터

- Amazon Reviews 2023: https://amazon-reviews-2023.github.io/
- benchmark scripts: https://github.com/hyp1231/AmazonReviews2023/tree/main/benchmark_scripts
- FabricVST / Multimodal ZSL: https://sites.google.com/view/multimodalzsl (Cao et al., RAS 2024)
- MMRec toolbox: https://github.com/enoche/MMRec
- VBPR https://arxiv.org/abs/1510.01784 · LATTICE https://arxiv.org/abs/2104.09036 · BM3 https://arxiv.org/abs/2207.05969 · FREEDOM https://arxiv.org/abs/2211.06924

---

## 16. 새 GPT 대화를 시작할 때 함께 보낼 짧은 메시지

```text
첨부한 GPT_HANDOFF_20260917.md는 진행 중인 시각장애인용 의류 촉감 검색·추천 프로젝트의
실험 01~21 전체 현황입니다. 전체를 읽고 사실·해석·제안을 구분해 주세요.

핵심 맥락: 파이프라인은 완성됐고 same-category 평가와 명시적 촉감 질의에서는 양성 결과가
나왔지만, 추천 개선은 네 가지 독립 설계에서 모두 실패했고 외부 fabric 데이터셋 일반화도
실패했습니다. 실험 20의 shuffle 대조군이 aligned와 동일한 성능을 냈고, 실험 21에서
pseudo-label의 positive 편향(known 중 positive 0.79~0.96)이 근본 원인으로 진단됐습니다.

Qwen claim과 리뷰 벡터를 human ground truth로 간주하지 말고, benchmark 차이와 데이터 누수를
엄격하게 봐 주세요. 음성 결과를 긍정적으로 포장하지 말아 주세요.

프로젝트를 다시 요약하기보다, 12절의 질문부터 바로 답해 주세요.
```

---

## 17. 첫 질문으로 던질 것

```text
12절의 질문 1~3(논문 프레이밍)에 먼저 답해 줘.

특히 실험 20의 shuffle 대조군 결과(진짜 촉감 벡터와 무작위로 섞은 촉감 벡터의 NDCG 차이가
-1.7e-8)를 논문에서 어떻게 다뤄야 하는지 판단해 줘. 이걸 숨기면 부정직하고, 전면에 내세우면
제안 방법이 무효라는 자백처럼 읽힐 수 있어.

그리고 "리뷰 기반 촉감 pseudo-label은 왜 추천으로 전이되지 않는가"를 주제로 한 진단 논문이
4-page short paper로서 성립하는지, 성립한다면 어떤 실험을 추가로 해야 reviewer가 납득할지
decision table로 정리해 줘. 아직 방향을 임의로 확정하지는 말아 줘.
```
