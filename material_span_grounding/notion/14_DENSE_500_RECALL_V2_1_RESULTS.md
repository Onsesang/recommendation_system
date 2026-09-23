# Dense-500 Recall v2.1 재추출·재검증 결과

> 실행일: 2026-08-13  
> 백엔드: vLLM 0.27.1 / Qwen3-VL-8B-Instruct / BNB 4-bit  
> 개발 근거: Codex AI 자체 검수 200 span + missing span 24건  
> **이 회귀 세트는 사람 gold가 아니며 prompt 개발에 사용됐으므로 독립 평가가 아니다.**

## 결과 요약

| 항목 | v2.0 | v2.1 |
|---|---:|---:|
| 전체 리뷰 | 4,158 | 4,158 |
| exact span | 2,866 | 6,345 |
| semantic schema 성공 | 2,866/2,866 | 6,345/6,345 |
| semantic accepted | 2,591 | 4,527 |
| semantic rejected | 275 | 1,818 |

v2.1 최초 검증에서 1건의 `span_id` 복사 오류가 발생했으며, 정확한 identifier 복사를
강조한 targeted vLLM retry 1건으로 복구했다. 최종
verification SHA-256은 `9f7690cb2aba6c85dd519b3499d28e9dc9c4f0b4261b877ffabea1843203c595`다.

## 68-review 개발 회귀 결과

| 지표 | 보강 후 소규모 점검 | 전체 재실행에서 동일 68리뷰 |
|---|---:|---:|
| 기존 missing 24건 exact 재추출 | 10 / 24 | 10 / 24 |
| 기존 missing 24건 containment coverage | 18 / 24 | 18 / 24 |
| coverage 후 verifier accepted | 17 / 24 | 17 / 24 |

- Codex 승인 전체 138개 추출 coverage: 131 / 138
  (94.9%)
- 기존 200개 후보 중 v2.1에도 exact 존재: 161 / 200
- 존재하는 후보의 Codex 판정 일치: 147 / 161
  (91.3%)
- 과거 오판 18개 중 v2.1에서 판정 교정: 14 /
  14 available

## 해석

이 수치는 누락을 발견하고 prompt를 수정하는 데 사용한 같은 68개 리뷰에서 계산한 개발
회귀 성능이다. 따라서 개선 여부를 확인하는 용도이며 독립적인 일반화 성능으로 보고하지
않는다. 다음 M0/M1 입력은 v2.1 전체 결과로 다시 구성하되, 최종 외부 보고 전에는 별도의
미사용 리뷰 표본을 사람 또는 독립 검수 프로토콜로 확인해야 한다.

## 산출물

- 전체 결과: `data/vllm/dense_500/v2_1_ai_recall/`
- 회귀 fixture: `data/regression/codex_ai_audit_v2_1/fixture.json`
- 소규모 회귀 지표:
  `experiments/12_dense_500_v2_1_ai_recall/regression/regression_metrics.json`
- 전체 재실행 회귀 지표:
  `experiments/12_dense_500_v2_1_ai_recall/full/regression_metrics.json`
