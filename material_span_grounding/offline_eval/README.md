# Offline Recommendation Evaluation

Amazon Fashion `user_id-item-timestamp` interaction으로 다음 긍정 상품 ranking을 평가한다.
모든 모델은 저장된 동일 candidate set을 사용한다.

## 한 번에 실행

```bash
conda run -n texture python -m offline_eval.cli all
```

기본 protocol:

- rating 4~5를 positive interaction으로 사용
- 사용자별 동일 상품 반복은 마지막 timestamp 하나로 통합
- 최소 positive 4개 사용자
- 시간순 이전 상품=train, 끝에서 두 번째=validation, 마지막=test
- test target 1개 + 사용자 미관측 negative 100개
- 각 test timestamp 이전에 train에서 등장한 상품만 negative 후보로 사용
- negative는 해당 시점 train popularity의 제곱근에 비례해 고정 seed로 비복원 추출
- raw `user_id`는 저장하지 않고 SHA-256 기반 `case_id`만 저장

## 외부 BPR/CF 모델 평가

모델은 `cases.jsonl`의 `train_items`, `validation_item`, `candidates`를 사용하고 다음 JSONL을
출력하면 된다. MRR도 같은 전체 후보군에서 공정하게 계산하기 위해 모든 candidate를
누락 없이 점수순으로 정렬해야 한다.

```json
{"case_id":"...","ranked_items":["B...","B...","B..."]}
```

```bash
conda run -n texture python -m offline_eval.cli evaluate \
  --prediction popularity=data/recommendation_eval/temporal_v1/predictions/popularity.jsonl \
  --prediction bpr=artifacts/bpr/predictions.jsonl \
  --prediction bpr_tactile=artifacts/bpr_tactile/predictions.jsonl \
  --baseline bpr --k 10
```

출력 지표:

- Precision@K, Recall@K, Hit Rate@K, nDCG@K, MRR, MAP@K
- TactileMatch@K
- tactile profile coverage와 추천 item coverage
- cold-start, long-tail, mid-tail, head item cohort
- sparse/medium/rich user-history cohort
- baseline 대비 paired bootstrap 95% CI

현재 test 정답은 사용자당 1개이므로 이 protocol에서는 `Recall@K = Hit Rate@K`이고
`Precision@K = Recall@K / K`다. 다중 정답 protocol을 추가하면 세 지표가 서로 달라진다.

## 중요한 해석 규칙

현재 open-vocabulary 소재 target은 438상품만 포함한다. 따라서 TactileMatch 점수는 반드시
`tactile_profile_coverage`와 `tactile_item_coverage@K`와 함께 보고한다. coverage가 없으면
점수를 만들지 않고 `N/A`로 둔다. 두 coverage가 각각 50% 미만이면 자동으로
`tactile_match_status=insufficient_coverage`가 붙는다.

현재 item target은 추천 test timestamp 이전 리뷰만으로 다시 만든 것이 아니므로 tactile
결과는 진단용이다. 논문 최종 실험에서는 global cutoff 또는 각 fold의 train 기간 이전
리뷰만 사용해 target과 text transform을 다시 생성해야 한다.
