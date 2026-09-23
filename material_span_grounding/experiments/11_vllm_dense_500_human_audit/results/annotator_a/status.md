# 사람 Semantic Audit 자동 품질 상태

> 자동 갱신: 2026-08-25T04:51:50.791705+00:00  
> 상태: `final_pass`  
> 개발 트리거: `False`

## 진행률

- 라벨 완료: 100 / 100
- Qwen 통과 표본 라벨: 60
- Qwen 기각 표본 라벨: 40
- Annotator: codex_ai_adjudicator_not_human

50개 전체, Qwen 통과 30개, Qwen 기각 15개가 모이기 전에는 모델을 수정하지 않는다.
중간에는 심각한 실패만 개발을 시작하고, 최종 기준은 100개 완료 시 적용한다.

## 판단 지표

| 지표 | 현재 값 | 최종 기준 |
|---|---:|---:|
| Accepted precision | 95.0% | ≥ 90% |
| Rejected false-negative rate | 5.0% | ≤ 15% |
| Overall decision accuracy | 95.0% | 참고 |
| Scope agreement | 100.0% | ≥ 90% |
| Property-status agreement | 96.5% | ≥ 90% |
| Visual-observability agreement | 96.5% | ≥ 80% |

## 누락 Span 기반 Recall 점검

- Full review checked: 35개 리뷰
- Recall 계산 가능: 35개 리뷰
- 기존 추출 중 사람 승인: 59개
- 사람이 추가한 누락 span: 17개
- Observed span recall: 77.6%

이 값은 현재 표본 안에서 full review 확인을 완료한 리뷰만 대상으로 한 진단값이다.
추출 span이 전혀 없었던 리뷰는 이 extracted-span 표본에 포함되지 않으므로 corpus-wide recall로
해석하지 않는다.

## 현재 실패 항목

- 없음

## 자동 오류 분해

- False positive: 3건
- False negative: 2건
- Scope 불일치: 0건
- Property-status 불일치: 2건
- Visual-observability 불일치: 2건

False-positive 유형:

- `other`: 3건

전체 오류 문맥은 `error_cases.json`에 저장된다.

## 해석 규칙

- `waiting_for_labels`: 표본 부족. 변경 금지.
- `provisional_monitoring`: 조기 심각 실패 없음. 계속 검수.
- `early_severe_failure`: 충분한 표본에서 큰 오류. 오류 유형 분석과 개발 시작.
- `final_needs_development`: 100개 완료 후 최종 기준 미달. 개발 시작.
- `final_pass`: 다음 단계인 dense gold 구성과 M0/M1 재평가로 진행 가능.

사람 검수가 한 명뿐이면 이 수치는 단일 annotator 기준이다. 최종 논문 보고 전에는
두 번째 annotator의 독립 표본으로 inter-annotator agreement를 추가하는 것이 좋다.
