# 누락 소재 Span과 Recall 검수 보완

## 결정

기존 139개 사람 검수는 Qwen이 추출한 span이 소재 근거로 맞는지 평가하므로 precision과
판정 일치도를 측정할 수 있지만, Full Review 안에서 Qwen이 아예 뽑지 않은 표현은 측정할
수 없었다. 이를 보완하기 위해 기존 span 판정과 분리된 `Add Missing Span` 및
`Full Review Checked` 절차를 추가했다.

## 검수 원칙

1. 현재 extracted span이 유효하면 그대로 Good으로 둔다.
2. 같은 리뷰에 빠진 소재 표현은 기존 span을 교체하지 않고 별도 missing span으로 추가한다.
3. 하나의 리뷰에 두께·단단함·수축 등 서로 다른 claim이 있으면 각각 독립 span으로 보존한다.
4. quote는 Full Review에 존재하는 원문 그대로여야 하며 백엔드가 exact substring을 검사한다.
5. 리뷰 전체를 끝까지 확인한 뒤에만 `Mark full review checked`를 누른다.

예시:

- 기존 유효 span: `They shrank a little the first time but still fit.`
- 추가할 누락 span 1: `These are the thickest fabric masks I've gotten so far.`
- 추가할 누락 span 2: `The firmer material creates an open pocketing in front of my mouth.`

세 표현은 수축, 두께, 단단함이라는 서로 다른 근거이므로 하나로 합치지 않는다. 이후 리뷰
공간이나 GNN을 만들 때에도 세 개의 claim 노드로 유지한다.

## UI 사용 순서

1. 현재 Extracted Span과 Qwen Judgment를 Good/Bad/Edit로 판정한다.
2. Full Review를 처음부터 끝까지 읽는다.
3. 누락 문장을 드래그해 선택한다.
4. `Add Missing Span` → `Use text selected in full review`를 누른다.
5. normalized claim과 scope, property status, intensity, sentiment, evidence basis,
   visual observability를 입력해 저장한다.
6. 누락이 더 있으면 반복한다.
7. 리뷰 전체 확인이 끝나면 `Mark full review checked`를 누른다.

추가된 누락 span은 주황색으로 강조되며 같은 리뷰의 다른 audit item에서도 동일하게 보인다.
각 누락 span은 Edit/Delete할 수 있다.

## 저장 산출물

| 파일 | 내용 |
|---|---|
| `audit_app/data/annotations.json` | 기존 extracted span 사람 판정 |
| `audit_app/data/missing_spans.json` | missing span 및 Full Review Checked 원본 |
| `audit_app/data/human_semantic_audit_live.csv` | 기존 span 판정 CSV |
| `audit_app/data/human_missing_spans_live.csv` | 누락 span CSV |
| `audit_app/data/human_review_recall_checks_live.csv` | 리뷰 전체 확인 CSV |
| `experiments/03_human_semantic_audit/results/metrics.json` | precision·agreement·observed recall 통합 지표 |

## Recall 정의와 제한

Observed span recall:

`accepted extracted spans / (accepted extracted spans + human-added missing spans)`

계산 대상은 다음 두 조건을 모두 만족한 리뷰다.

- Full Review Checked 상태
- 같은 리뷰의 기존 extracted 후보가 모두 사람 판정 완료

현재 139개 표본은 Qwen이 무언가를 추출한 리뷰에서 만들어졌기 때문에, 이 값은
zero-extraction 리뷰를 포함하는 corpus-wide recall이 아니다. 논문에서 전체 추출 recall을
보고하려면 이후 무작위 리뷰 표본을 별도로 뽑아, Qwen 추출이 0개인 리뷰까지 같은 방식으로
full-review annotation해야 한다.

## 다음 실험 반영

- 프롬프트 개선: missing span을 오류 유형별로 묶어 Stage 1 누락 패턴을 분석한다.
- 전체 데이터 생성: accepted extracted span과 human-added missing span을 동일한 claim schema로
  합친다.
- 리뷰 공간/GNN: claim 단위를 유지하고 Review → Claim 간선으로 연결한다.
- 모델 비교: precision만 높고 recall이 낮은 모델이 유리해지지 않도록 두 지표를 함께 보고한다.

## 구현 검증

- exact quote가 아닌 paraphrase 저장 거부
- 이미 extracted된 quote의 missing 중복 등록 거부
- 같은 리뷰의 동일 missing quote 중복 등록 거부
- missing span 추가·수정·삭제 및 atomic JSON/CSV 갱신
- Full Review Checked 설정·해제
- 판정이 덜 끝난 checked review는 recall 계산에서 제외
- 총 19개 Python 단위 테스트 통과
