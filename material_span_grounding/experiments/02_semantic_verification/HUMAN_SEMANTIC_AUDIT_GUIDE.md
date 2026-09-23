# Qwen 2차 semantic verification 사람 감사 지침

`human_semantic_audit.csv`에는 Qwen이 채택한 span 최대 100개와 거절한 span 최대
100개가 포함된다. 같은 원문과 quote를 보고 Qwen 출력과 독립적으로 판단한다.

## 작성 열

- `human_accepted`: 소재 evidence이면 `true`, 아니면 `false`
- `human_claim`: 원문 의미를 보존한 독립적인 자유 텍스트 claim
- `human_scope`: `main_fabric`, `outer_surface`, `lining`, `component`,
  `whole_garment`, `unknown`
- `human_property_status`: `present`, `absent`, `comparative`, `uncertain`,
  `mixed`, `not_applicable`
- `human_visual_observability`: `high`, `medium`, `low`, `unknown`
- `annotator_id`: 검토자 ID
- `comment`: 경계 판단과 Qwen 오류 설명

## 핵심 판정 원칙

- quote가 아니라 원문 전체 문맥을 함께 읽는다.
- `comfortable`, `nice`, `quality`는 구체 소재 원인이 없으면 거절한다.
- `looks`, `seems`, `likely`, `might`가 있으면 `uncertain`을 우선 검토한다.
- `not itchy`, `not see-through`처럼 명시적 부재는 `absent`다.
- 평범한 `soft`, `thick`에는 원문에 없는 강도나 감각 근거를 추가하지 않는다.
- scope가 부품에 한정되면 상품 전체로 확대하지 않는다.
- 시각 관찰 가능성과 사용자 중요도는 다르다. irritation은 중요하지만 이미지
  관찰 가능성은 낮다.

두 명이 독립 검토한 뒤 accepted precision, rejected false-negative rate,
scope/status/observability agreement를 계산하는 것을 권장한다.

