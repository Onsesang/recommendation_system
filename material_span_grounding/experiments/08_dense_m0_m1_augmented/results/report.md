# 실험 08 — Sparse 학습 보조, dense-only 평가

기존 sparse 상품 436개를 fold별 학습 보조 데이터로 추가하고 89 dense 상품만 평가했다.
M1의 세 핵심 점추정치는 M0보다 높았지만 bootstrap 95% CI는 모두 0을 포함했다.
평가 텍스트 중심은 dense development 상품으로 고정해 실험 07과 M0 수치가 동일하다.

정확한 수치와 protocol은 같은 폴더의 `metrics.json`, 종합 해석은
`notion/08_M0_M1_SIMPLE_EXPERIMENTS.md`를 참고한다.
