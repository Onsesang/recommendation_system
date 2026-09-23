# Offline Recommendation Evaluation

> 평가 case: 332 · candidate ranking · K=10

## Overall

| Model | Recall@10 | Hit Rate@10 | nDCG@10 | MRR | Precision@10 | MAP@10 | Tactile Match@10 | Tactile profile coverage | Tactile item coverage@10 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| popularity | 0.012048 | 0.012048 | 0.006166 | 0.018010 | 0.001205 | 0.004476 | -0.028511 (insufficient_coverage) | 0.090361 | 0.097892 |
| tactile_only | 0.015060 | 0.015060 | 0.005531 | 0.017172 | 0.001506 | 0.002769 | -0.044170 (insufficient_coverage) | 0.090361 | 0.119880 |
| popularity_tactile | 0.012048 | 0.012048 | 0.006166 | 0.018007 | 0.001205 | 0.004476 | 0.096208 (insufficient_coverage) | 0.090361 | 0.098193 |

## 해석 주의

- 모든 모델은 저장된 동일 candidate set에서 평가한다.
- Tactile Match는 coverage와 함께 해석한다. coverage가 낮은 높은 점수는 전체 추천 품질을 뜻하지 않는다.
- 현재 소재 target은 추천 시점 이전 리뷰만으로 재구성한 것이 아니므로 tactile 결과는 진단용이다.
- 최종 논문 결과에서는 global time cutoff 이전 리뷰로 item target을 다시 만들어야 한다.

## Cohort

### popularity: target item cohort

- `cold_start`: n=86, Recall@10=0.000000, nDCG@10=0.000000, MRR=0.009901
- `head_21_plus`: n=9, Recall@10=0.444444, nDCG@10=0.227463, MRR=0.202066
- `long_tail_1_5`: n=184, Recall@10=0.000000, nDCG@10=0.000000, MRR=0.011502
- `mid_tail_6_20`: n=53, Recall@10=0.000000, nDCG@10=0.000000, MRR=0.022510

### tactile_only: target item cohort

- `cold_start`: n=86, Recall@10=0.000000, nDCG@10=0.000000, MRR=0.010309
- `head_21_plus`: n=9, Recall@10=0.333333, nDCG@10=0.116352, MRR=0.092112
- `long_tail_1_5`: n=184, Recall@10=0.010870, nDCG@10=0.004288, MRR=0.015269
- `mid_tail_6_20`: n=53, Recall@10=0.000000, nDCG@10=0.000000, MRR=0.022189

### popularity_tactile: target item cohort

- `cold_start`: n=86, Recall@10=0.000000, nDCG@10=0.000000, MRR=0.009901
- `head_21_plus`: n=9, Recall@10=0.444444, nDCG@10=0.227463, MRR=0.202066
- `long_tail_1_5`: n=184, Recall@10=0.000000, nDCG@10=0.000000, MRR=0.011499
- `mid_tail_6_20`: n=53, Recall@10=0.000000, nDCG@10=0.000000, MRR=0.022495

