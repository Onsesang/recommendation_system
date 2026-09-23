# 프론트엔드 페이지별 API 데이터베이스

> 작성일: 2026-08-16  
> Backend base URL: `http://127.0.0.1:8877`  
> 상세 타입·응답 예시: `notion/18_FRONTEND_API_HANDOFF.md`  
> 목적: 프론트엔드가 화면별로 필요한 API, 입력과 반환 타입을 한 표에서 확인하도록 전달

## 1. Notion 데이터베이스 속성

아래 속성으로 Notion의 **Table - Full page** 데이터베이스를 만든 뒤, 2장의 행을 옮기면 된다.
`페이지`와 `필수 여부`를 기준으로 view를 만들면 화면별 작업 관리에도 사용할 수 있다.

| 속성명 | Notion 속성 타입 | 용도 |
|---|---|---|
| API 이름 | Title | 사람이 읽는 API 이름 |
| 페이지 | Multi-select | `공통`, `첫 화면`, `상품 상세`, `비교`, `대화형 추천`, `관리자` |
| 필수 여부 | Select | `필수`, `조건부`, `선택`, `내부용` |
| Method | Select | `GET`, `POST` |
| Endpoint | Text | base URL을 제외한 경로 |
| 호출 시점 | Text | mount, 검색 제출, 상품 클릭 등 |
| Path 입력 | Text | URL path parameter와 타입 |
| Query 입력 | Text | query parameter와 타입·기본값·범위 |
| Body 입력 타입 | Text | request body 타입 이름, GET은 `없음` |
| 반환 타입 | Text | 성공 응답 타입 이름 |
| 성공 상태 | Multi-select | 정상적인 application-level 상태 |
| HTTP | Multi-select | 예상 HTTP status |
| UI 사용처 | Text | 응답을 표시할 component |
| 비고 | Text | 근거·정렬·빈 상태 관련 주의사항 |
| 연동 상태 | Status | `미착수`, `진행 중`, `완료` — 프론트팀이 관리 |

## 2. API Master Database

### 공통·첫 화면

| API 이름 | 페이지 | 필수 여부 | Method | Endpoint | 호출 시점 | Path 입력 | Query 입력 | Body 입력 타입 | 반환 타입 | 성공 상태 | HTTP | UI 사용처 | 비고 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 자연어 상품 검색 | 공통, 첫 화면, 상품 상세 | 필수 | POST | `/v1/products/search` | 어느 화면에서든 검색 제출, 검색 페이지 이동 | 없음 | 없음 | `ProductSearchRequest` | `SearchPage` | `natural_language_search` | 200, 400, 404, 500 | 전역 prompt bar, 상품 grid | 검색 결과의 다음 페이지도 같은 POST body에서 `page`만 변경. backend 순서를 유지 |
| 멀티모달 상태 | 첫 화면, 관리자 | 선택 | GET | `/v1/multimodal/health` | 앱 시작 또는 관리자 상태 확인 | 없음 | 없음 | 없음 | `MultimodalHealthResponse` | `ok` | 200, 404, 500 | 서비스 상태 badge | 일반 사용자 화면은 생략 가능 |
| 전체 상품 목록 | 첫 화면 | 필수 | GET | `/v1/products` | 첫 진입과 페이지 이동 | 없음 | `page?: integer=1, 1 이상`<br>`page_size?: integer=30, 1~100` | 없음 | `ProductPage<ProductCard>` | `catalog` | 200, 400, 404, 500 | 30개 상품 grid, pagination | 고유 상품만 반환. frontend에서 임의 재정렬·중복 제거하지 않음 |

### 상품 상세

상품을 클릭하면 아래 네 GET 요청을 `Promise.all`로 병렬 호출한다. 전역 prompt bar는 같은
`POST /v1/products/search`를 계속 사용한다.

