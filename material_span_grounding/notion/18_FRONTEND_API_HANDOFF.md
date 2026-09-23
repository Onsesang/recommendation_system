# 프론트엔드 전달용 Backend API 명세

> 작성일: 2026-08-16  
> Backend: `material-recommendation.service`  
> 로컬 주소: `http://127.0.0.1:8877`  
> 데모: `http://127.0.0.1:8877/tactile-demo`  
> OpenAPI 요약: `http://127.0.0.1:8877/api/openapi.json`  
> 페이지별 Notion 데이터베이스 표: `notion/19_FRONTEND_API_PAGE_DATABASE.md`

## 1. 먼저 알아둘 내용

- 현재 API 인증은 없다.
- 모든 API 응답은 JSON이며 UTF-8이다.
- CORS 응답은 현재 `Access-Control-Allow-Origin: *`다.
- 상품 이미지는 API와 같은 host의 상대 경로로 내려온다.
- 운영 frontend에서는 base URL을 코드에 고정하지 말고 `API_BASE_URL` 환경변수로 관리한다.
- backend가 현재 `127.0.0.1`에 bind되어 있으므로 다른 서버·PC에서 접속할 경우 reverse
  proxy를 사용하거나 backend bind 설정을 별도로 변경해야 한다.
- `/api/*`는 기존 M0/M1 호환 API다. 새 frontend는 아래의 `/v1/*`를 우선 사용한다.
- score와 confidence는 보정된 확률이 아니다. backend가 반환한 순서를 그대로 사용한다.

같은 origin으로 배포한다면 상대 경로를 그대로 사용할 수 있다.

```ts
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "";

const absoluteUrl = (path: string) =>
  path.startsWith("http") ? path : `${API_BASE_URL}${path}`;
```

## 2. 권장 화면 호출 순서

### 첫 화면

```text
GET /v1/multimodal/health             선택: backend 상태 표시
GET /v1/products?page=1&page_size=30  필수: 첫 상품 목록
```

### 페이지 이동

```text
GET /v1/products?page={page}&page_size=30
```

### 자연어 검색

```text
POST /v1/products/search
```

### 상품 클릭

아래 네 요청은 서로 의존하지 않으므로 병렬 호출한다.

```text
GET /v1/products/{product_id}/tactile?include_claims=false
GET /v1/products/{product_id}/tactile-summary
GET /v1/products/{product_id}/tactile-concerns
GET /v1/products/{product_id}/related?limit=10
```

```ts
const [profile, summary, concerns, related] = await Promise.all([
  get(`/v1/products/${productId}/tactile?include_claims=false`),
  get(`/v1/products/${productId}/tactile-summary`),
  get(`/v1/products/${productId}/tactile-concerns`),
  get(`/v1/products/${productId}/related?limit=10`),
]);
```

### 필수 endpoint 빠른 확인

| 화면·기능 | Method | Endpoint |
|---|---|---|
| 전체 상품 30개씩 조회 | GET | `/v1/products?page={page}&page_size=30` |
| 자연어 상품 검색 | POST | `/v1/products/search` |
| 상품 촉감 profile | GET | `/v1/products/{product_id}/tactile?include_claims=false` |
| 구매자들이 말하는 소재 | GET | `/v1/products/{product_id}/tactile-summary` |
| 소재 관련 의견 | GET | `/v1/products/{product_id}/tactile-concerns` |
| 디자인·촉감 유사상품 | GET | `/v1/products/{product_id}/related?limit=10` |

위 표의 여섯 endpoint만 연결해도 현재 요구된 목록·검색·상세·유사상품 화면을 완성할 수
있다. 나머지 endpoint는 비교나 대화형 추천이 필요할 때 선택적으로 연결한다.

## 3. 공통 타입

```ts
type TactileStatus = "available" | "insufficient_evidence" | "image_predicted";
type TactileTargetSource = "review_image_blended" | "image_predicted";

interface ProductCard {
  product_id: string;
  title: string;
  category: string;
  image_url: string; // 예: /images/B000NRV95U.jpg
  tactile_status: TactileStatus;
  reviewer_count: number;
  claim_count: number;
  tactile_target_source: TactileTargetSource;
  review_weight: number;                 // 0~0.9
  image_weight: number;                  // 0.1~1
  image_prediction_confidence: number;   // 0~1, 보정 확률 아님
  tactile_target_confidence: number;     // 0~1, 보정 확률 아님
  rank: number;                          // 1-based
}

interface Page<T> {
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
  has_previous: boolean;
  has_next: boolean;
  items: T[];
  mode: "catalog" | "natural_language_search";
}

interface ApiError {
  error: {
    code: "invalid_request" | "not_found" | "feature_disabled" | string;
    message: string;
  };
}
```

