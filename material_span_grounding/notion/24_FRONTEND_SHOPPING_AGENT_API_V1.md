# 프론트엔드 전달용 개인화 쇼핑 에이전트 API v1

> 작성일: 2026-08-21  
> Base URL: `http://127.0.0.1:8878`  
> UI: `http://127.0.0.1:8878/agent-demo`  
> OpenAPI summary: `http://127.0.0.1:8878/agent/v1/openapi.json`

## 1. 기존 명세와 달라진 점

기존 `notion/18_FRONTEND_API_HANDOFF.md`의 `/v1/*` API는 그대로 유지된다. 새 frontend는
로그인, 대화 세션, 자동 취향, 행동 개인화, 장바구니를 위해 `/agent/v1/*`를 사용한다.
상품 상세 응답은 기존 네 개의 요청을 하나로 묶어 제공한다.

| 항목 | 기존 frontend API | Agent v1 |
|---|---|---|
| 인증 | 없음 | 회원가입·로그인·로그아웃·me |
| 첫 상품 화면 | `GET /v1/products` | 인증 후 `GET /agent/v1/products` |
| 자연어 추천 | `POST /v1/products/search` | session 생성 후 message 전송 |
| 상품 상세 | tactile/summary/concerns/related 4회 | `GET /agent/v1/products/{id}` 1회 |
| 취향 | 없음 | 자동 저장, 조회, 수정, 삭제 |
| 행동 | 없음 | idempotent event API |
| 장바구니 | 없음 | 조회, 추가·수량 변경, 삭제 |
| 구매 | 없음 | 여전히 없음. 버튼만 disabled |

## 2. 인증 공통 규칙

- 로그인·회원가입 응답은 `HttpOnly; SameSite=Strict` cookie와 Bearer token을 함께 준다.
- 같은 origin web frontend는 모든 fetch에 `credentials: "same-origin"`을 사용한다.
- 다른 client는 `Authorization: Bearer {access_token}`을 보낸다.
- `/health`, `/openapi.json`, `/auth/register`, `/auth/login`, `/auth/logout` 외에는 로그인이 필요하다.
- cookie를 사용하는 cross-origin 구성이라면 `credentials: "include"`와 정확한 CORS origin,
  HTTPS secure cookie 설정이 모두 필요하다.

```ts
async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    credentials: "same-origin",
    ...init,
    headers: {
      ...(init.body ? { "Content-Type": "application/json" } : {}),
      ...init.headers,
    },
  });
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.error?.message ?? `HTTP ${response.status}`);
  return payload as T;
}
```

## 3. 페이지별 API 데이터베이스

아래 표는 Notion database로 그대로 옮길 수 있는 단위다. 한 행이 frontend의 한 API다.