| API 이름 | 페이지 | 필수 여부 | Method | Endpoint | 호출 시점 | Path 입력 | Query 입력 | Body 입력 타입 | 반환 타입 | 성공 상태 | HTTP | UI 사용처 | 비고 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 상품 촉감 profile | 상품 상세 | 필수 | GET | `/v1/products/{product_id}/tactile` | 상세 진입 | `product_id: string` 필수 | `include_claims?: boolean=true`<br>프론트 권장값 `false` | 없음 | `TactileProfile` | `available`, `insufficient_evidence` | 200, 400, 404, 500 | 상세 기본 정보·근거 통계 | 전체 claim이 필요할 때만 `true` |
| 구매자들이 말하는 소재 | 상품 상세 | 필수 | GET | `/v1/products/{product_id}/tactile-summary` | 상세 진입 | `product_id: string` 필수 | 없음 | 없음 | `TactileSummaryResponse` | `available`, `insufficient_evidence` | 200, 404, 500 | 소재 요약 section | `original_span`만 실제 리뷰 인용문으로 표시 |
| 소재 관련 의견 | 상품 상세 | 필수 | GET | `/v1/products/{product_id}/tactile-concerns` | 상세 진입 | `product_id: string` 필수 | 없음 | 없음 | `TactileConcernResponse` | `available`, `no_qualifying_concerns`, `insufficient_evidence` | 200, 404, 500 | 소재 우려·의견 cards | 낮은 평점만으로 생성된 의견이 아니라 명시적 소재 부정 근거를 사용 |
| 디자인·촉감 유사상품 | 상품 상세 | 필수 | GET | `/v1/products/{product_id}/related` | 상세 진입 | `product_id: string` 필수 | `limit?: integer=10, 1~30` | 없음 | `RelatedResponse` | 정상 배열, 빈 배열 | 200, 400, 404, 500 | 디자인 유사 carousel, 촉감 유사 carousel | 두 배열의 점수 체계가 다르므로 배열 간 점수를 직접 비교하지 않음 |
| 촉감 대안 상품 | 상품 상세 | 조건부 | POST | `/v1/recommendations/tactile-alternatives` | concern의 대안 찾기 클릭 | 없음 | 없음 | `TactileAlternativeRequest` | `TactileAlternativeResponse` | 결과 있음, `results=[]` | 200, 400, 404, 500 | 소재 우려별 대안 modal·section | concern의 `alternative_action`이 있을 때만 호출 |

### 상품 비교

| API 이름 | 페이지 | 필수 여부 | Method | Endpoint | 호출 시점 | Path 입력 | Query 입력 | Body 입력 타입 | 반환 타입 | 성공 상태 | HTTP | UI 사용처 | 비고 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 상품 촉감 비교 | 비교 | 선택 | POST | `/v1/products/tactile-compare` | 비교할 상품 2개 이상 선택 후 제출 | 없음 | 없음 | `TactileCompareRequest` | `TactileCompareResponse` | `available`, 상품별 `insufficient_evidence` | 200, 400, 404, 500 | 공통점·차이·한쪽만·상충 section | 상품 2~20개. 근거가 없는 속성에 중간값을 추측하지 않음 |

### 대화형 추천

| API 이름 | 페이지 | 필수 여부 | Method | Endpoint | 호출 시점 | Path 입력 | Query 입력 | Body 입력 타입 | 반환 타입 | 성공 상태 | HTTP | UI 사용처 | 비고 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 자연어 intent 해석 | 대화형 추천 | 선택 | POST | `/v1/tactile/intent` | 추천 전 조건 preview 또는 후속 대화 | 없음 | 없음 | `TactileIntentRequest` | `SearchIntent` | 해석 완료 | 200, 400, 404, 500 | 조건 chip·debug panel | 메인 검색만 구현할 때는 불필요 |
| 대화형 추천 agent | 대화형 추천 | 선택 | POST | `/v1/tactile/agent` | 대화 메시지 제출 | 없음 | 없음 | `TactileAgentRequest` | `TactileAgentResponse` | `complete`, `needs_clarification`, `insufficient_evidence` | 200, 400, 404, 500 | 대화 응답·추천 cards | category가 없으면 명확화 질문을 반환할 수 있음 |
| 후보 촉감 재정렬 | 대화형 추천 | 내부용 | POST | `/v1/recommendations/tactile-rerank` | 별도 검색기의 후보를 backend에서 재정렬할 때 | 없음 | 없음 | `TactileRerankRequest` | `TactileRerankResponse` | 결과 있음, `results=[]` | 200, 400, 404, 500 | 별도 추천 pipeline | 일반 프론트에서는 직접 호출하지 않고 `/products/search` 또는 `/tactile/agent` 사용 권장 |

