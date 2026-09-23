# 실험 05 — Product-dense 데이터 준비

- 전체 리뷰 2,500,939개를 공식 train split과 로컬 이미지 조건으로 스캔했다.
- 고유 사용자 5명 이상의 상품은 8,498개였다.
- 확장용으로 500상품·4,158리뷰, 단순 실험용으로 100상품×5사용자·500리뷰를 만들었다.
- 모든 표본은 사용자당 리뷰 1개이며 protected test는 사용하지 않았다.

상세 수치는 `data/dense/density_manifest.json`과
`data/dense/simple_100x5/density_manifest.json`을 참고한다.
