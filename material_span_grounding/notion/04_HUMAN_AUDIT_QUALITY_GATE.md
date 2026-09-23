# 사람 검수 자동 품질 Gate

## 목적

사람 라벨이 충분하지 않은 상태에서 몇 개의 오류만 보고 프롬프트를 과적합하지 않도록,
검수 결과가 저장될 때마다 품질 지표를 자동 계산하고 개발 시작 조건을 고정한다.

## 현재 상태 확인

검수가 진행 중이므로 문서에 숫자를 고정하지 않고 아래 자동 갱신 산출물을 기준으로 본다.

상태 파일은 검수 앱에서 Good, Bad, Edit가 저장될 때마다 자동 갱신된다.

- `experiments/03_human_semantic_audit/results/metrics.json`
- `experiments/03_human_semantic_audit/results/status.md`
- API: `GET /api/quality`

`recall_audit`에는 Full Review Checked 리뷰 수, 사람이 추가한 missing span 수와 observed
span recall이 함께 기록된다. 판정이 덜 끝난 checked review는 recall 계산에서 자동 제외된다.

## 최소 표본 Gate

다음 조건을 모두 만족하기 전에는 프롬프트나 모델을 수정하지 않는다.

| 조건 | 최소값 |
|---|---:|
| 전체 사람 라벨 | 50 |
| Qwen 통과 표본 라벨 | 30 |
| Qwen 기각 표본 라벨 | 15 |
| Metadata agreement 비교쌍 | 25 |

중간 표본에서는 accepted precision 80% 미만, rejected false-negative rate 30% 초과
등의 심각한 실패만 조기 개발을 시작한다.

## 139개 완료 후 최종 기준

| 지표 | 통과 기준 |
|---|---:|
| Accepted precision | 90% 이상 |
| Rejected false-negative rate | 15% 이하 |
| Scope agreement | 90% 이상 |
| Property-status agreement | 90% 이상 |
| Visual-observability agreement | 80% 이상 |

하나라도 기준을 충족하지 못하면 `final_needs_development`가 되고 오류 유형 분석,
프롬프트 수정, GPU 재검증, 개선 전후 비교 순으로 진행한다.

## 상태 의미

- `waiting_for_labels`: 표본 부족, 변경 금지
- `provisional_monitoring`: 충분한 중간 표본이며 심각한 실패 없음
- `early_severe_failure`: 조기 기준에서 큰 오류 발견, 개발 시작
- `final_needs_development`: 전체 검수 후 최종 기준 미달, 개발 시작
- `final_pass`: 동일 사용자 반복 제거 단계로 진행 가능

## 주의사항

한 명의 annotator 결과만 있으면 단일 annotator 기준 정확도다. 논문 최종 보고에는 두 번째
annotator의 독립 표본을 추가하고 inter-annotator agreement를 계산하는 것이 권장된다.