### target 출처 표시 규칙

| API 값 | 권장 UI 문구 | 의미 |
|---|---|---|
| `review_image_blended` | 리뷰+이미지 촉감 | 실제 리뷰 target과 이미지 예측을 결합 |
| `image_predicted` | 이미지 기반 촉감 예상 | 리뷰 target 없이 이미지만으로 예측 |

중요:

- `tactile_status=insufficient_evidence`는 구매자 리뷰 근거가 없다는 뜻이다.
- 동시에 `tactile_target_source=image_predicted`일 수 있다.
- 이 경우 촉감 유사상품은 보여줄 수 있지만 **구매자들이 말하는 소재**와 **소재 관련
  의견**은 빈 상태로 표시해야 한다.
- 이미지 예측값을 구매자 의견처럼 표현하면 안 된다.

## 4. 전체 상품 목록

```http
GET /v1/products?page=1&page_size=30
```

- `page`: 1부터 시작한다.
- `page_size`: 기본 30, 최대 100이다.
- 현재 고유 상품은 465개이며 30개씩 총 16페이지다.
- 동일 상품 변형은 backend에서 이미 제거된다.

응답 축약 예시:

```json
{
  "total": 465,
  "page": 1,
  "page_size": 30,
  "total_pages": 16,
  "has_previous": false,
  "has_next": true,
  "mode": "catalog",
  "items": [
    {
      "product_id": "B000NRV95U",
      "title": "Leegoal Radiant Pleated Turban Sun Cap Hat Purple",
      "category": "accessory",
      "image_url": "/images/B000NRV95U.jpg",
      "tactile_status": "available",
      "reviewer_count": 2,
      "claim_count": 2,
      "tactile_target_source": "review_image_blended",
      "review_weight": 0.3766,
      "image_weight": 0.6234,
      "image_prediction_confidence": 0.6562,
      "tactile_target_confidence": 0.5667,
      "rank": 1
    }
  ]
}
```

이미지 렌더링:

```tsx
<img src={absoluteUrl(product.image_url)} alt={product.title} loading="lazy" />
```

## 5. 자연어 상품 검색

```http
POST /v1/products/search
Content-Type: application/json
```

```json
{
  "query_text": "세탁 후 잘 늘어나지 않는 치마를 찾아줘.",
  "page": 1,
  "page_size": 30
}
```

응답은 `Page<ProductSearchCard>`이며 다음 필드가 추가된다.

```ts
interface SearchIntent {
  current_product_id: string | null;
  category: string | null;
  query_text: string;
  desired_more: string[];
  desired_less: string[];
  avoid: string[];
  must_have: string[];
  source: string;
  confidence: number;
}

interface ProductSearchCard extends ProductCard {
  relevance_score: number;
  score_breakdown: Record<string, number>;
  matched_tactile_constraints: string[];
  matched_evidence: ReviewEvidence[];
}

interface SearchPage extends Page<ProductSearchCard> {
  query_text: string;
  intent: SearchIntent;
  message: string;
}
```

예시 문장은 다음처럼 해석된다.

```json
{
  "category": "skirt",
  "desired_less": ["stretchiness"]
}
```

주의:

- `matched_tactile_constraints`가 빈 배열이어도 검색 결과일 수 있다.
- 이미지 예측은 구매자 evidence를 만들지 않으므로 `matched_evidence`가 없을 수 있다.
- frontend에서 재정렬하지 않는다.
- 검색 중 페이지 이동도 같은 POST에 `page`만 변경하여 호출한다.

## 6. 상품 기본 촉감 profile

```http
GET /v1/products/{product_id}/tactile?include_claims=false
```

```ts
interface TactileProfile {
  product_id: string;
  title: string;
  category: string;
  representative_claims: unknown[];
  embedding_ref: number | null;
  reviewer_count: number;
  review_count: number;
  claim_count: number;
  evidence_strength: number;
  source_breakdown: Record<string, number>;
  status: "available" | "insufficient_evidence";
}
```

- 현재 상세 화면에는 `include_claims=false`를 권장한다.
- 실제 claim 전체가 필요할 때만 `include_claims=true`를 사용한다.
- 상세 화면의 target 출처·가중치는 이 API가 아니라 `/related`의 `anchor_target`에서 읽는다.

## 7. 구매자들이 말하는 소재

```http
GET /v1/products/{product_id}/tactile-summary
```

