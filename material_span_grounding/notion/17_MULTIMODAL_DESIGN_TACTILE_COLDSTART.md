# FashionCLIP 디자인 검색과 촉감 Cold-start 적용 결과

> 완료일: 2026-08-13  
> 범위: 전체 이미지 디자인 검색, image→tactile 예측, hybrid target, API/UI 적용

## 산출물

- 원본 500레코드 → 465개 고유 상품군, 이미지 누락 0
- `patrickjohncyh/fashion-clip` revision `7e3ba62ce16b...`
- 전 상품 512차원 L2-normalized 이미지 임베딩
- 리뷰 target 보유 상품군 461개: train 321 / dev 70 / locked test 70
- 선택 모델: FashionCLIP 512차원 + category one-hot → multi-output Ridge → 촉감 384차원
- hybrid target 465개: `review_image_blended` 461, `image_predicted` 4

## Cold-start 평가

| 방법 | Centered cosine | Same-category Recall@5 | NDCG@5 |
|---|---:|---:|---:|
| Category-only | 0.0998 | 0.1400 | 0.7367 |
| Raw FashionCLIP image | - | 0.2171 | 0.7762 |
| MLP | 0.1323 | 0.2371 | 0.7990 |
| **Ridge** | **0.2006** | **0.2657** | **0.8093** |

Ridge는 dev cosine으로 선택한 뒤 잠근 test에서 한 번 평가했으며 category-only와 raw image
retrieval을 모두 넘었다. BGE target의 강한 공통 평균 방향 때문에 원본 cosine만 주장하지
않고 train 평균을 제거한 centered cosine을 함께 보고한다.

## 런타임 점수

```text
design_score = 0.85 × FashionCLIP image cosine01
             + 0.15 × title/style Jaccard

tactile_score = 0.85 × hybrid tactile cosine01
              + 0.15 × target confidence
```

리뷰가 있는 상품은 evidence strength에 따라 review target과 image prediction을 결합한다.
리뷰 target이 없으면 이미지 예측을 100% 사용하지만 UI와 API에 `image_predicted`로 표시한다.
이미지 예측은 추천 순위에만 사용하며 구매자 소재 설명·의견·exact evidence를 만들지 않는다.

## API/UI

- `GET /v1/multimodal/health`
- `GET /v1/multimodal/evaluation`
- `/v1/products/{id}/related`의 두 목록 모두 score breakdown 제공
- 디자인 카드: FashionCLIP 이미지 신호 표시
- 촉감 카드: target 출처와 confidence 표시
- 상세 화면: review/image weight 표시
- 기존 **구매자들이 말하는 소재**, **소재 관련 의견** 유지

## 제한

- test는 70개 상품군으로 작다.
- review target은 전체 선택 리뷰 집계이며 time-aware가 아니다.
- 상품 대표 이미지 한 장만 사용했다. 소재 확대·앞/뒤 이미지를 추가하면 별도 재평가가 필요하다.
- 사람의 디자인 유사성 라벨은 없어 현재 디자인 평가는 coverage/category/중복 등 구조 검증이다.

재현 스크립트와 모든 stage manifest는 `scripts/build_multimodal_catalog.py` 및
`data/derived/multimodal_catalog_v1/`에 있다.
