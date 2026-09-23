# v3 Tactile Human Audit Protocol

## 1. 목적

이 단일-reviewer audit은 (1) Qwen3-VL-32B-Instruct가 review span에서 만든 tactile pseudo-label의 타당성, (2) 각 tactile property의 단일 상품 이미지 관측 가능성, (3) 고정된 FashionCLIP Last2 예측과 사람의 image-based 판단 간 일치도를 평가한다. 모델 학습·target 생성 실험이 아니다.

## 2. 왜 Human Audit이 필요한가

v3의 locked-test target은 사람이 확정한 image ground truth가 아니라 review text를 Qwen이 해석해 집계한 pseudo-label이다. 따라서 기존 test metric만으로는 Qwen의 언어 해석 오류, review와 이미지 간 정보 차이, category shortcut, 실제 이미지 촉감 신호를 분리할 수 없다. 이 audit은 그 세 요인을 구분하기 위한 후속 검증이다.

## 3. Sampling strategy

- 대상은 기존 family-disjoint split의 locked test이며 `observed mask = 1`인 product-class만 사용한다.
- primary class는 `smooth`, `rough`, `thin`, `thick`, `flexible`, `stiff`, `warm`, `cool`이다. 나머지 6개 class는 supplementary/diagnostic으로만 유지한다.
- seed `20260904`로 class당 20개, 기존 binary rule 기준 positive 10개와 negative 10개를 선택한다(총 160개).
- 정렬 기준에는 target stratum, fractional 여부, category 사용 횟수, family/ASIN 반복 횟수와 seeded hash만 들어간다. Last2 probability·prediction·성공/실패 여부는 표본 identity가 고정된 뒤에만 결합한다.
- category 다양성을 우선하고 ASIN의 전체 사용 횟수는 최대 2회로 제한한다. 동일 family 반복도 최소화한다.
- 실제 manifest는 160개, 154개 unique ASIN, 151개 unique family이며 모든 class가 10/10 균형이다.

## 4. Blind-first design

각 항목의 최초 화면에는 상품 이미지, 평가 class, 짧은 정의, 전체 및 class별 진행률만 보인다. category, review/span, Qwen 출력, raw/binary target, Last2 probability, threshold와 prediction은 blind image judgment가 CSV에 저장된 뒤에만 expander로 공개된다. 저장 후 공개 정보로 최초 판단을 수정할 수는 있지만, 수정 기록은 같은 `item_id` 행을 갱신한다.

## 5. Tactile class definitions

| Class | 중립적 정의 |
|---|---|
| smooth | 표면이 매끄럽고 거친 요철이 적어 보이는 특성 |
| rough | 표면이 거칠고 질감이나 요철이 뚜렷해 보이는 특성 |
| thin | 소재 두께가 얇고 가벼워 보이는 특성 |
| thick | 소재가 두껍고 볼륨감이나 두께가 있어 보이는 특성 |
| flexible | 소재가 쉽게 휘고 흐르거나 유연해 보이는 특성 |
| stiff | 소재가 형태를 유지하고 뻣뻣해 보이는 특성 |
| warm | 소재가 보온성이 높고 따뜻할 것으로 보이는 특성 |
| cool | 소재가 시원하고 가볍거나 통기성이 있을 것으로 보이는 특성 |

## 6. Annotation questions

한 항목마다 다음을 저장한다.

1. 이미지 관측 가능성: `yes`, `partial`, `no`
2. image-based tactile label: `present`, `absent`, `uncertain`
3. confidence: 1(거의 확신 없음)–5(매우 높음)
4. optional note

사람이 UI에서 저장하기 전까지 모든 human annotation field는 비어 있다.

## 7. Image observability

class별 `Yes`, `Partial`, `No` 수를 집계한다. Strict observability는 `Yes / completed`, inclusive observability는 `(Yes + Partial) / completed`다. missing image는 별도 집계하고 모델-사람 평가에서 제외한다.

## 8. Qwen/review audit

