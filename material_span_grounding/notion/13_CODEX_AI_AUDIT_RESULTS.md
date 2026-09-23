# Dense-500 Codex AI 자체 검수 결과

> 완료일: 2026-08-13  
> 범위: vLLM dense-500 층화 표본 200 span, review-complete 68개 리뷰  
> 판정자: `codex_ai_adjudicator_not_human`  
> **주의: 사람 검수가 아니며, 독립적인 human gold 또는 논문용 최종 평가로 보고할 수 없다.**

## 결론

Codex가 200개 후보를 전부 다시 읽고 68개 전체 리뷰에서 누락 span을 검사했다.
Qwen 판정 18개를 변경했고, 기존 추출에 없던 소재 근거 24개를 추가했다.

Qwen accepted precision과 rejected false-negative rate는 설정된 판정 gate를 충족했다.
그러나 review-complete 표본의 observed span recall은 82.6%로,
누락 보완 없이 dense gold와 M0/M1 재평가로 바로 넘어가기에는 낮다.

## 검수 범위

| 항목 | 결과 |
|---|---:|
| 후보 판정 | 200 / 200 |
| 전체 리뷰 확인 | 68 / 68 |
| Qwen accepted / rejected 표본 | 120 / 80 |
| Codex accepted / rejected | 114 / 86 |
| 판정 변경 | 18 |
| 추가한 missing span | 24 |

## 판정 지표

| 지표 | 값 | Wilson 95% CI | 개발 기준 |
|---|---:|---:|---:|
| Accepted precision | 90.0% | 83.3%–94.2% | ≥ 90% |
| Rejected false-negative rate | 7.5% | 3.5%–15.4% | ≤ 15% |
| Overall decision accuracy | 91.0% | 86.2%–94.2% | 참고 |
| Scope agreement | 100.0% | 96.6%–100.0% | ≥ 90% |
| Property-status agreement | 96.3% | 90.9%–98.6% | ≥ 90% |
| Visual-observability agreement | 96.3% | 90.9%–98.6% | ≥ 80% |

Confusion matrix:

| | Codex accept | Codex reject |
|---|---:|---:|
| Qwen accept | 108 | 12 |
| Qwen reject | 6 | 74 |

## 누락 Span 검사

| 항목 | 결과 |
|---|---:|
| 계산 가능한 full review | 68 |
| 기존 후보 중 Codex 승인 | 114 |
| Codex가 추가한 missing span | 24 |
| Observed span recall | 82.6% |
| Wilson 95% CI | 75.4%–88.0% |

주요 누락 유형은 보온성·두께·가벼움·비침·부드러움·압박감·내구성·세탁 조건·
안감/마감 같은 component 속성이었다. 이 recall은 추출 후보가 포함된 68개 리뷰 안에서의
진단값이며, 추출 span이 0개인 리뷰까지 포함한 corpus-wide recall은 아니다.

## 오류 요약

- False positive: 12건
- False negative: 6건
- Scope 불일치: 0건
- Property-status 불일치: 4건
- Visual-observability 불일치: 4건

False positive에는 fit/slippage, 색상, vague comfort/quality 표현이 섞인 경우가 많았다.
False negative에는 구멍·봉제 풀림·세탁 후 냄새 제거·장기 내구성 같은 behavior/care 근거가
포함됐다.

## 다음 단계

1. 추가된 24개와 18개 판정 변경 사례를 Recall v2/semantic verification prompt의 회귀
   테스트 세트로 고정한다.
2. 누락 유형을 반영해 recall extraction을 수정하고 dense-500을 다시 추출한다.
3. 같은 68개 리뷰에서 missing span 수가 충분히 감소하는지 재검사한다.
4. 개발은 이 AI 판정을 사용할 수 있지만, 외부 보고·논문용 수치는 소규모라도 독립 사람
   표본으로 최종 확인한다.

## 산출물

- 통합 판정 CSV: `audit_app/data/vllm_dense_500_200_codex_combined/human_semantic_audit_live.csv`
- 통합 missing span CSV: `audit_app/data/vllm_dense_500_200_codex_combined/human_missing_spans_live.csv`
- 통합 review check CSV: `audit_app/data/vllm_dense_500_200_codex_combined/human_review_recall_checks_live.csv`
- 기계 판독 지표: `experiments/11_vllm_dense_500_human_audit/results/codex_ai_combined/metrics.json`
- 오류 사례: `experiments/11_vllm_dense_500_human_audit/results/codex_ai_combined/error_cases.json`
