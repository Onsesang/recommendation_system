# Review-Cold-Start Tactile Retrieval — Phase 0~11 실행 문서

## 실행 결론

이 문서는 buyer review의 선택적·주관적 tactile evidence를 구조화한 뒤, review가 없는 상품 이미지에 선택적으로 전이하는 feasibility 실험의 전체 기록이다. REVIEW_UNOBSERVED, reviewer disagreement, VISUAL_ABSTAIN은 서로 다른 상태로 유지했다.

## Phase 3 축 구성과 실제 관측 결과

축은 아래의 두 pole을 가진 bipolar ordinal 구조다. Qwen은 pole과 강도만 기호로 출력하고 수치는 설정의 결정론적 변환과 reviewer-first aggregation 뒤에 생성된다. 축은 문헌만 보고 고정하지 않고 Phase 3의 span/product/pole/reviewer/category 기준을 모두 통과한 경우에만 active로 선택했다.

### Softness (`softness`)

- 축: `soft` ↔ `firm`
- 의미: Perceived yielding softness versus resistant firmness of the textile or garment material.
- 결과: mapped span 499, product 164, ≥2 reviewers product 102, REVIEW_UNOBSERVED 42.5%
- pole별 product: `{'soft': 154, 'firm': 23}`
- category 집중도: 25.5%
- 선택: **ACTIVE** (모든 정량 기준 통과)

### Surface texture (`surface_texture`)

- 축: `smooth` ↔ `rough`
- 의미: Smooth versus rough, scratchy, or coarse character of the textile surface.
- 결과: mapped span 102, product 47, ≥2 reviewers product 10, REVIEW_UNOBSERVED 83.5%
- pole별 product: `{'smooth': 21, 'rough': 31}`
- category 집중도: 29.4%
- 선택: **ACTIVE** (모든 정량 기준 통과)

### Elasticity (`elasticity`)

- 축: `non_elastic` ↔ `elastic`
- 의미: Resistance to stretch versus ability to stretch and recover as a material property.
- 결과: mapped span 223, product 98, ≥2 reviewers product 32, REVIEW_UNOBSERVED 65.6%
- pole별 product: `{'non_elastic': 45, 'elastic': 77}`
- category 집중도: 30.9%
- 선택: **ACTIVE** (모든 정량 기준 통과)

### Thickness (`thickness`)

- 축: `thin` ↔ `thick`
- 의미: Low versus high perceived textile thickness, including explicit thinness or thickness.
- 결과: mapped span 549, product 184, ≥2 reviewers product 102, REVIEW_UNOBSERVED 35.4%
- pole별 product: `{'thin': 146, 'thick': 68}`
- category 집중도: 26.0%
- 선택: **ACTIVE** (모든 정량 기준 통과)

### Flexibility (`flexibility`)

- 축: `flexible` ↔ `stiff`
- 의미: Ease of bending and draping versus stiffness or rigidity of the textile.
- 결과: mapped span 70, product 31, ≥2 reviewers product 6, REVIEW_UNOBSERVED 89.1%
- pole별 product: `{'flexible': 2, 'stiff': 30}`
- category 집중도: 31.4%
- 선택: **INACTIVE** (미통과: both_poles, external_validation_available)

### Warmth (`warmth`)

- 축: `warm` ↔ `cool`
- 의미: Perceived thermal warmth versus coolness attributable to the textile.
- 결과: mapped span 117, product 58, ≥2 reviewers product 23, REVIEW_UNOBSERVED 79.6%
- pole별 product: `{'warm': 44, 'cool': 25}`
- category 집중도: 29.9%
- 선택: **INACTIVE** (미통과: external_validation_available)

### Sponginess (`sponginess`)

- 축: `spongy` ↔ `crisp`
- 의미: Compressible spongy hand versus crisp, sharply structured textile hand.
- 결과: mapped span 9, product 3, ≥2 reviewers product 0, REVIEW_UNOBSERVED 98.9%
- pole별 product: `{'spongy': 0, 'crisp': 3}`
- category 집중도: 88.9%
- 선택: **INACTIVE** (미통과: mapped_spans, unique_products, both_poles, multi_reviewer_products, external_validation_available)

## Phase별 수행 내용

- **Phase 0:** 저장소·schema·Qwen checkpoint·embedding·family split을 감사하고 누수 경계를 동결
- **Phase 1:** 7개 후보 축과 ordinal coding을 YAML로 선언하고 source code의 축별 분기를 제거
- **Phase 2:** 기존 Qwen3-VL-8B-Instruct로 4,527 accepted span을 단일 taxonomy prompt에 grounding
- **Phase 3:** coverage/MNAR/extreme/category/reviewer diagnostics 후 active axis 자동 선택
- **Phase 4:** 600개 stratified human audit sheet 생성; 사람 label은 비워 두고 미완료를 명시
- **Phase 5:** reviewer-first product target, 분포·support·agreement·mask 생성
- **Phase 6:** category/FashionCLIP/image+category/MLP/open-vector baseline 평가
- **Phase 7:** masked regression·ordinal·pairwise 및 W0~W3/강도·support robustness 비교
- **Phase 8:** MLLM-Fabric 220 RGB 외부 전이 평가; Leeds 접근 불가를 그대로 보고
- **Phase 9:** bootstrap instance uncertainty와 external property recoverability를 분리해 risk-coverage calibration
- **Phase 10:** hidden test-review relevance로 same-category cold-start retrieval과 UNKNOWN 정책 평가
- **Phase 11:** seed 평균·bootstrap CI·가설 기각 기준·재현 manifest·전체 테스트를 통합

## 가설 판정

- **H1 — falsified**: structured FashionCLIP Ridge beats category-only on mean axis Spearman and current-split open-vector on retrieval NDCG@10. Evidence: `{"structured_axis_mean": 0.060825669218267694, "category_axis_mean": 0.08590558274244667, "structured_ndcg@10": 0.7298292193668611, "open_vector_ndcg@10": 0.7660250671961953}`
- **H2 — supported**: mean compatible external pairwise accuracy exceeds random 0.5. Evidence: `{"external_pairwise_mean": 0.5132343093930841, "axes": 4}`
- **H3 — supported**: generic recoverability+confidence calibrator has lower AURC than confidence-only. Evidence: `{"confidence_only_aurc": 0.8086023085120609, "learned_calibrator_aurc": 0.6714998145118738}`
- **H4 — supported**: validation-calibrated selective predictor reduces test MAE risk at nominal 80% coverage versus 100%. Evidence: `{"full_risk": 0.836233913898468, "selective_risk": 0.732701301574707, "actual_coverage": 0.816}`
- **H5 — supported**: UNKNOWN-aware proposed ranking beats forced structured prediction on cold-start NDCG@10. Evidence: `{"forced_structured_ndcg@10": 0.7298292193668611, "proposed_ndcg@10": 0.7486523584406508}`

## 해석 제한

- The current Amazon family splits are feasibility splits and not a never-inspected final test set.
- Human-audit rows were exported, but human annotation was not fabricated; pseudo-label quality metrics remain pending.
- Leeds raw image-plus-rating access/licensing was not verified, so Leeds was reported unavailable.
- Qwen VLM zero-shot uses symbolic image-only axis scores with explicit abstention; it is not a direct prompt-to-ranked-list evaluator.
- Held-out reviews are subjective selective evidence, never described as physical tactile ground truth.
