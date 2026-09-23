# 실험 02 — Qwen 소재 semantic verification pilot

## 목적

1차 Qwen이 복사한 exact span이 실제 소재 evidence인지 다시 검증하고, 채택된
span에 자유 텍스트 claim과 scope·극성·강도·근거 방식·시각 관찰 가능성을 붙인다.
고정 소재 taxonomy로 분류하지 않는다.

## 입력과 누수 통제

- 입력 exact span: 669개
- 원천: 실험 01의 train-only 리뷰 1,000건
- validation/calibration/protected test: 사용하지 않음
- 모델: `Qwen/Qwen3-VL-8B-Instruct`
- prompt: `semantic_verification_v1.1`
- 생성 시간: 52.3분

## 자동 결과

- schema 검증 성공: 669/669
- schema 재시도: 1회
- 채택: 630개 (94.2%)
- 거절: 39개
- ambiguous로 표시된 채택 span: 0개

| 필드 | 분포 |
|---|---|
| scope | main_fabric=474, component=56, whole_garment=90, lining=9, outer_surface=1 |
| property_status | present=565, absent=50, uncertain=6, comparative=9 |
| intensity | none=419, strong=163, slight=46, moderate=2 |
| sentiment | positive=286, neutral=228, negative=116 |
| evidence_basis | direct_touch=135, unspecified=254, visual_only=129, worn_experience=37, product_behavior=75 |
| visual_observability | low=323, medium=178, unknown=40, high=89 |

## Prompt smoke test와 경계 진단

- v1.0 16-span smoke test에서 단순 `thick`을 `strong/direct_touch`로 과대
  구조화하고 `likely cotton`을 확정 진술로 처리해 실행을 중단했다. 해당 결과는
  `pilot_v1_0/`에 보존했다.
- v1.1은 강도·불확실성·근거 방식을 명시적 어휘에 근거하도록 수정했고 전체
  669개를 이 버전으로 다시 처리했다.
- v1.1은 1차 span의 94.2%를 채택해
  강한 필터보다 metadata 정제기로 동작했다.
- 자동 lexical 감사에서 구체 속성 keyword가 없는 comfort/quality 계열 채택
  후보가 20개, 부속품 keyword 채택 후보가
  2개 발견됐다. 예: `Material feels nice`,
  `the zipper - it seems that it is a cheaper fabrication`.
- 이 flag는 사람이 확인할 우선 표본이지 자동 오답 수가 아니다.

## 해석

채택률은 semantic precision이 아니다. 같은 Qwen 계열 모델이 1차 후보를 만들고
2차 판정도 했으므로 오류가 상관될 수 있다. 특히 self-contained claim이 원문
의미를 보존하는지, `comfortable` 같은 모호 표현이 적절히 제거됐는지,
visual observability 판정이 일관적인지는 사람 감사가 필요하다.

## 다음 단계

1. accepted 100개와 rejected 전체 39개의 사람 semantic audit을 수행한다.
2. accepted precision, rejected false-negative rate, scope/status/observability agreement를 계산한다.
3. 통과한 span만 동일 사용자 반복 제거와 polarity-aware semantic deduplication에 전달한다.
