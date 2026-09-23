# Review-Cold-Start 실험 Phase 3 — 촉감 축 구성 및 타당성

> 이 문서는 Notion에 그대로 옮길 수 있는 Markdown 결과 문서다.

## 축 구성 원칙

각 축은 두 극을 가진 ordinal axis이며 UNKNOWN은 축의 class가 아니다. Qwen은 symbolic axis/pole/intensity만 출력하고 숫자값은 config가 결정한다. 원문 exact span은 모든 레코드에 보존된다.

최종 active axes: `softness, surface_texture, elasticity, thickness`

## Softness (`softness`)

- 구성: `soft` ↔ `firm` bipolar ordinal axis
- 의미: Perceived yielding softness versus resistant firmness of the textile or garment material.
- 외부 검증 후보: leeds, mllm_fabric
- 관측 결과: span 499, 상품 164, 독립 reviewer 2명 이상 상품 102
- REVIEW_UNOBSERVED: 42.5%
- pole별 상품: {'soft': 154, 'firm': 23}
- category-target 의존도(eta²): 0.065
- 평균 Qwen mapping confidence: 0.978
- 결정: ACTIVE — 모든 사전 기준 충족

## Surface texture (`surface_texture`)

- 구성: `smooth` ↔ `rough` bipolar ordinal axis
- 의미: Smooth versus rough, scratchy, or coarse character of the textile surface.
- 외부 검증 후보: leeds, mllm_fabric
- 관측 결과: span 102, 상품 47, 독립 reviewer 2명 이상 상품 10
- REVIEW_UNOBSERVED: 83.5%
- pole별 상품: {'smooth': 21, 'rough': 31}
- category-target 의존도(eta²): 0.094
- 평균 Qwen mapping confidence: 0.952
- 결정: ACTIVE — 모든 사전 기준 충족

## Elasticity (`elasticity`)

- 구성: `non_elastic` ↔ `elastic` bipolar ordinal axis
- 의미: Resistance to stretch versus ability to stretch and recover as a material property.
- 외부 검증 후보: mllm_fabric
- 관측 결과: span 223, 상품 98, 독립 reviewer 2명 이상 상품 32
- REVIEW_UNOBSERVED: 65.6%
- pole별 상품: {'non_elastic': 45, 'elastic': 77}
- category-target 의존도(eta²): 0.132
- 평균 Qwen mapping confidence: 0.965
- 결정: ACTIVE — 모든 사전 기준 충족

## Thickness (`thickness`)

- 구성: `thin` ↔ `thick` bipolar ordinal axis
- 의미: Low versus high perceived textile thickness, including explicit thinness or thickness.
- 외부 검증 후보: mllm_fabric
- 관측 결과: span 549, 상품 184, 독립 reviewer 2명 이상 상품 102
- REVIEW_UNOBSERVED: 35.4%
- pole별 상품: {'thin': 146, 'thick': 68}
- category-target 의존도(eta²): 0.072
- 평균 Qwen mapping confidence: 0.971
- 결정: ACTIVE — 모든 사전 기준 충족

## Flexibility (`flexibility`)

- 구성: `flexible` ↔ `stiff` bipolar ordinal axis
- 의미: Ease of bending and draping versus stiffness or rigidity of the textile.
- 외부 검증 후보: leeds
- 관측 결과: span 70, 상품 31, 독립 reviewer 2명 이상 상품 6
- REVIEW_UNOBSERVED: 89.1%
- pole별 상품: {'flexible': 2, 'stiff': 30}
- category-target 의존도(eta²): 0.171
- 평균 Qwen mapping confidence: 0.964
- 결정: INACTIVE — 미충족 기준: both_poles, external_validation_available

## Warmth (`warmth`)

- 구성: `warm` ↔ `cool` bipolar ordinal axis
- 의미: Perceived thermal warmth versus coolness attributable to the textile.
- 외부 검증 후보: leeds
- 관측 결과: span 117, 상품 58, 독립 reviewer 2명 이상 상품 23
- REVIEW_UNOBSERVED: 79.6%
- pole별 상품: {'warm': 44, 'cool': 25}
- category-target 의존도(eta²): 0.080
- 평균 Qwen mapping confidence: 0.965
- 결정: INACTIVE — 미충족 기준: external_validation_available

## Sponginess (`sponginess`)

- 구성: `spongy` ↔ `crisp` bipolar ordinal axis
- 의미: Compressible spongy hand versus crisp, sharply structured textile hand.
- 외부 검증 후보: leeds
- 관측 결과: span 9, 상품 3, 독립 reviewer 2명 이상 상품 0
- REVIEW_UNOBSERVED: 98.9%
- pole별 상품: {'spongy': 0, 'crisp': 3}
- category-target 의존도(eta²): 0.250
- 평균 Qwen mapping confidence: 0.967
- 결정: INACTIVE — 미충족 기준: mapped_spans, unique_products, both_poles, multi_reviewer_products, external_validation_available

## 선택 결론

축 선택은 review coverage, pole balance, 독립 reviewer 지원, category 집중도를 모두 통과한 경우에만 이뤄졌다. 통계와 선택에는 모든 평가 seed에서 공통으로 train+development에 속한 family만 사용하며 어떤 seed의 test review도 사용하지 않았다. 이 결정은 물리적 촉감 진실성이 아니라 이후 이미지 feasibility 실험을 수행할 최소 데이터 조건을 뜻한다.