```ts
interface ReviewEvidence {
  claim_id: string;
  review_id: string;
  original_span: string;
  direction?: "present" | "absent";
  sentiment: "positive" | "neutral" | "negative";
  confidence: number;
  source: string;
  human_verified: boolean;
  verified_purchase: boolean | null;
}

interface TactileSummaryItem {
  concept: string;
  label: string;
  display_label: string;
  display_text: string;
  reviewer_count: number;
  confidence: number;
  agreement_ratio: number;
  contradictory: boolean;
  sentiment_distribution: Record<string, number>;
  direction_distribution: Record<string, number>;
  source_breakdown: Record<string, number>;
  representative_evidence: string[];
  evidence_details: ReviewEvidence[];
}

interface TactileSummaryResponse {
  product_id: string;
  title: string;
  status: "available" | "insufficient_evidence";
  summary: TactileSummaryItem[];
  reviewer_count: number;
  review_count: number;
  claim_count: number;
  source_breakdown: Record<string, number>;
  message: string;
}
```

`evidence_details[].original_span`만 실제 리뷰 인용문으로 표시한다. `review_id`는 내부 추적
키이며 사용자에게 반드시 노출할 필요는 없다. raw reviewer ID는 API에 포함되지 않는다.

빈 상태 예시:

```json
{
  "status": "insufficient_evidence",
  "summary": [],
  "reviewer_count": 0,
  "review_count": 0,
  "claim_count": 0,
  "message": "구매자 리뷰에서 촉감·소재 관련 근거를 찾지 못했습니다."
}
```

## 8. 소재 관련 의견

```http
GET /v1/products/{product_id}/tactile-concerns
```

```ts
interface TactileConcern {
  property: string;
  label: string;
  category: string;
  severity: "low" | "medium" | "high" | string;
  reviewer_count: number;
  total_reviewer_count: number;
  negative_ratio: number;
  confidence: number;
  agreement: number;
  concern_score: number;
  evidence: ReviewEvidence[];
  alternative_action: null | {
    type: "tactile_alternatives";
    current_product_id: string;
    tactile_concept: string;
    desired_direction: "less" | "more";
  };
  alternative_unavailable_reason: string | null;
}
```

응답 `status`:

- `available`: 표시할 반복 부정 의견이 있음
- `no_qualifying_concerns`: 리뷰는 있지만 기준을 만족한 우려 없음
- `insufficient_evidence`: 소재 관련 리뷰 근거 부족

`concerns=[]`는 오류가 아니므로 빈 상태 UI를 표시한다.

## 9. 디자인·촉감 유사상품

```http
GET /v1/products/{product_id}/related?limit=10
```

- `limit`: 1~30
- 같은 카테고리 안에서 검색한다.
- 현재 상품과 같은 상품군은 backend가 제외한다.
- 두 배열은 서로 다른 점수 체계이므로 서로 점수를 비교하지 않는다.

```ts
interface TargetInfo {
  tactile_target_source: TactileTargetSource;
  review_weight: number;
  image_weight: number;
  image_prediction_confidence: number;
  tactile_target_confidence: number;
}

interface DesignRelated extends ProductCard {
  relevance_score: number;
  title_style_similarity: number;
  visual_similarity: number;
  method: "same_category_fashionclip_image_plus_title";
  score_breakdown: {
    image_similarity_01: number;
    title_style_similarity: number;
    weighted_image: number;
    weighted_title: number;
    final_score: number;
  };
}

interface TactileRelated extends ProductCard {
  relevance_score: number;
  tactile_cosine: number;
  evidence_strength: number;
  target_source: TactileTargetSource;
  method: "same_category_hybrid_tactile_cosine";
  score_breakdown: {
    tactile_similarity_01: number;
    target_confidence: number;
    weighted_tactile: number;
    weighted_confidence: number;
    final_score: number;
  };
}

interface RelatedResponse {
  product_id: string;
  category: string;
  anchor_target: TargetInfo;
  design_similar: DesignRelated[];
  tactile_similar: TactileRelated[];
  design_method_note: string;
  tactile_method_note: string;
}
```

현재 점수식:

```text
design = 0.85 × FashionCLIP image similarity01
       + 0.15 × title/style similarity

tactile = 0.85 × hybrid tactile similarity01
        + 0.15 × target confidence
```

권장 표시:

- 디자인 카드: `FashionCLIP 이미지`
- 촉감 카드: `리뷰+이미지` 또는 `이미지 기반 예상`
- 상세 상단: `리뷰 38% · 이미지 62% · confidence 0.57` 형태
- `design_method_note`, `tactile_method_note`는 도움말 문구로 사용할 수 있다.

## 10. 촉감 대안 상품

소재 우려 카드의 `alternative_action`이 있을 때만 호출한다.

```http
POST /v1/recommendations/tactile-alternatives
Content-Type: application/json
```

```json
{
  "anchor_product_id": "B00EBNKMKU",
  "direction": "less",
  "tactile_concept": "thinness",
  "top_k": 10
}
```

