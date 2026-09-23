# vLLM Dense-500 층화 사람 검수

> 준비일: 2026-08-13  
> 입력: vLLM dense-500 Recall v2 검증 결과 2,866 span  
> 상태: Codex AI 자체 검수 완료, 독립 사람 검수는 미실시

> 2026-08-13 변경: 두 작업자가 검수할 시간이 없어 사용자의 요청에 따라 Codex가 두
> 표본을 직접 판정했다. 따라서 아래의 원래 사람 검수 설계와 링크는 재현을 위해 보존하지만,
> 생성된 판정은 human gold가 아니다. 결과는 `notion/13_CODEX_AI_AUDIT_RESULTS.md`를 본다.

## 검증본 고정

- semantic schema 성공: 2,866 / 2,866
- Qwen accepted: 2,591
- Qwen rejected: 275
- 2회 실패했던 1건은 identifier 복사를 강조한 3차 vLLM 재검증으로 통과
- 최종 verification SHA-256:
  `7c1583dd803dd51c285fb1757593fd829c12fa4943850dfa9d854a3eb78e7c9b`

## 감사 표본

| 항목 | 값 |
|---|---:|
| 전체 span | 200 |
| Qwen accepted | 120 |
| Qwen rejected | 80 |
| review-complete 리뷰 | 68 |
| 상품 | 65 |
| 로컬 이미지 | 200 / 200 |
| 선택 seed | 20260813 |

표본은 span을 독립적으로 잘라 뽑지 않았다. 리뷰 하나가 선택되면 그 리뷰의 모든 sibling
span을 포함했다. accepted/rejected 결정층, 상품 제목 기반 카테고리, 최종 소재 근거 사용자
수 구간을 함께 고려해 결정적으로 선택했다.

### 카테고리 분포

| 카테고리 | span |
|---|---:|
| accessory | 25 |
| dress | 32 |
| other | 16 |
| outerwear | 12 |
| pants | 35 |
| skirt | 9 |
| sleepwear | 16 |
| sweater | 9 |
| swimwear | 3 |
| top | 25 |
| underwear | 18 |

### 상품별 소재 근거 사용자 구간

| 구간 | span |
|---|---:|
| 1명 | 11 |
| 2–3명 | 93 |
| 4명 이상 | 96 |

## 원래 사람 검수 방법

두 사람이 동시에 작업하도록 review-complete 표본을 겹치지 않는 두 묶음으로 분리했다.

| 담당 | 링크 | span | 리뷰 | accepted / rejected |
|---|---|---:|---:|---:|
| Annotator A | `http://100.96.162.32:8765` | 100 | 35 | 60 / 40 |
| Annotator B | `http://100.96.162.32:8766` | 100 | 33 | 60 / 40 |

두 링크는 Tailscale 주소이므로 두 작업자 모두 같은 tailnet에 접속해야 한다. A와 B 사이의
span 및 리뷰 중복은 0개이며 합집합은 원본 200개 전체와 같다.

1. 각 span을 Good, Bad 또는 Edit로 판정한다.
2. sibling 목록을 먼저 확인한 뒤 전체 리뷰에서 누락 span을 찾는다.
3. 리뷰의 모든 후보를 판정하고 누락 검사를 마치면 `Mark full review checked`를 누른다.
4. Qwen reject에 동의하면 Bad, reject를 뒤집으면 Good 또는 Edit를 사용한다.

## 품질 gate

- accepted precision ≥ 90%
- rejected false-negative rate ≤ 15%
- scope agreement ≥ 90%
- property-status agreement ≥ 90%
- visual-observability agreement ≥ 80%
- review-complete 표본의 observed span recall을 별도로 기록

Codex AI 판정의 precision 관련 gate는 통과했지만 observed span recall이 82.6%였다. 누락
유형을 반영해 추출을 개선·재실행한 뒤 dense gold 150–300상품 구성과 M0/M1 재평가로
진행한다. 논문용 최종 수치는 별도의 독립 사람 표본이 필요하다.

## 산출물

- UI manifest: `audit_app/data/vllm_dense_500_200/items.json`
- Annotator A: `audit_app/data/vllm_dense_500_200_a/`
- Annotator B: `audit_app/data/vllm_dense_500_200_b/`
- 원본 감사표: `audit_app/data/vllm_dense_500_200/human_semantic_audit.csv`
- 실시간 판정: `audit_app/data/vllm_dense_500_200/annotations.json`
- 품질 지표: `experiments/11_vllm_dense_500_human_audit/results/metrics.json`
- Codex AI 통합 결과: `notion/13_CODEX_AI_AUDIT_RESULTS.md`
- Codex AI 통합 지표:
  `experiments/11_vllm_dense_500_human_audit/results/codex_ai_combined/metrics.json`