### 관리자·개발 화면

| API 이름 | 페이지 | 필수 여부 | Method | Endpoint | 호출 시점 | Path 입력 | Query 입력 | Body 입력 타입 | 반환 타입 | 성공 상태 | HTTP | UI 사용처 | 비고 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 리뷰 촉감 상태 | 관리자 | 선택 | GET | `/v1/tactile/health` | 상태 화면 진입 | 없음 | 없음 | 없음 | `TactileHealthResponse` | `ok` | 200, 404, 500 | 상태 panel | 사용자 화면에는 불필요 |
| 리뷰 촉감 평가 | 관리자 | 선택 | GET | `/v1/tactile/evaluation` | 평가 화면 진입 | 없음 | 없음 | 없음 | `TactileEvaluationResponse` | 평가 artifact 있음 | 200, 404, 500 | 평가 panel | 평가 파일이 없으면 404 |
| 멀티모달 평가 | 관리자 | 선택 | GET | `/v1/multimodal/evaluation` | 평가 화면 진입 | 없음 | 없음 | 없음 | `MultimodalEvaluationResponse` | 평가 artifact 있음 | 200, 404, 500 | 평가 panel | 사용자 화면에는 불필요 |

## 3. 입력 타입 데이터베이스

`?`는 선택 필드다. JSON body가 있는 모든 요청은 `Content-Type: application/json`을
보내야 한다.

| 타입 이름 | 필드 | TypeScript 타입 | 필수 | 기본값·범위 | 설명 |
|---|---|---|---|---|---|
| `ProductSearchRequest` | `query_text` | `string` | 필수 | 공백이 아닌 문자열 | 자연어 검색문 |
| `ProductSearchRequest` | `page` | `number` | 선택 | 기본 1, 1 이상 | 검색 결과 page |
| `ProductSearchRequest` | `page_size` | `number` | 선택 | 기본 30, 1~100 | 한 page 상품 수 |
| `TactileAlternativeRequest` | `anchor_product_id` | `string` | 필수 | 존재하는 상품 ID | 현재 상품 |
| `TactileAlternativeRequest` | `direction` | `"more" \| "less"` | 필수 | 두 값 중 하나 | 해당 촉감의 증감 방향 |
| `TactileAlternativeRequest` | `tactile_concept` | `string` | 필수 | 지원되는 정규화 concept | 예: `thinness` |
| `TactileAlternativeRequest` | `top_k` | `number` | 선택 | 기본 10, 1~50 | 반환 결과 수 |
| `TactileCompareRequest` | `product_ids` | `string[]` | 필수 | 2~20개, 빈 값·중복 불가 | 비교할 상품 |
| `TactileCompareRequest` | `evidence_limit` | `number` | 선택 | 기본 3, 1~10 | 속성·상품당 최대 evidence 수 |
| `TactileIntentRequest` | `query_text` | `string` | 둘 중 하나 | `message`의 alias | 자연어 문장 |
| `TactileIntentRequest` | `message` | `string` | 둘 중 하나 | `query_text`의 alias | 자연어 문장 |
| `TactileIntentRequest` | `current_product_id` | `string` | 선택 | 존재하는 상품 ID 권장 | 현재 보고 있는 상품 |
| `TactileIntentRequest` | `previous_intent` | `Partial<SearchIntent>` | 선택 | 없음 | 이전 대화의 구조화 intent |
| `TactileAgentRequest` | `message` | `string` | 둘 중 하나 | `query_text`보다 우선 | 자연어 문장 |
| `TactileAgentRequest` | `query_text` | `string` | 둘 중 하나 | 없음 | 자연어 문장 |
| `TactileAgentRequest` | `current_product_id` | `string` | 선택 | 존재하는 상품 ID | 현재 상품 context |
| `TactileAgentRequest` | `previous_intent` | `Partial<SearchIntent>` | 선택 | 없음 | 이전 intent |
| `TactileAgentRequest` | `top_k` | `number` | 선택 | 기본 10, 1~500 | 추천 수 |
| `TactileRerankRequest` | `candidates` | `{ product_id: string; base_score: number }[]` | 필수 | product ID 중복 불가, score는 유한수 | 외부 retrieval 후보 |
| `TactileRerankRequest` | `strategy` | `"baseline" \| "global_history" \| "category_conditioned" \| "context_gated"` | 선택 | 기본 `baseline` | reranking 방식 |
| `TactileRerankRequest` | `history_product_ids` | `string[]` | 선택 | 기본 `[]` | 사용자 이력 상품 |
| `TactileRerankRequest` | `intent` | `Partial<SearchIntent>` | 선택 | 기본 빈 intent | 구조화 조건 |
| `TactileRerankRequest` | `top_k` | `number` | 선택 | 기본 10, 1~500 | 결과 수 |

