# Material Recommendation API

상품별 리뷰 소재 target을 조회하고 기존 M0/M1 검색과 review-grounded tactile 기능을
제공하는 읽기 전용 backend다.
기존 사람 검수 backend(`audit_app`)와 별도 포트에서 실행된다.

## 실행

```bash
chmod +x recommendation_api/*.sh
./recommendation_api/start.sh
./recommendation_api/status.sh
./recommendation_api/stop.sh
```

기본 주소는 `http://127.0.0.1:8877`, API 문서는 `/docs`다. 원격 환경에서는 8877 포트를
로컬로 포워딩한다. 외부 인터페이스에 열어야 하면 다음처럼 설정한다.

통합 데모는 `http://127.0.0.1:8877/tactile-demo`에서 실행된다.

현재 워크스테이션에는 `material-recommendation.service` 사용자 systemd unit도 설치되어
있다. 기본 설정으로 `start.sh`를 실행하면 service가 enable되어 로그인 세션과 분리된 채
유지되고 실패 시 자동 재시작한다.

```bash
MATERIAL_API_HOST=0.0.0.0 MATERIAL_API_PORT=8877 ./recommendation_api/start.sh
```

## API

```text
GET  /api/health
GET  /api/stats
GET  /api/evaluation
GET  /api/evaluation/protocol
GET  /api/products?offset=0&limit=50&category=top&min_users=1
GET  /api/products/{asin}
GET  /api/search?asin={asin}&method=m1&k=10&same_category=true
POST /api/search
GET  /images/{asin}.jpg

GET  /v1/tactile/health
GET  /v1/tactile/evaluation
GET  /v1/multimodal/health
GET  /v1/multimodal/evaluation
GET  /v1/products?page=1&page_size=30
POST /v1/products/search
GET  /v1/products/{asin}/tactile
GET  /v1/products/{asin}/tactile-summary
GET  /v1/products/{asin}/tactile-concerns
GET  /v1/products/{asin}/related?limit=10
POST /v1/products/tactile-compare
POST /v1/recommendations/tactile-alternatives
POST /v1/recommendations/tactile-rerank
POST /v1/tactile/intent
POST /v1/tactile/agent
GET  /tactile-demo
```

### 상품 목록과 자연어 검색

첫 화면의 상품 목록은 한 페이지에 30개씩 반환한다. 원본 500레코드에서 제목이 같거나
이미지가 같고 제목·카테고리가 충분히 유사한 변형 상품을 하나의 상품군으로 묶어 현재
465개 고유 상품만 노출한다. 검색 결과와 관련 상품 목록에도 같은 중복 제거 규칙을 적용한다.

```http
GET /v1/products?page=1&page_size=30
```

응답에는 `total`, `page`, `page_size`, `total_pages`, `has_previous`, `has_next`와
이미지·제목을 포함한 `items`가 들어간다. 자연어 조건은 동일한 pagination 계약을
사용한다.

```http
POST /v1/products/search
Content-Type: application/json

{
  "query_text": "세탁 후 잘 늘어나지 않는 치마를 찾아줘.",
  "page": 1,
  "page_size": 30
}
```

위 문장은 `category=skirt`, `desired_less=stretchiness`로 구조화되며, 실제 상품의
제목·카테고리·tactile evidence 관련도 순으로 정렬된다. 응답에는 intent,
`relevance_score`, score breakdown, matched constraint와 근거가 포함된다.

### 상품 상세 관련 상품

```http
GET /v1/products/{asin}/related?limit=10
```

- `design_similar`: 같은 카테고리 안에서 465개 전 상품의 FashionCLIP 이미지 cosine을
  85%, 제목·스타일 token 유사도를 15% 반영한다.
- `tactile_similar`: 리뷰 target과 이미지에서 Ridge로 예측한 target을 근거량에 따라 결합한
  384차원 hybrid target cosine 85%와 target confidence 15%를 사용한다.

두 목록은 관련도 내림차순이며 현재 상품군은 제외한다. 각 결과는 `score_breakdown`을
포함하고 촉감 결과는 `review_image_blended` 또는 `image_predicted` 출처를 반환한다.
리뷰가 없는 상품의 촉감 설명은 추측하지 않으며, 이미지 예측 target은 추천에만 사용한다.

POST는 catalog ASIN 또는 외부 이미지 encoder가 만든 1152차원 Qwen feature를 받는다.

```json
{
  "asin": "B0010Z6RRY",
  "method": "m1",
  "k": 5,
  "same_category": true,
  "include_evidence": 3
}
```

`m0`는 원본 동결 Qwen 이미지 feature cosine 검색이다. `m1`은 Ridge가 이미지에서
예측한 소재 벡터와 실제 review target 사이 cosine 검색이다. 응답의 `score`는 확률이나
보정된 confidence가 아니다.

기존 M0/M1 catalog 438상품은 회귀 호환성을 위해 유지된다. Tactile v1은 별도 v2.1
catalog를 사용하며 원본 500상품 중 근거 있는 495상품에 384차원 target을 제공한다.
나머지 5상품은 내용을 추측하지 않고 `insufficient_evidence`를 반환한다. 일반 tactile
reranking은 기존 추천을 자동 대체하지 않으며 요청에서 strategy를 명시한다.

`/api/evaluation`은 최신 시간순 offline ranking 결과를, `/api/evaluation/protocol`은
split·negative sampling·cold-start cohort 정의와 입력 hash를 반환한다.
Tactile 전체 평가 결과는 `/v1/tactile/evaluation`과
`data/recommendation_eval/tactile_v1/report.md`에서 확인한다. 현재 tactile target은
time-aware가 아니고 test target coverage가 낮으므로 추천 비교 결과는 진단용이다.
이미지 cold-start 평가는 `/v1/multimodal/evaluation`에서 확인한다.