| 페이지 | 기능 | Method | Endpoint | 인증 | 입력 타입 | 반환 타입 | 성공 | 주요 오류 | 호출 시점 |
|---|---|---|---|---|---|---|---:|---|---|
| 공통 | 상태 | GET | `/agent/v1/health` | 불필요 | 없음 | `AgentHealth` | 200 | 500 | app boot 선택 |
| 공통 | API 요약 | GET | `/agent/v1/openapi.json` | 불필요 | 없음 | OpenAPI JSON | 200 | 500 | 개발 도구 |
| 로그인 | 회원가입 | POST | `/agent/v1/auth/register` | 불필요 | `RegisterInput` | `AuthResponse` | 201 | 400 | 회원가입 제출 |
| 로그인 | 로그인 | POST | `/agent/v1/auth/login` | 불필요 | `LoginInput` | `AuthResponse` | 200 | 400, 401 | 로그인 제출 |
| 공통 | 로그인 확인 | GET | `/agent/v1/auth/me` | 필요 | 없음 | `{user: User}` | 200 | 401 | app boot |
| 공통 | 로그아웃 | POST | `/agent/v1/auth/logout` | 선택 | `{}` | `{status}` | 200 | 500 | 로그아웃 클릭 |
| 홈 | 전체 상품 | GET | `/agent/v1/products?page=1&page_size=30` | 필요 | query `ProductPageInput` | `ProductPage` | 200 | 400, 401 | 로그인 후·페이지 이동 |
| 채팅 | 대화 생성 | POST | `/agent/v1/sessions` | 필요 | `{}` | `AgentSession` | 201 | 401 | 로그인 후 최초 1회 |
| 채팅 | 대화 복원 | GET | `/agent/v1/sessions/{session_id}` | 필요 | path ID | `AgentSessionWithMessages` | 200 | 401, 404 | 새로고침·복원 |
| 채팅 | 추천 대화 | POST | `/agent/v1/sessions/{session_id}/messages` | 필요 | `AgentMessageInput` | `AgentMessageResponse` | 200 | 400, 401, 404 | prompt 전송 |
| 상세 | 통합 상품 상세 | GET | `/agent/v1/products/{product_id}` | 필요 | path ID | `AgentProductDetail` | 200 | 401, 404 | 상품 클릭 |
| 공통 | 행동 기록 | POST | `/agent/v1/events` | 필요 | `BehaviorEventInput` | `BehaviorEventResponse` | 201/200 | 400, 401, 404 | 노출·클릭·체류 등 |
| 내 취향 | 취향 목록 | GET | `/agent/v1/preferences` | 필요 | 없음 | `PreferenceList` | 200 | 401 | dialog 열기·채팅 후 |
| 내 취향 | 취향 수정 | PATCH | `/agent/v1/preferences/{preference_id}` | 필요 | `PreferencePatch` | `Preference` | 200 | 400, 401, 404 | 사용자 correction |
| 내 취향 | 취향 삭제 | DELETE | `/agent/v1/preferences/{preference_id}` | 필요 | 없음 | `ForgetResponse` | 200 | 401, 404 | 잊기 클릭 |
| 장바구니 | 목록 | GET | `/agent/v1/cart` | 필요 | 없음 | `CartResponse` | 200 | 401 | app boot·dialog 열기 |
| 장바구니 | 추가·수량 변경 | POST | `/agent/v1/cart/items` | 필요 | `CartUpsertInput` | `CartUpsertResponse` | 201 | 400, 401, 404 | 담기 클릭 |
| 장바구니 | 삭제 | DELETE | `/agent/v1/cart/items/{product_id}` | 필요 | 없음 | `CartRemoveResponse` | 200 | 401, 404 | 삭제 클릭 |

`POST /agent/v1/checkout`은 존재하지 않는다. frontend는 구매하기 버튼을 `disabled`로
렌더링하고 이 주소를 호출하지 않는다.

## 4. 권장 페이지 호출 순서

### 앱 시작

```text
GET /agent/v1/health               선택
GET /agent/v1/auth/me              필수
  ├─ 401 → 로그인 화면
  └─ 200 → 아래 네 요청 병렬 실행
           POST /agent/v1/sessions
           GET  /agent/v1/products?page=1&page_size=30
           GET  /agent/v1/preferences
           GET  /agent/v1/cart
```

### 채팅 추천

```text
POST /agent/v1/sessions/{session_id}/messages
  → assistant message 표시
  → products를 backend 순서 그대로 렌더링
  → preferences_saved badge 표시
  → GET /agent/v1/preferences로 목록 갱신
```

### 상품 클릭

```text
POST /agent/v1/events               product_click
GET  /agent/v1/products/{id}        상세·구매자 소재·우려·유사상품 통합
dialog close → POST /agent/v1/events product_dwell
```

### 장바구니

```text
POST /agent/v1/cart/items
GET  /agent/v1/cart
```

장바구니 추가 API가 `cart_add` 행동도 함께 기록하므로 frontend가 같은 cart event를 별도로
한 번 더 전송하면 안 된다. 삭제도 동일하다.

## 5. 인증 타입

```ts
interface User {
  user_id: string;
  email: string;
  display_name: string;
  created_at: string;
}

interface RegisterInput {
  email: string;
  password: string;       // 8~256자
  display_name: string;   // 1~80자
}

interface LoginInput {
  email: string;
  password: string;
}

interface AuthResponse {
  status: "authenticated";
  user: User;
  access_token: string;
  token_type: "Bearer";
  expires_at: string;
}
```

브라우저 앱은 XSS 위험을 줄이기 위해 `access_token`을 localStorage에 복사하지 않고
HttpOnly cookie를 그대로 사용하는 것을 권장한다.

## 6. 상품 목록과 상세 타입

`ProductCard`의 촉감 source 규칙은 기존 API와 같다.

```ts
type TactileStatus = "available" | "insufficient_evidence" | "image_predicted";
type TactileTargetSource = "review_image_blended" | "image_predicted";

interface ProductCard {
  product_id: string;
  title: string;
  category: string;
  image_url: string;
  tactile_status: TactileStatus;
  reviewer_count: number;
  claim_count: number;
  tactile_target_source: TactileTargetSource;
  review_weight: number;
  image_weight: number;
  image_prediction_confidence: number;
  tactile_target_confidence: number;
  rank: number;
}

interface ProductPageInput { page: number; page_size: number; }
interface ProductPage {
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
  has_previous: boolean;
  has_next: boolean;
  mode: "catalog";
  items: ProductCard[];
}

interface AgentProductDetail {
  product: ProductCard;
  profile: TactileProfile;
  tactile_summary: TactileSummaryResponse;
  tactile_concerns: TactileConcernResponse;
  related: RelatedResponse;
}
```