## 4. 반환 타입 데이터베이스

여기서는 화면 연결에 필요한 최상위 필드만 정의한다. 중첩 타입의 전체 필드와 JSON 예시는
`18_FRONTEND_API_HANDOFF.md`의 해당 장을 사용한다.

| 반환 타입 | 주요 필드 | 중첩 타입 | 빈 상태·주의사항 | 상세 명세 |
|---|---|---|---|---|
| `ProductPage<ProductCard>` | `total`, `page`, `page_size`, `total_pages`, `has_previous`, `has_next`, `items`, `mode` | `ProductCard[]` | 현재 465개 고유 상품. `page_size=30`이면 16 page | 18번 문서 3~4장 |
| `SearchPage` | page 공통 필드, `query_text`, `intent`, `message` | `ProductSearchCard[]`, `SearchIntent` | evidence가 없어도 검색 결과일 수 있음 | 18번 문서 5장 |
| `TactileProfile` | `product_id`, `title`, `category`, `representative_claims`, count들, `evidence_strength`, `source_breakdown`, `status` | claim은 `include_claims=true`일 때 포함 | `status=insufficient_evidence`는 HTTP 오류가 아님 | 18번 문서 6장 |
| `TactileSummaryResponse` | `product_id`, `title`, `status`, `summary`, count들, `source_breakdown`, `message` | `TactileSummaryItem[]`, `ReviewEvidence[]` | 근거 부족이면 `summary=[]` | 18번 문서 7장 |
| `TactileConcernResponse` | `product_id`, `title`, `category`, `status`, `concerns` | `TactileConcern[]`, `ReviewEvidence[]`, `alternative_action` | `no_qualifying_concerns`와 `insufficient_evidence`를 구분 | 18번 문서 8장 |
| `RelatedResponse` | `product_id`, `category`, `anchor_target`, `design_similar`, `tactile_similar`, method note들 | `TargetInfo`, `DesignRelated[]`, `TactileRelated[]` | `image_predicted`를 구매자 리뷰라고 표시하지 않음 | 18번 문서 9장 |
| `TactileAlternativeResponse` | `anchor_product_id`, `direction`, `tactile_concept`, `results`, `message` | recommendation result와 `score_breakdown`, `reason.evidence` | `results=[]`도 정상 200 | 18번 문서 10장 |
| `TactileCompareResponse` | `product_ids`, `dimensions`, `groups` | 상품별 status·direction·confidence·evidence | `insufficient_evidence`에 임의 중간값 금지 | 18번 문서 11장 |
| `SearchIntent` | `current_product_id`, `category`, `query_text`, `desired_more`, `desired_less`, `avoid`, `must_have`, `source`, `confidence` | 문자열 배열 | confidence는 보정 확률이 아님 | 18번 문서 5·12장 |
| `TactileAgentResponse` | `status`, `message`, `intent`, `retrieval`, `results` | `SearchIntent`, recommendation results | category가 없으면 `needs_clarification` | 18번 문서 12장 |
| `TactileRerankResponse` | `strategy`, `count`, `results` | score breakdown, reason·evidence | 프론트 직접 호출은 보통 불필요 | Backend 내부용 |
| `MultimodalHealthResponse` | `status`, `catalog_products`, `design_embedding`, `tactile_target`, `weights` | model·dimension·coverage·source counts | 운영 상태·모델 버전 확인용 | 18번 문서 13장 |
| `TactileHealthResponse` | artifact·feature 상태 | 구현 상태에 따라 확장 가능 | 관리자용 | 18번 문서 13장 |
| `TactileEvaluationResponse` | 평가 artifact 전체 | 평가 버전에 따라 확장 가능 | runtime UI 계약으로 사용하지 않음 | 18번 문서 13장 |
| `MultimodalEvaluationResponse` | cold-start·embedding 평가 artifact | 평가 버전에 따라 확장 가능 | runtime UI 계약으로 사용하지 않음 | 18번 문서 13장 |
| `ApiError` | `error.code`, `error.message` | 없음 | 400·404·500 처리 | 18번 문서 15장 |

