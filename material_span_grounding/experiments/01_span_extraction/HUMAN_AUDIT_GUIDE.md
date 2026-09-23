# Qwen 1차 소재 span 사람 감사 지침

`human_span_audit.csv`의 200개 리뷰를 검토한다. 모델 evidence가 있는 리뷰
100개와 빈 결과 리뷰 100개가 포함돼 precision과 missed span을 함께 볼 수 있다.

## 작성 열

- `human_gold_quotes`: 리뷰에 실제로 존재하는 모든 소재 span을 원문 그대로
  ` || `로 구분해 기록한다.
- `human_false_positive_quotes`: `model_quotes` 중 소재 정보가 아닌 것을 원문
  그대로 기록한다.
- `human_missed_quotes`: 모델이 빠뜨린 소재 span을 원문 그대로 기록한다.
- `annotator_id`: 검토자 ID를 기록한다.
- `comment`: scope 경계, 핏과 소재의 모호성 등 판단 근거를 적는다.

## 판정 원칙

- 원문의 정확한 substring만 사용한다.
- 부정어, 강도, 비교, 불확실성 표현을 포함한다.
- 소재 원인이 없는 `comfortable`, `nice`, `good quality`는 제외한다.
- 색상·배송·가격·사이즈·핏은 제외한다.
- 원단의 광택·짜임·비침처럼 소재와 직접 관련된 외관은 포함한다.
- 안감·겉감·목 부분처럼 특정 부분에 한정된 표현도 포함하되 comment에 scope를
  기록한다.

두 사람이 독립 작성한 뒤 span precision/recall/F1과 불일치 사례를 계산하는
것을 권장한다.