`image_url`은 `/images/{product_id}.jpg` 형태의 상대 경로다. 다른 origin frontend라면
API base URL을 결합한다. `tactile_target_source=image_predicted`인 상품의 촉감은
“이미지 기반 촉감 예상”으로 표시하고 구매자들이 말하는 소재 영역은 evidence가 없으면 빈
상태로 둔다. 실제 리뷰 인용은 `evidence_details[].original_span`만 사용한다.

## 7. 대화와 개인화 추천 타입

```ts
interface AgentSession {
  session_id: string;
  state: {
    intent: Record<string, unknown>;
    last_product_ids: string[];
    turn_count: number;
    agent_version: "v1";
  };
  created_at: string;
  updated_at: string;
}

interface AgentMessageInput {
  message: string;  // 1~4000자
  limit?: number;   // 서버에서 1~50으로 제한
}

interface PersonalizedProduct extends ProductCard {
  relevance_score: number;
  personalized_score: number;
  personalization_reasons: string[];
  matched_tactile_constraints: string[];
  matched_evidence: ReviewEvidence[];
  score_breakdown: {
    personalization_inputs: Record<string, number>;
    personalization_weighted: Record<string, number>;
    personalized_final_score: number;
    [key: string]: unknown;
  };
}

interface AgentMessageResponse {
  status: "complete" | "insufficient_results";
  action: "respond_greeting" | "respond_out_of_scope" | "search_products";
  session_id: string;
  trace_id: string;
  message: string;
  intent: SearchIntent;
  preferences_saved: Array<{
    preference_id: string;
    scope_category: string | null;
    attribute_type: "tactile" | "color" | "style";
    attribute: string;
    direction: "more" | "less" | "avoid" | "must_have";
  }>;
  profile_summary: {
    preference_count: number;
    behavior_event_count: number;
    cart_item_count: number;
    personalization_applied: boolean;
  };
  products: PersonalizedProduct[];
  routing: {
    tool: "respond_greeting" | "respond_out_of_scope" | "search_products";
    source: "openai_function_call" | "gemini_function_call" | "local_intent_model";
    confidence: number | null;
  };
  provenance: {
    tools: string[];
    agent_version: "v1";
    tactile_provider: string;
    llm_provider: "openai" | "gemini" | "deterministic";
    llm_model: string;
    llm_fallback_used: boolean;
  };
}
```

frontend에서 `products`를 다시 정렬하지 않는다. `message`는 설명용이고 상품 렌더링의
source of truth는 `products`다. `personalization_reasons`는 카드의 “추천 이유”로 사용한다.
`action=search_products`일 때만 상품 grid를 교체한다. `respond_greeting`과
`respond_out_of_scope`에서는 `products=[]`이며 기존 grid와 pagination을 유지하고 채팅
답변만 추가한다. 이 두 유형은 preference를 저장하지 않는다.

응답 예시:

```json
{
  "status": "complete",
  "session_id": "shop_...",
  "trace_id": "...",
  "message": "말씀하신 조건과 저장된 취향을 반영해 관련도가 높은 상품을 찾았습니다.",
  "preferences_saved": [
    {
      "preference_id": "pref_...",
      "scope_category": "pants",
      "attribute_type": "tactile",
      "attribute": "sheerness",
      "direction": "avoid"
    }
  ],
  "profile_summary": {
    "preference_count": 1,
    "behavior_event_count": 3,
    "cart_item_count": 1,
    "personalization_applied": true
  },
  "products": [],
  "provenance": {
    "tools": ["catalog_tactile_search", "personalized_rerank"],
    "agent_version": "v1",
    "tactile_provider": "review-image-hybrid-ridge-v1",
    "llm_provider": "deterministic",
    "llm_model": "grounded-template-v1",
    "llm_fallback_used": false
  }
}
```

## 8. 행동 이벤트 타입