## 5. 페이지별 호출 흐름

| 순서 | 페이지 | 동작 | API | 병렬 여부 | 성공 후 처리 |
|---:|---|---|---|---|---|
| 1 | 첫 화면 | 앱 진입 | `GET /v1/products?page=1&page_size=30` | 단독 | 상품 30개와 pagination 표시 |
| 2 | 어느 화면 | 자연어 검색 제출 | `POST /v1/products/search` | 단독 | 검색 상품 grid로 교체 |
| 3 | 어느 화면 | 검색 결과 다음 page | `POST /v1/products/search` | 단독 | 기존 query를 유지하고 `page`만 증가 |
| 4 | 상품 상세 | 상품 클릭 | profile, summary, concerns, related의 GET 4개 | 병렬 | 각 section을 독립적으로 표시 |
| 5 | 상품 상세 | 소재 우려의 대안 찾기 | `POST /v1/recommendations/tactile-alternatives` | 단독 | 대안 상품 표시 |
| 6 | 비교 | 상품 2~20개 비교 | `POST /v1/products/tactile-compare` | 단독 | 공통·차이·한쪽만·상충 그룹 표시 |
| 7 | 대화형 추천 | 문장 제출 | `POST /v1/tactile/agent` | 단독 | 추천 또는 명확화 질문 표시 |

## 6. 프론트 구현 시 고정 규칙

| 규칙 | 프론트 처리 |
|---|---|
| 이미지 URL | 상대 경로이므로 `${API_BASE_URL}${image_url}`로 표시 |
| 상품 정렬 | backend의 `items`, `design_similar`, `tactile_similar`, `results` 순서를 유지 |
| 리뷰 인용 | `ReviewEvidence.original_span`만 실제 구매자 리뷰 인용으로 사용 |
| target source | `review_image_blended`는 `리뷰+이미지`, `image_predicted`는 `이미지 기반 촉감 예상`으로 표시 |
| 근거 부족 | HTTP 200의 `insufficient_evidence`는 오류가 아니라 빈 상태로 표시 |
| 빈 배열 | 정상 200으로 처리하고 각 section의 빈 상태 문구 표시 |
| 오류 | `ApiError.error.message`를 사용하고 400, 404, 500을 구분 |
| 점수 | confidence와 score를 확률이라고 표현하지 않고 backend 결과의 정렬 지표로 사용 |
| 보안 | raw reviewer ID는 응답에 없으며 `review_id`도 사용자에게 노출할 필요 없음 |

## 7. 현재 연결 정보

| 항목 | 값 |
|---|---|
| 로컬 API | `http://127.0.0.1:8877` |
| 데모 | `http://127.0.0.1:8877/tactile-demo` |
| OpenAPI 목록 | `http://127.0.0.1:8877/api/openapi.json` |
| 인증 | 없음 |
| Content-Type | JSON body는 `application/json` 필수 |
| CORS | 현재 `Access-Control-Allow-Origin: *` |
| 외부 접속 | 현재 localhost bind이므로 reverse proxy 또는 bind 변경 필요 |
| 전체 상품 | 465개 고유 상품 |
| 기본 pagination | 30개씩 16 page |