응답의 `results`는 `rank`, `final_score`, `score_breakdown`, `reason.evidence`를 포함한다.
`results=[]`이면 `message`를 빈 상태로 표시한다.

## 11. 상품 촉감 비교 — 선택 기능

```http
POST /v1/products/tactile-compare
Content-Type: application/json
```

```json
{
  "product_ids": ["B000NRV95U", "B006NO99DQ"]
}
```

- 2~20개 상품을 받는다.
- `groups.common`, `groups.different`, `groups.one_sided`, `groups.conflicting`으로 구분된다.
- `dimensions[].products[product_id].evidence`에 실제 리뷰 근거가 있다.
- 근거가 없는 속성은 `insufficient_evidence`이며 중간값을 추측하지 않는다.

## 12. 자연어 Intent·Agent — 선택 기능

의도만 먼저 확인하려면:

```http
POST /v1/tactile/intent
```

```json
{
  "query_text": "부드럽고 비치지 않는 바지를 찾아줘"
}
```

Agent가 추천까지 수행하게 하려면:

```http
POST /v1/tactile/agent
```

```json
{
  "message": "부드럽고 비치지 않는 바지를 찾아줘",
  "top_k": 10
}
```

현재 메인 카탈로그 화면에는 pagination과 멀티모달 상품 필드가 포함된
`POST /v1/products/search` 사용을 권장한다. Agent는 대화형 후속 intent가 필요할 때만
사용한다.

## 13. 상태 확인·평가 API

```text
GET /v1/tactile/health
GET /v1/tactile/evaluation
GET /v1/multimodal/health
GET /v1/multimodal/evaluation
```

`/v1/multimodal/health` 현재 핵심 값:

```json
{
  "status": "ok",
  "catalog_products": 465,
  "design_embedding": {
    "model": "patrickjohncyh/fashion-clip",
    "dimension": 512,
    "coverage": 1.0
  },
  "tactile_target": {
    "model": "ridge",
    "dimension": 384,
    "source_counts": {
      "image_predicted": 4,
      "review_image_blended": 461
    }
  }
}
```

일반 사용자 화면에서 evaluation API를 호출할 필요는 없다. 관리자·개발 화면에서만 사용한다.

## 14. 공통 fetch 예시

```ts
async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, init);
  const payload = await response.json();

  if (!response.ok) {
    const apiError = payload as ApiError;
    throw new Error(apiError.error?.message ?? `HTTP ${response.status}`);
  }
  return payload as T;
}

const get = <T>(path: string) => request<T>(path);

const post = <T>(path: string, body: unknown) =>
  request<T>(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
```

## 15. 오류와 빈 상태 처리

오류 응답 형식:

```json
{
  "error": {
    "code": "invalid_request",
    "message": "page must be positive"
  }
}
```

| HTTP | 처리 |
|---:|---|
| 200 | 정상. 배열이 비어 있을 수 있음 |
| 400 | 입력값 오류. `error.message` 표시 |
| 404 | 상품·route 없음 또는 비활성 기능 |
| 500 | 서버 오류. 재시도 안내 |

frontend에서 반드시 구분할 상태:

1. HTTP 오류
2. HTTP 200 + `insufficient_evidence`
3. HTTP 200 + 빈 배열
4. HTTP 200 + `image_predicted`

2~4는 오류가 아니다.

## 16. 구현 체크리스트

- [ ] API base URL 환경변수 적용
- [ ] 이미지 상대 URL에 API base URL 결합
- [ ] 첫 화면 30개 및 server-side pagination
- [ ] 검색 결과도 POST 기반 pagination 유지
- [ ] 상품 상세 네 API 병렬 호출
- [ ] `review_image_blended` / `image_predicted` badge 구분
- [ ] 이미지 예측을 구매자 의견으로 표현하지 않음
- [ ] `insufficient_evidence`와 네트워크 오류를 다르게 표시
- [ ] `original_span`만 실제 리뷰 인용문으로 사용
- [ ] 디자인·촉감 결과를 backend 순서 그대로 표시
- [ ] 동일 상품 중복 제거를 frontend에서 다시 수행하지 않음
- [ ] 모바일에서 유사상품 가로 스크롤 또는 responsive grid 처리

## 17. 참고 구현

현재 동작하는 vanilla frontend 구현:

- `recommendation_api/static/index.html`
- `recommendation_api/static/app.js`
- `recommendation_api/static/app.css`

Backend 계약 및 평가:

- `recommendation_api/README.md`
- `docs/tactile/DATA_CONTRACTS.md`
- `notion/17_MULTIMODAL_DESIGN_TACTILE_COLDSTART.md`

현재 backend 전체 회귀 테스트는 103/103 통과 상태다.
