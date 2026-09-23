# 실험 04 — Recall 중심 소재 Span 재수집 v2

## 결론 요약

- 동일 train-only 리뷰: 1,000개
- v1 exact span: 669개
- v2 union 후보: 898개
- 후보 증가: +229개 (34.2%)
- v1 evidence 0개에서 새 후보가 생긴 리뷰: 62개
- 새 후보 Qwen 2차 채택: 157/229

## 방법

v1 결과를 안전망으로 유지하고, 리뷰 전체를 두 번 독립적으로 탐색했다.

1. surface/use lens: 정체성·촉감·두께·구조·신축·통기·착용 반응
2. behavior/care lens: 세탁·수축·보풀·손상·흡수·형태 변화·내구
3. exact substring 코드 검사
4. 기존 quote와 포함 관계인 후보 병합
5. v1과 v2 후보 union
6. 기존 span의 Qwen v1.1 판단은 재사용하고 새 span만 의미 검증

## 해석 제한

후보 수 증가는 recall 향상의 가능성을 보여주지만, 그 자체가 recall 향상을 증명하지는
않는다. 새 후보에는 fit·construction 같은 false positive가 포함될 수 있어 Qwen verifier와
새 사람 검수를 거친다. 최종 평가는 review-complete audit의 accepted precision과 사람이
추가한 missing span 기반 observed recall로 판단한다.
