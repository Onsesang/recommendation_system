# 시간순 추천 정량 평가 환경

> 기준일: 2026-08-13  
> 상태: evaluator 구현·실데이터 protocol 생성·baseline 실행 완료  
> 목적: 촉각 표현이 실제 다음 상품 추천에 기여하는지 동일 조건에서 정량 비교

## 1. 결론

Amazon Fashion의 `user_id-item-rating-timestamp` interaction으로 다음 지표를 재현 가능하게
계산하는 환경을 구축했다.

- Precision@K
- Recall@K
- Hit Rate@K
- nDCG@K
- MRR
- MAP@K
- TactileMatch@K
- target item cold-start/long-tail/head 분석
- sparse/medium/rich user-history 분석
- baseline 대비 paired bootstrap 95% 신뢰구간

현재 실측 결과는 촉각 모델의 최종 성능이 아니라 **평가 환경 smoke test**다. 현재
open-vocabulary 소재 target이 전체 20,198개 평가 상품 중 438개뿐이어서 사용자 tactile
profile coverage가 9.0%, Top-10 tactile item coverage가 약 9.8%에 불과하다. evaluator는
이를 자동으로 `tactile_match_status=insufficient_coverage`로 표시한다.

따라서 지금 확정할 수 있는 결론은 다음과 같다.

> 추천 지표를 측정할 환경은 준비됐다. 그러나 BPR+tactile의 기여를 판단하기 전에 소재
> target을 interaction catalog 대부분으로 확장하고, 추천 시점 이전 리뷰만으로 target을
> 다시 만들어야 한다.

---

## 2. 시간순 protocol

입력은 기존 interaction cache 272,606개다.

```text
rating 4~5 interaction
→ 동일 사용자·상품 반복은 마지막 timestamp만 유지
→ positive가 4개 이상인 사용자 선택
→ 과거 상품: train
→ 끝에서 두 번째 상품: validation
→ 마지막 상품: test
```

| 항목 | 값 |
|---|---:|
| 원본 interaction | 272,606 |
| positive dedup interaction | 194,528 |
| 평가 사용자/case | 332 |
| 상품 universe | 20,198 |
| test 정답 | 사용자당 1개 |
| negative | case당 100개 |
| candidate set | 101개 |
| K | 10 |

각 case의 negative는 다음 조건으로 고정했다.

- 사용자가 이미 선택한 상품 제외
- 해당 test timestamp 이전 train event에 등장한 상품만 허용
- 해당 시점 train popularity의 제곱근에 비례해 비복원 추출
- 모든 모델이 동일하게 저장된 candidate set 사용
- seed `20260813`
- raw `user_id`는 파일에 저장하지 않고 SHA-256 기반 `case_id`만 사용

단일 test 정답이므로 현재 protocol에서는 다음 관계가 성립한다.

```text
Recall@K = Hit Rate@K
Precision@K = Recall@K / K
```

MAP과 Precision의 독립적인 의미를 더 크게 보려면 향후 다중 정답 time-window protocol을
별도로 추가해야 한다.

---

## 3. 지표 정의

### 일반 추천 품질

| 지표 | 계산 목적 |
|---|---|
| Recall@10 | 실제 다음 상품이 Top-10에 들어갔는가 |
| Hit Rate@10 | 정답을 하나라도 맞혔는가; 단일 정답에서는 Recall과 동일 |
| nDCG@10 | 실제 상품을 더 높은 순위에 올렸는가 |
| MRR | 첫 정답의 역순위; 현재 저장된 101개 전체 순위에서 계산 |
| Precision@10 | Top-10 중 정답 비율 |
| MAP@10 | 여러 정답으로 확장할 때 전체 relevant ranking 품질 |

### TactileMatch@10

사용자의 train history 중 소재 target이 있는 상품들을 평균해 tactile profile을 만들고,
Top-10 추천 중 실제 review-derived 소재 target이 존재하는 상품과 cosine similarity를
계산한다.

```text
user tactile profile
    = mean(review-derived target of tactile-covered history items)

TactileMatch@10
    = mean cosine(profile, tactile-covered Top-10 items)
```

점수와 함께 반드시 다음 coverage를 보고한다.

- `tactile_profile_coverage`: profile을 만들 수 있는 사용자 비율
- `tactile_item_coverage@10`: Top-10 중 소재 target이 있는 추천 비율
- `target_tactile_coverage`: 실제 test target의 소재 target 존재 비율

profile과 item coverage가 각각 50% 미만이면 자동으로 `insufficient_coverage`다.

---

## 4. Item/User cohort

각 test 상품은 그 사용자의 test timestamp 이전 train interaction 수로 구간을 나눈다.

| Target item cohort | 정의 | Case |
|---|---:|---:|
| Cold-start | 0 | 86 |
| Long-tail | 1~5 | 184 |
| Mid-tail | 6~20 | 53 |
| Head | 21 이상 | 9 |

사용자 train history도 다음처럼 분리한다.

| User cohort | Train history | Case |
|---|---:|---:|
| Sparse | 2 | 149 |
| Medium | 3~5 | 122 |
| Rich | 6 이상 | 61 |

이 분리를 통해 전체 성능뿐 아니라 `BPR`과 `BPR+tactile`의 차이가 interaction-sparse
사용자·상품에서 커지는지 확인할 수 있다.

---

## 5. 현재 baseline smoke-test 결과

