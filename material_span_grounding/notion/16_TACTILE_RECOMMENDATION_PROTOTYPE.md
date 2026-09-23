# Tactile-aware Fashion Recommendation Prototype 완료

> 완료일: 2026-08-13  
> Demo: `http://127.0.0.1:8877/tactile-demo`  
> 이번 작업에서 기존 M0/M1 재평가는 실행하지 않음

## 구현 완료 기능

1. 공통 Tactile Backend: 500상품, 495 profile, 5 explicit empty state
2. 구매자 리뷰 기반 소재·촉감 설명과 exact evidence
3. 일반 추천용 baseline/global/category/context-gated reranking
4. 실제 catalog만 사용하는 자연어 Agent 추천
5. 같은 category 안의 방향성 tactile alternative
6. 2개 이상 상품의 tactile comparison
7. 서로 다른 reviewer의 반복적인 negative concern detection
8. 통합 API, 반응형 demo UI, feature flags, score breakdown
9. 시간순 추천 ablation과 기능별 정량 검증
10. 원본 500레코드를 465개 고유 상품으로 중복 제거한 카탈로그(페이지당 30개), 상시
    자연어 검색, 상품 상세와 디자인/촉감 유사상품

## 최종 검증

- 테스트: 103/103 통과
- 로컬 systemd 서비스: active
- live E2E: catalog pagination, 자연어 검색, 상품 상세, design/tactile related, 기존 소재 섹션, demo 통과
- 원본 review/span/raw dataset 수정 없음
- 공개 응답에 raw reviewer ID 없음
- request-time LLM 없음

## 정량 결과

| 전략 | Recall@5 | NDCG@5 | Recall@10 | NDCG@10 |
|---|---:|---:|---:|---:|
| No tactile | 0.0060 | 0.0043 | 0.0120 | 0.0062 |
| Global tactile | 0.0060 | 0.0043 | 0.0120 | 0.0062 |
| Category-conditioned | 0.0060 | 0.0043 | 0.0120 | 0.0062 |
| Context-gated | 0.0060 | 0.0043 | 0.0120 | 0.0062 |

ranking 개선은 관찰되지 않았다. 현재 332개 평가 case 중 tactile history가 있는 case는
46개, test target까지 있는 case는 5개뿐이고 후보 tactile coverage는 3.25%다.
Context-gated는 explicit tactile query가 없는 interaction 평가에서 baseline과 동일하게
동작했으며, 이는 구매 이력만으로 강한 tactile preference를 만들지 않는 설계와 일치한다.

기능별 구조적 검증:

- Description: 500상품 중 495상품(99%), 표시 evidence 3,859개 exact support 100%
- Concern: 42상품 48건, exact support 100%; 독립 human precision label은 없음
- Comparison: 50 pair, 679 dimension, exact support 100%, unsupported value 0%
- Alternative: 지원 47 task 중 38 task 결과 존재, 175결과; 방향·category·evidence 100%
  - 같은 signal로 확인한 self-consistency 수치이며 human relevance precision이 아님
- Agent: intent fixture 5/5, catalog consistency 100%, invented product 0%

## 해석 제한

현재 target은 전체 선택 리뷰를 집계했으므로 time-aware가 아니다. 추천 성능 결과는
프로토타입 진단용이며 leakage-free 연구 결과가 아니다. 또한 Qwen v2.1 결과는 Codex AI
개발 검수 규칙의 영향을 받은 pseudo-label이며 독립 human gold가 아니다.

다음 우선순위는 UI 기능 추가보다 **time-aware tactile coverage 확대**와 independent human
evaluation 구축이다.

## 카탈로그 중심 UI/API 추가

- `GET /v1/products?page=1&page_size=30`: 이미지와 제목을 포함한 전체 상품 목록
- 제목이 같거나 동일 이미지·유사 제목인 변형 상품은 한 번만 노출하며, 검색·유사상품에도
  동일 규칙 적용(500 source records → 465 visible products, 16 pages)
- `POST /v1/products/search`: 자연어 의도 해석 후 관련도순 목록과 동일한 pagination 반환
- `GET /v1/products/{product_id}/related`: 디자인 유사상품과 촉감 유사상품을 별도 순위로 반환
- 상세 화면에서 **구매자들이 말하는 소재**와 **소재 관련 의견**을 그대로 유지
- 디자인 유사도는 465개 전 상품의 FashionCLIP 이미지 cosine 85%와 title/style 15%를
  사용한다. 촉감 유사도는 review target과 이미지 예측 target을 근거량에 따라 결합하며,
  UI에서 `리뷰+이미지`와 `이미지 기반 예상`을 구분한다.

상세 설계·계약·최종 보고서는 `docs/tactile/`에, 평가 산출물은
`data/recommendation_eval/tactile_v1/`에 있다.
