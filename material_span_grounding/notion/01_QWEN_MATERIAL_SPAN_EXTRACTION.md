# 소재 서술 파이프라인 — 1차 소재 span 추출

> 실험일: 2026-08-04  
> 프로젝트: `/home/user/onsesang/material_span_grounding`  
> 상태: Qwen 1차 exact-span pilot 완료, 사람 의미 검증 대기



리뷰를 요약하거나 고정 소재 class로 분류하지 않고, 원문에서 명시적으로 언급된
소재·질감 evidence span을 그대로 복사한다. 후속 Qwen 검증과 상품 embedding의
추적 가능한 입력을 만드는 단계다.

## 데이터와 누수 통제

- split: `seoyoung` train only
- 리뷰: 1,000건, 상품 931개
- 상품당 최대 리뷰: 2건
- 표본: seed 42 SHA-256 결정적 표본
- validation/calibration/protected test: 사용하지 않음

## 실행 설정

- 모델: `Qwen/Qwen3-VL-8B-Instruct`
- prompt: `span_extraction_v1.0`
- batch size: 8
- strict JSON 실패 시 최대 시도: 2회
- 생성 시간: 26.0분
- 처리량: 0.64 reviews/s

## 자동 검증 결과

| 상태 | 리뷰 수 |
|---|---|
| partial_invalid_quote | 26 |
| success | 974 |

- evidence가 발견된 리뷰: 406/1,000
  (40.6%)
- 유효 exact span: 669개
- 원문에 없는 quote: 29개
- exact quote 자동 유효율: 95.8%
- 리뷰당 span: 평균 0.67,
  중앙값 0.0

## 자주 추출된 exact quote

| 원문 구절 | 횟수 |
|---|---|
| soft | 15 |
| super soft | 13 |
| very soft | 9 |
| comfortable | 8 |
| lightweight | 8 |
| and stretchy | 6 |
| breathable | 6 |
| very thin | 6 |
| light weight | 4 |
| the fabric is thick | 4 |
| warm | 4 |
| stretchy | 4 |
| thick | 4 |
| not see through | 3 |
| very comfortable | 3 |
| it is so soft | 3 |
| cozy | 3 |
| very warm | 3 |
| the material was very thin | 2 |
| material is thick | 2 |

## 기존 방식과 비교

기존 `exp_k_open_vocab.py`는 400개 리뷰에서 439개 정규화 구절을 얻었지만,
`very soft → soft`처럼 강도를 제거했고 원문 span·review ID·user ID를 보존하지
않았다. 이번 방식은 표현을 정규화하지 않고 exact substring만 채택해 모든 결과를
원문과 사용자까지 역추적할 수 있다.

## 관찰된 v1.0 개선점

1. Qwen이 반환한 quote 698개 중 29개는 대소문자 변경,
   축약 또는 paraphrase 때문에 exact substring 검사를 통과하지 못했다. 다음
   prompt에서는 `partial_invalid_quote`도 원문과 함께 한 번 교정 재시도한다.
2. `comfortable` 8회, `very comfortable` 3회처럼 소재 원인이 명시되지 않은
   일반 편안함 후보가 남았다. 1차에서 무리하게 없애기보다 사람 감사와 2차
   semantic verifier에서 제외하는 편이 recall 보존에 안전하다.
3. `and stretchy`처럼 문법적으로 불완전하지만 원문에는 정확히 존재하는 span이
   발생했다. 후속 embedding에는 exact quote와 별도로, 2차 검증을 통과한
   self-contained claim을 사용해야 한다.
4. 핏 문맥의 `they do stretch very well` 같은 표현은 소재 stretch인지 의복 fit인지
   경계가 모호해 누락될 수 있다. 빈 결과 표본의 missed span을 사람이 별도로
   기록해야 recall을 측정할 수 있다.
5. 이번 40.6%는 무작위 리뷰 한 건 단위
   후보 발견률이다. 기존 98%는 상품당 여러 리뷰를 합친 상품 coverage이므로 두
   값을 직접 비교하지 않는다.

## 해석 제한

exact substring 검사는 Qwen이 문장을 실제로 복사했는지만 보장한다. 그 구절이
정말 소재 정보인지, 소재 구절을 얼마나 놓쳤는지는 사람 gold 없이는 알 수 없다.
따라서 이 결과의 coverage를 소재 정보 보유율이나 extraction recall로 해석하지
않는다.

## 다음 단계

1. evidence가 있는 리뷰와 빈 리뷰를 층화해 사람 감사 표본을 만든다.
2. span precision/recall과 negation 보존 정확도를 측정한다.
3. 통과한 span만 Qwen 2차 검증으로 보내 scope·극성·관찰 가능성을 구조화한다.
4. 동일 사용자 반복 제거와 semantic deduplication은 코드로 수행한다.


## 산출물

| 파일 | 설명 |
|---|---|
| `data/input/reviews_pilot.jsonl` | 결정적으로 선택한 원문 리뷰 |
| `data/output/raw_generations.jsonl` | Qwen 원시 응답과 재시도 기록 |
| `data/output/span_extractions.jsonl` | 코드 검증을 통과한 exact spans |
| `experiments/01_span_extraction/results/metrics.json` | 기계 판독 결과 |
| `experiments/01_span_extraction/results/examples.json` | 검토용 예시 |
| `experiments/01_span_extraction/human_span_audit.csv` | positive/empty 층화 사람 감사표 |

## 전체 파이프라인에서의 위치

```text
[완료] Qwen 1차 소재 span 추출
   ↓
[다음] Qwen 2차 소재 여부·scope·극성 검증
   ↓
exact quote 검사 → 사용자 반복 제거 → semantic dedup
   ↓
사용자 합의도·가중치 → 상품 target embedding → M1~M5 비교
```