blind image 판단을 저장한 뒤 원 review/span과 Qwen class·polarity·confidence를 공개한다. reviewer는 review evidence를 `present_evidence`, `absent_or_opposite_evidence`, `ambiguous`, `not_tactile_irrelevant`, `insufficient_context` 중 하나로 선택하고 confidence 1–5를 선택할 수 있다. 앞의 두 명확한 label만 Qwen binary 비교에 포함하고 나머지는 제외 사유별로 보고한다. 사용되는 Qwen 결과는 기존 v3의 `Qwen/Qwen3-VL-32B-Instruct` NF4 4-bit grounding 산출물이며 재실행하지 않는다.

## 9. Last2-human evaluation

primary 분석은 image missing이 아니며 observability가 `yes`, human label이 `present/absent`인 항목만 사용한다. Last2 probability의 AUROC와 Average Precision, 기존 development threshold로 만든 prediction의 accuracy·precision·recall·F1을 전체 및 class별 support와 함께 계산한다. `yes` 또는 `partial`을 포함한 결과는 sensitivity 분석으로 분리한다.

## 10. Threshold leakage 방지

Human Audit label로 threshold를 선택·보정·재튜닝하지 않는다. manifest에 저장된 threshold는 기존 v3 development split에서 선택된 값을 experiment 14의 고정 prediction artifact에서 읽은 것이다. locked-test human label은 평가에만 사용한다.

## 11. Fractional target 처리

기존 v3 evaluation과 동일하게 `binary_target = int(raw_target >= 0.5)`를 사용한다. manifest에는 `raw_target`, `binary_target`, `is_fractional_target`을 모두 보존한다. 각 binary stratum에서 exact 0/1 target을 우선 선택하고 support가 부족할 때만 fractional target을 결정론적으로 fallback한다. 현재 160개 표본은 모두 exact target이어서 fractional 표본은 0개다.

## 12. 분석 metric

- observability: count, strict rate, inclusive rate
- Last2 vs Human: AUROC, Average Precision, accuracy, precision, recall, F1
- pseudo-label vs Human image label: agreement/accuracy, precision, recall, F1
- Qwen vs Human review evidence: agreement/accuracy, precision, recall, F1
- qualitative grouping: clean success, clean negative, false negative, false positive

AUROC/AP는 명확한 human class가 둘 다 존재할 때만 계산한다. support가 0이거나 한 class뿐이면 해당 값은 `null`이며 오류를 내지 않는다.

## 13. Limitations

- reviewer가 한 명이므로 inter-rater agreement나 사람 간 변이를 추정할 수 없다.
- 단일 상품 이미지는 실제 촉감, 두께, 보온성 등을 완전히 보여주지 못할 수 있다.
- review-derived target과 image judgment는 서로 다른 evidence modality를 측정한다. 둘의 불일치는 어느 한쪽의 오류라고 자동 해석할 수 없다.
- class별 20개는 정밀한 subgroup 추정을 위한 큰 표본이 아니다.
- 저장 후 reference를 본 다음 기존 답변을 수정하면 post-reveal bias가 생길 수 있으므로, 원칙적으로 blind 답변은 유지한다.

## 14. Streamlit 실행 방법

```bash
cd /home/user/onsesang/material_span_grounding
/home/user/onsesang/miniconda3/envs/texture/bin/streamlit run experiments/15_human_audit/app.py
```

브라우저에 표시되는 로컬 주소를 열어 검수한다. 외부 배포, 로그인, DB는 사용하지 않는다.

## 15. Annotation 저장 위치

CSV는 `experiments/15_human_audit/annotations/human_audit.csv`에 즉시 원자적으로 저장된다. `item_id`가 unique key이며 기존 항목 수정 시 행을 append하지 않고 update한다. `first_saved_timestamp`는 유지되고 `last_updated_timestamp`만 갱신된다. 앱 재시작 시 CSV를 읽어 완료 상태를 복구한다.

현재 파일은 header만 있으며 실제 human annotation은 아직 0/160이다.

## 16. Analysis 실행 방법

```bash
cd /home/user/onsesang/material_span_grounding
/home/user/onsesang/miniconda3/envs/texture/bin/python experiments/15_human_audit/analyze_human_audit.py
```

출력은 `experiments/15_human_audit/artifacts/human_audit_results.json`에 기록된다. 미완료 상태에서도 완료된 행만 분석하며, 0개이면 `status: not_started`와 `null` metric을 안전하게 기록한다.
