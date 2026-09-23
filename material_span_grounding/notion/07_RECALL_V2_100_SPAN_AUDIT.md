# RECALL V2 — 100 Span 사람 검수 계획

> 변경일: 2026-08-09  
> 상태: 활성화 완료, 0 / 100에서 검수 시작  
> 서비스: `http://localhost:8765`  
> 활성 데이터: `audit_app/data/v2_100`

## 변경 이유

최초 RECALL V2 검수 pool은 150개 리뷰의 342개 span이었다. 전량 수동 검수 부담이 큰
점을 고려해, prompt의 품질을 판단할 수 있는 100개 span만 우선 검수하는 방향으로
변경했다.

342개 중 앞에서부터 100개를 자르지 않았다. 그렇게 하면 한 리뷰의 일부 sibling만 남거나
표본 초반 상품에 치우칠 수 있기 때문이다. 고정 seed를 사용해 리뷰 단위로 표본을 뽑고,
원래 pool의 New V2·Qwen Reject·회복 리뷰 비율을 유지했다.

## 활성 표본

| 항목 | 개수 |
|---|---:|
| 전체 span | 100 |
| 전체 리뷰 | 47 |
| Qwen accepted | 80 |
| Qwen rejected | 20 |
| New V2 span | 26 |
| 기존 audit 리뷰의 span | 86 |
| v1 추출 0건에서 회복된 리뷰의 span | 14 |
| 표본 seed | 20260809 |

선택된 리뷰의 extracted sibling은 전부 포함한다. 따라서 한 리뷰에 span이 3개 있으면 세
span 모두 100개 안에 들어가며, 리뷰 단위 누락 검사를 수행할 수 있다.

## 기존 검수 기록 처리

342개 세트에서 저장했던 기록은 다음과 같았다.

- Good: 5개
- Edit: 1개
- Bad: 0개
- Missing span: 0개
- Full Review Checked: 0개

이 6개 기록은 새 100개 검수 결과에 재사용하지 않고 초기화했다. 삭제 대신 아래 경로에
복구 가능한 상태로 보존했다.

`experiments/03_human_semantic_audit/archives/v2_342_cancelled_20260809/`

이전 v1 사람 판정 21개도 별도 archive에 유지된다.

## 판정 규칙

버튼은 Qwen과의 일치 여부가 아니라 사람의 최종 span 유효성을 뜻한다.

| Qwen | 사람 판단 | 누를 버튼 |
|---|---|---|
| Accept | 유효함 | Good |
| Accept | 유효하지 않음 | Bad |
| Reject | 기각에 동의 | Bad |
| Reject | 실제로 유효함 | Good 후 Edit 필드 입력 |
| Accept/Reject | 소재 정보는 맞지만 구조화가 틀림 | Edit |

`→`와 `Next`는 현재 span을 Good으로 저장하는 동작이다. Qwen Reject에 동의할 때는
방향키로 넘기지 말고 `Bad`을 누른다.

## 리뷰 단위 검수 순서

1. 현재 `EXTRACTED SPAN`과 `QWEN JUDGMENT`를 확인한다.
2. sibling 목록에 있는 같은 리뷰의 모든 span을 각각 Good·Bad·Edit한다.
3. Full Review 전체를 읽고 누락된 소재 표현이 있으면 `Add Missing Span`으로 추가한다.
4. 해당 리뷰의 모든 extracted span을 판정한 뒤 `Full Review Checked`를 기록한다.

## 100개 완료 후 볼 지표

- Qwen accepted 후보의 human precision
- Qwen rejected 후보 중 사람이 되살린 비율
- New V2 후보의 human precision
- 기존 v1 span과 New V2 span의 품질 차이
- Full Review Checked 리뷰에서 발견된 missing span 수
- observed span recall
- scope·property status·visual observability 수정률

후보 증가율은 recall 자체가 아니다. 실제 recall 판단은 Full Review Checked 리뷰에서
사람이 추가한 missing span까지 포함해 계산한다.

## 재현 명령

```bash
cd /home/user/onsesang/material_span_grounding
python -m audit_app.build_v2_manifest \
  --target-items 100 \
  --sample-seed 20260809 \
  --output-root audit_app/data/v2_100
```