| Model | Recall@10 | nDCG@10 | MRR | TactileMatch@10 | Profile coverage | Item coverage@10 |
|---|---:|---:|---:|---:|---:|---:|
| Popularity | 0.012048 | 0.006166 | 0.018010 | -0.028511 | 0.0904 | 0.0979 |
| Tactile only | 0.015060 | 0.005531 | 0.017172 | -0.044170 | 0.0904 | 0.1199 |
| Popularity + tactile | 0.012048 | 0.006166 | 0.018007 | 0.096208 | 0.0904 | 0.0982 |

세 모델의 TactileMatch는 모두 `insufficient_coverage`다.

Popularity+tactile 대 popularity의 paired 결과:

| 지표 | 차이 | Bootstrap 95% CI | 해석 |
|---|---:|---:|---|
| Recall@10 | 0.000000 | 0.000000 ~ 0.000000 | ranking 개선 없음 |
| nDCG@10 | 0.000000 | 0.000000 ~ 0.000000 | ranking 개선 없음 |
| MRR | -0.000004 | -0.000012 ~ +0.000002 | 차이 없음 |
| TactileMatch@10 | +0.132427 | +0.053565 ~ +0.247887 | 단 20개 paired case; coverage 부족 |

높은 TactileMatch 차이는 전체 추천이 좋아졌다는 뜻이 아니다. profile과 추천 상품 양쪽에
소재 target이 있던 20 case만의 진단값이며, 전체 ranking 정확도는 개선되지 않았다.

---

## 6. Cold-start 결과의 현재 의미

현재 popularity는 cold-start 86 case에서 Recall@10과 nDCG@10이 모두 0이었다. 이는
예상되는 결과다. tactile-only도 cold-start Recall@10이 0이었는데, test cold-start
상품 대부분에 review-derived 소재 target이 없기 때문이다.

향후 이미지→소재 M1을 전체 이미지 상품에 적용하면 cold-start 상품에도 predicted tactile
representation을 부여할 수 있다. 다만 평가 TactileMatch의 정답은 여전히 실제 리뷰
target이어야 하므로 다음을 구분해야 한다.

```text
추천 feature: 이미지에서 예측한 tactile vector 사용 가능
평가 ground truth: 추천 시점 이전 실제 review-derived target 사용
```

---

## 7. BPR/CF 모델 연결 방법

평가 case는 다음 구조로 저장된다.

```json
{
  "case_id": "hashed-id",
  "train_items": ["B...", "B..."],
  "validation_item": "B...",
  "test_items": ["B..."],
  "candidates": ["B...", "B..."],
  "candidate_train_counts": [4, 0],
  "target_item_cohort": "long_tail_1_5",
  "user_cohort": "sparse_history"
}
```

BPR, LightGCN, CF 또는 tactile fusion 모델은 동일 candidate를 점수화해 다음 prediction
JSONL만 만들면 된다.

```json
{"case_id":"hashed-id","ranked_items":["B...","B...","B..."]}
```

평가 예시:

```bash
conda run -n texture python -m offline_eval.cli evaluate \
  --prediction bpr=artifacts/bpr/predictions.jsonl \
  --prediction bpr_tactile=artifacts/bpr_tactile/predictions.jsonl \
  --baseline bpr --k 10
```

evaluator는 다음 오류를 자동 차단한다.

- 누락되거나 중복된 case ID
- candidate set 밖의 추천
- 추천 목록 내부 중복
- K보다 짧은 추천 목록
- 서로 다른 모델의 평가 case 불일치

---

## 8. 재현 명령

```bash
# protocol, baseline, 평가, 보고서를 한 번에 생성
conda run -n texture python -m offline_eval.cli all

# 단계별 실행
conda run -n texture python -m offline_eval.cli prepare
conda run -n texture python -m offline_eval.cli baselines
conda run -n texture python -m offline_eval.cli evaluate \
  --prediction popularity=data/recommendation_eval/temporal_v1/predictions/popularity.jsonl \
  --prediction tactile_only=data/recommendation_eval/temporal_v1/predictions/tactile_only.jsonl \
  --prediction popularity_tactile=data/recommendation_eval/temporal_v1/predictions/popularity_tactile.jsonl
```

백엔드 조회:

```text
GET http://127.0.0.1:8877/api/evaluation
GET http://127.0.0.1:8877/api/evaluation/protocol
```

---

## 9. 주요 산출물

| 경로 | 내용 |
|---|---|
| `offline_eval/` | protocol·baseline·evaluator·report 코드 |
| `data/recommendation_eval/temporal_v1/cases.jsonl` | 고정 평가 case와 candidate |
| `data/recommendation_eval/temporal_v1/manifest.json` | split·hash·cohort manifest |
| `data/recommendation_eval/temporal_v1/predictions/` | baseline prediction 계약 예시 |
| `data/recommendation_eval/temporal_v1/results/metrics.json` | 전체·cohort·bootstrap 결과 |
| `data/recommendation_eval/temporal_v1/results/report.md` | 자동 생성 결과표 |
| `offline_eval/README.md` | 외부 모델 연결 방법 |

## 10. 다음 의사결정 gate

1. 추천 catalog의 최소 50% 이상에 leakage-safe 소재 target을 만든다.
2. 사용자 profile coverage와 Top-10 item coverage가 각각 50%를 넘는지 확인한다.
3. `Popularity → BPR → BPR+일반 content → BPR+tactile` 순서로 동일 case에서 비교한다.
4. primary metric은 nDCG@10, Recall@10으로 고정한다.
5. TactileMatch@10은 coverage gate를 통과한 뒤 공동 primary 또는 secondary metric으로 쓴다.
6. cold-start와 long-tail에서 BPR+tactile의 paired bootstrap CI가 0보다 큰지 확인한다.

이 gate를 통과해야 “촉각 정보가 추천 정확도와 촉각 취향 일치를 개선한다”고 주장할 수
있다.
