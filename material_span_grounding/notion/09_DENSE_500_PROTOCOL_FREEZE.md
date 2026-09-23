# DENSE 500 실험 Protocol Freeze

> 동결일: 2026-08-13  
> 범위: 500상품·4,158리뷰 Recall v2 수집과 M0/M1 재평가  
> 데이터 원칙: 공식 train split만 사용, protected test 미사용

## 동결 목적

500상품 실험 결과를 본 뒤 prompt, target 또는 평가 기준을 바꾸는 선택 편향을 막기 위해
실행 전에 입력과 protocol을 고정한다. 전체 machine-readable 기록은
`data/manifests/dense_500_protocol_freeze.json`에 보존한다.

## 입력

| 항목 | 값 |
|---|---:|
| 상품 | 500 |
| 리뷰 | 4,158 |
| 상품당 고유 사용자 | 최소 5명 |
| 사용자당 리뷰 | 1개 |
| 이미지 | 모든 상품에 존재 |
| 표본 seed | 42 |
| 입력 SHA-256 | `ac2b3b6e061dacaaefcf601532496e291ee4edb022ff194a99cf755f365ab3d8` |

## 수집 및 검증

- 모델: `Qwen/Qwen3-VL-8B-Instruct`
- 모델 snapshot: `0c351dd01ed87e9c1b53cbc748cba10e6187ff3b`
- 추출: surface/use와 behavior/care 두 lens의 exact-quote union
- 의미 검증: `semantic_verification_v1.1`
- 기존 결과가 있는 경우 exact span과 검증 결과를 재사용한다.
- 현재 dense 500 입력에는 실질적으로 신규 리뷰가 대부분이므로 전체 생성 비용을 기록한다.

## 상품 target

```text
Qwen accepted open-vocabulary claim
→ 동일 사용자 내 normalized exact claim 중복 제거
→ 사용자별 claim 벡터 평균 및 L2 정규화
→ 사용자별 동일 가중 평균
→ 상품 벡터 L2 정규화
```

상반된 claim은 제거하지 않는다. 소재를 언급하지 않은 사용자는 target 평균에 넣지 않으며,
상품별 유효 근거 사용자 수를 별도 보고한다.

## 평가 protocol

| 항목 | 동결값 |
|---|---|
| 분할 | parent/product group-safe 5-fold outer holdout |
| alpha 선택 | fold 내부 validation |
| Category baseline | 같은 카테고리 후보 안에서 무작위 순위 |
| M0 | 원본 동결 이미지 feature + L2 normalization |
| M1 | StandardScaler + multi-output Ridge |
| Primary metric | Same-category material cosine@5 |
| Secondary metrics | nDCG@5, Material cosine@5 |
| 불확실성 | query-level bootstrap 95% CI |

개발 통계로 표준화한 M0는 diagnostic으로만 보고하며 결론의 M0로 사용하지 않는다.

## 다음 모델 진입 gate

다음 조건을 모두 확인하기 전에는 관계 구조 증류, 순위 학습 또는 GNN을 주 실험으로
확장하지 않는다.

1. M1−M0의 primary metric bootstrap 95% CI 하한이 0보다 크다.
2. fold 또는 반복 seed 대부분에서 개선 방향이 양수다.
3. 층화 사람 검수에서 Qwen accepted precision이 90% 이상 유지된다.
4. 향상이 category shortcut만으로 설명되지 않는다.

## 동결 해시

| 대상 | SHA-256 |
|---|---|
| Surface prompt | `362acaa7641b5486d19b260d8add1e055be3cabeb2955c7e1d03f6425361feb3` |
| Behavior prompt | `520e807e615db4f268222a73c6aeea98b0a689234291a25a4efff22f517f1869` |
| Verification prompt | `eff1bf1bc2a3fb9a4eb98ec5ca8807473d8f50325653977d18e87840de6d09e1` |
| Recall extraction code | `34ab29fcd3d0794682d728e00a5593b20775e34d9f5450291b0326e6d226a880` |
| Recall verification code | `b6c2bc56a4f691f6058590d2f7aa5029f3c97f007146df0a5491e722006f026d` |
| Dense M0/M1 code | `7520bb70621155139d2ab87e1d0bcb960e1a265dde11647100e22c5bc06c9058` |

동결 이후 필요한 버그 수정은 기존 파일을 조용히 덮어쓰지 않고, 변경 이유·영향 범위와 새
해시를 후속 보고서에 기록한다.