```ts
type BehaviorEventType =
  | "product_impression"
  | "product_click"
  | "product_dwell"
  | "image_zoom"
  | "similar_product_click"
  | "favorite_add"
  | "favorite_remove"
  | "cart_add"
  | "cart_remove"
  | "explicit_like"
  | "explicit_dislike"
  | "recommendation_skip";

interface BehaviorEventInput {
  event_id?: string;       // client UUID 권장; 없으면 server 생성
  event_type: BehaviorEventType;
  product_id: string;
  session_id?: string;
  context?: Record<string, unknown>;
}

interface BehaviorEventResponse {
  event_id: string;
  created: boolean;        // 같은 event_id 재전송은 false
}
```

권장 context:

| event | context 예시 |
|---|---|
| `product_impression` | `{rank: 1, personalized: true}` |
| `product_click` | `{source: "product_grid"}` |
| `product_dwell` | `{dwell_ms: 42000, page_active: true}` |
| `similar_product_click` | `{anchor_product_id: "...", similarity_type: "design"}` |
| `explicit_like` | `{source: "recommendation_card"}` |

`product_dwell.context.dwell_ms`는 0~300,000이어야 한다. 노출 이벤트를 무한히 보내지 말고
실제로 viewport에 진입한 상품에 한 번 보내는 것이 좋다.

## 9. 취향 타입

```ts
interface Preference {
  preference_id: string;
  scope_category: string | null;
  attribute_type: "tactile" | "color" | "style";
  attribute: string;
  direction: "more" | "less" | "avoid" | "must_have";
  strength: number;       // 0~1
  confidence: number;     // 0~1
  source: string;
  source_text: string;
  active: boolean;
  created_at: string;
  updated_at: string;
}

interface PreferenceList { items: Preference[]; auto_save: true; }
interface PreferencePatch {
  direction?: "more" | "less" | "avoid" | "must_have";
  strength?: number;
  confidence?: number;
  active?: boolean;
}
```

UI에는 자동 저장 사실을 명시하고, 잘못 배운 취향을 수정하거나 삭제할 수 있는 control을
반드시 제공한다. `source_text`에는 대화 원문이 포함되므로 analytics나 화면 로그에 불필요하게
재전송하지 않는다.

## 10. 장바구니 타입

```ts
interface CartUpsertInput {
  product_id: string;
  quantity?: number;    // 1~20, 기본 1
  session_id?: string;
}

interface CartItem {
  user_id: string;
  product_id: string;
  quantity: number;
  added_at: string;
  updated_at: string;
  product: ProductCard;
}

interface CartResponse {
  items: CartItem[];
  checkout_enabled: false;
}
```

`POST /cart/items`는 같은 상품이 있으면 quantity를 새 값으로 교체한다. 증가 연산이 아니다.
구매하기 버튼은 `checkout_enabled`를 확인하고 계속 비활성화한다.

## 11. 상태·오류 처리

```ts
interface ApiError {
  error: {
    code: "invalid_request" | "unauthorized" | "not_found" | "internal_error";
    message: string;
  };
}
```

| HTTP | 의미 | frontend 처리 |
|---:|---|---|
| 200/201 | 정상 | body 사용 |
| 400 | 입력 오류 | `error.message` 표시 |
| 401 | 로그인 없음·만료 | 로그인 화면으로 이동 |
| 404 | session, preference, product, route 없음 | 대상 갱신 후 안내 |
| 500 | server 오류 | 재시도 안내, trace가 있으면 보관 |

HTTP 200이면서 tactile evidence가 비어 있거나 `image_predicted`인 것은 오류가 아니다. 기존
명세처럼 리뷰 근거 없음과 네트워크 실패를 구분한다.

## 12. frontend 구현 체크리스트

- [ ] `/agent/v1/auth/me` 401과 일반 server 오류 구분
- [ ] cookie 사용 fetch에 credentials 설정
- [ ] 첫 화면 고유 상품 30개와 server-side pagination
- [ ] 로그인 후 session 1개 생성·유지
- [ ] prompt 전송 중 중복 submit 방지
- [ ] Agent `products`를 backend 순서 그대로 표시
- [ ] `personalization_reasons`와 `preferences_saved` 표시
- [ ] impression은 viewport 기준 한 번, event ID로 중복 방지
- [ ] 상세 닫을 때 실제 active dwell만 전송
- [ ] `original_span`만 실제 리뷰 인용으로 표시
- [ ] `image_predicted`를 구매자 의견으로 표현하지 않음
- [ ] 디자인·촉감 유사상품을 별도 section으로 표시
- [ ] 장바구니 API가 event를 함께 기록하므로 중복 cart event 금지
- [ ] 구매하기 버튼 disabled, `/checkout` 호출 없음
- [ ] 내 취향 조회·수정 또는 삭제 control 제공
- [ ] frontend console·analytics에 token, 대화 원문, source text 노출 금지
