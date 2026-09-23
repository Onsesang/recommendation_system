# 개인화 쇼핑 에이전트 v1 구조와 기능

> 작성일: 2026-08-21  
> 구현 위치: `shopping_agent/v1/`  
> API prefix: `/agent/v1`  
> 데모 UI: `http://127.0.0.1:8878/agent-demo`

## 1. 이번 버전의 목표

기존 쇼핑몰을 단순 검색 화면이 아니라 사용자의 말과 행동을 기억하는 쇼핑 에이전트로
확장했다. 기존의 리뷰 기반 촉감 설명, 촉감 유사상품, FashionCLIP 디자인 유사상품은
그대로 사용한다. 촉감 모델은 Agent 코드와 분리했기 때문에 이후 새 모델로 교체해도 로그인,
대화, 취향 저장, 장바구니 API는 바뀌지 않는다.

v1에서 제공하는 범위는 다음과 같다.

- 회원가입, 로그인, 로그아웃, 로그인 상태 확인
- 사용자별 채팅 세션과 대화 기록
- 채팅에서 촉감, 색상, 스타일 취향 자동 추출·저장
- 상품 노출, 클릭, 체류 시간, 유사상품 클릭, 찜, 명시적 평가, 장바구니 행동 저장
- 대화 조건과 저장된 취향·행동·장바구니를 함께 반영한 재정렬
- 상품 상세, 실제 리뷰 소재 근거, 소재 우려, 디자인·촉감 유사상품
- 장바구니 추가·수량 변경·삭제
- 비활성화된 구매하기 버튼
- Agent 실행별 trace ID와 로컬 JSONL 실행 기록
- OpenAI, Gemini, 외부 모델 없는 deterministic fallback

주문, 결제, 재고 차감은 v1 범위가 아니다. `/checkout` API 자체가 없고 UI의 구매하기
버튼도 `disabled` 상태다.

## 2. 전체 구조

```text
Browser UI
  ├─ 인증 / 사용자별 세션
  ├─ 채팅 / 취향 관리
  ├─ 전체 상품 / 상품 상세
  └─ 행동 이벤트 / 장바구니
          │
          ▼
shopping_agent/v1/server.py              Public API
          │
          ├─ auth.py + database.py       로그인·사용자 데이터
          ├─ preferences.py              채팅 취향 추출·기억
          ├─ service.py                  Agent 실행 순서
          ├─ personalization.py          개인화 점수·정렬
          ├─ llm.py                      OpenAI/Gemini/안전한 fallback
          ├─ tracing.py                  로컬 trace와 LangSmith 경계
          └─ tools.py                    기존 추천 시스템 adapter
                    │
                    ▼
             recommendation_api
             ├─ review-grounded tactile
             ├─ image-predicted tactile
             └─ FashionCLIP design embedding
```

핵심 원칙은 LLM이 상품을 직접 만들거나 순서를 결정하지 않는 것이다. 검색과 점수 계산은
재현 가능한 추천 모듈이 수행하고, LLM은 확정된 상품·추천 이유·리뷰 근거만 받아 한국어
답변을 작성한다. LLM API가 실패해도 deterministic 답변으로 전환되므로 상품 검색은
중단되지 않는다.

### 대화 유형과 도구 라우팅

모든 메시지를 바로 상품 검색에 넣지 않고 모델이 아래 함수 도구 중 정확히 하나를 선택한다.

| 도구 | 선택 대상 | 실행 결과 |
|---|---|---|
| `respond_greeting` | 인사·감사·가벼운 안부만 있는 메시지 | 인사 후 원하는 스타일이나 옷 입력 요청 |
| `respond_out_of_scope` | 날씨·뉴스·번역·코딩 등 쇼핑과 무관한 요청 | 답변 불가 안내 후 스타일이나 옷 입력 요청 |
| `search_products` | 의류·패션·디자인·소재·촉감·상품 탐색 요청 | 기존 취향 추출·검색·개인화 정렬 실행 |

도구의 JSON Schema, 설명과 라우팅 지침은 `shopping_agent/v1/agent_tools.py`에 있고 실행은
allow-list registry만 허용한다. OpenAI는 Responses API strict function calling, Gemini는
Gemini function calling을 사용한다. 코드에 `if message == "안녕"` 같은 문장 비교는 없다.
API 키가 없거나 원격 router가 실패하면 `configs/v1.json`의 라벨 예시로 학습한 로컬
character n-gram logistic model이 동일한 세 도구 중 하나를 선택한다. 응답 문구와 fallback
학습 예시도 config에서 수정할 수 있다.

인사나 범위 밖 요청은 상품 검색·취향 저장을 실행하지 않으며 현재 화면의 상품 목록도
유지한다. 인사와 쇼핑 요청이 한 문장에 함께 있으면 `search_products`를 우선한다.

## 3. 폴더와 버전 관리

| 위치 | 역할 |
|---|---|
| `shopping_agent/CURRENT_VERSION` | 현재 활성 major 버전, 현재 값 `v1` |
| `shopping_agent/v1/VERSION` | 구현 package 버전, 현재 값 `1.1.0` |
| `shopping_agent/v1/` | v1 코드와 UI |
| `shopping_agent/configs/v1.json` | v1 인증·행동·점수 가중치 |
| `shopping_agent/evaluation/v1.json` | v1 오프라인 구조 평가 결과 |
| `shopping_agent/data/agent_v1.sqlite3` | 로컬 사용자 DB, git 제외 |
| `shopping_agent/traces/YYYY-MM-DD.jsonl` | Agent 실행 trace, git 제외 |

계약이 깨지는 변경은 `shopping_agent/v2/`와 `/agent/v2`로 새로 만든다. v1과 호환되는
모델·가중치 개선은 package minor 버전을 올리고 평가 결과를 별도 파일로 남긴다. 촉감 모델
교체는 `TactileProvider` adapter 구현만 교체하며 Agent public API는 유지한다.

## 4. 로그인과 데이터 저장

SQLite 스키마 v1은 다음 데이터를 사용자별로 분리한다.

| 테이블 | 저장 내용 |
|---|---|
| `users` | 이메일, 표시 이름, password hash와 salt |
| `auth_sessions` | hash 처리된 로그인 token, 만료 시간 |
| `agent_sessions` | 대화별 intent와 현재 Agent state |
| `messages` | user/assistant 대화와 trace metadata |
| `preferences` | 정규화된 촉감·색상·스타일 취향 |
| `behavior_events` | 클릭·체류·장바구니 등 idempotent 이벤트 |
| `cart_items` | 사용자별 상품과 수량 |

비밀번호는 원문을 저장하지 않고 사용자별 무작위 salt와 PBKDF2-HMAC-SHA256 310,000회로
처리한다. 로그인 token도 DB에는 SHA-256 hash만 저장한다. 브라우저에는 기본 30일 만료의
`HttpOnly; SameSite=Strict` cookie를 사용하며 Bearer token 방식도 지원한다. 실제 HTTPS
배포에서는 `SHOPPING_AGENT_COOKIE_SECURE=true`를 반드시 설정한다.

현재 구현은 연구·로컬 데모용 인증이다. 운영 배포 전에는 HTTPS, rate limit, 이메일 확인,
비밀번호 재설정, CSRF 정책, 개인정보 보존·삭제 정책과 관리형 DB migration을 추가해야 한다.

## 5. 취향을 자동으로 기억하는 방식

대화는 먼저 기존 deterministic intent parser로 상품 category와 촉감 조건을 해석한다.
예를 들어 “부드럽고 비치지 않는 바지를 찾아줘”는 `category=pants`,
`avoid=[sheerness]`와 같은 정규화된 intent가 된다. 색상과 스타일은 명시적인 한국어·영어
표현 사전으로 추출한다.

저장되는 preference의 주요 필드는 다음과 같다.

- `scope_category`: 취향이 적용되는 상품군. 바지의 촉감 취향을 다른 category에 강하게 전파하지 않는다.
- `attribute_type`: `tactile`, `color`, `style`
- `attribute`: open-vocabulary 촉감 concept 또는 정규화된 색상·스타일
- `direction`: `more`, `less`, `avoid`, `must_have`
- `strength`, `confidence`: 점수 반영 강도와 추출 신뢰도
- `source`, `source_text`: 어디서 배웠는지와 원문

같은 preference가 다시 나타나면 중복 행을 만들지 않고 갱신한다. 사용자는 내 취향
화면에서 항목을 삭제하거나 API로 방향·강도·신뢰도를 수정할 수 있다. LLM이 취향 저장을
결정하지 않으므로 OpenAI와 Gemini를 바꿔도 preference 계약은 변하지 않는다.

## 6. 행동 기반 개인화

허용 이벤트와 기본 신호 강도는 `shopping_agent/configs/v1.json`에 있다. 상품 노출은 매우
약한 신호, 클릭과 체류는 중간 신호, 장바구니와 명시적 좋아요는 강한 신호로 설정했다.
삭제, 싫어요, 건너뛰기는 음수 신호다.

체류 시간은 최대 90초까지만 선형 반영한다. 행동 신호는 30일 half-life로 감쇠한다. 다른
category에서 발생한 행동은 `0.02` gate만 통과시켜 매우 약하게 사용한다. 장바구니 이력은
그 상품의 촉감을 좋아한다는 직접 증거로 취급하지 않고, 같은 category 후보의 디자인·촉감
유사 context로만 사용한다.

`event_id`는 중복 요청에 안전하다. frontend가 같은 이벤트를 재전송하면 두 번 누적하지
않고 `created=false`를 반환한다.

## 7. 개인화 점수

현재 기본 점수는 다음의 가중합이다. 모든 값과 가중치는 응답의 `score_breakdown`에서
확인할 수 있고 config로 교체할 수 있다.

```text
personalized_score
  = 0.46 × 현재 query relevance
  + 0.16 × 명시적 tactile 조건
  + 0.08 × 저장된 color/style 취향
  + 0.08 × 행동 상품과의 design similarity
  + 0.08 × 행동 상품과의 tactile similarity
  + 0.07 × cart context similarity
  + 0.03 × category affinity
  + 0.04 × deterministic exploration
```

exploration은 사용자와 상품 ID의 hash로 계산하므로 같은 입력에서 재현 가능하다. 현재 값은
연구용 초기값이며 온라인 A/B test로 검증된 최적값은 아니다. 점수 변경 전후에는
`shopping_agent/v1/evaluation.py`를 실행하고 실제 사용자 relevance 지표도 별도로 확인해야
한다.

## 8. 디자인·촉감 모델의 분리

디자인 신호는 FashionCLIP 상품 이미지 embedding cosine similarity를 중심으로 사용한다.
기존 유사상품 API에서는 이미지 0.85, 제목·스타일 0.15를 결합한다.

촉감 신호는 실제 리뷰 claim으로 만든 상품 촉감 target과 이미지 기반 촉감 예측을 결합한
hybrid target을 사용한다. 리뷰가 없는 상품도 이미지 예측 target으로 촉감 유사상품 후보에
들어갈 수 있지만, UI에는 `이미지 기반 촉감 예상`이라고 표시하며 구매자 의견으로 말하지
않는다. 실제 리뷰 span은 별도의 evidence 필드로만 제공한다.

Agent는 현재 모델을 `CurrentTactileProvider` 뒤에서 호출한다. 새 촉감 모델은 다음 계약만
구현하면 된다.

```text
version
search(query_text, limit)
tactile_scores(candidates, intent)
product_detail(product_id)
```

따라서 모델 artifact, embedding 차원이나 학습 방법이 바뀌어도 `/agent/v1`의 로그인·대화·
장바구니 계약은 유지할 수 있다.

## 9. OpenAI와 Gemini 설정

실제 key는 commit하지 않고 `shopping_agent/.env`에 입력한다. 이 파일은 `.gitignore`에
포함되어 있다.

OpenAI 예시:

```dotenv
SHOPPING_AGENT_LLM_PROVIDER=openai
OPENAI_API_KEY=여기에_키_입력
OPENAI_MODEL=gpt-5.6
```

Gemini 예시:

```dotenv
SHOPPING_AGENT_LLM_PROVIDER=gemini
GEMINI_API_KEY=여기에_키_입력
GEMINI_MODEL=gemini-3.7-flash
```

`SHOPPING_AGENT_LLM_PROVIDER=auto`에서는 OpenAI key, Gemini key 순서로 선택하고 둘 다
없으면 `grounded-template-v1`을 사용한다. 원격 모델은 추천 순서를 변경하지 않고 이미
확정된 결과의 설명만 작성한다.

## 10. LangSmith 연결 준비 상태

각 Agent run에는 다음 경계가 있다.

- `trace_id`, 익명화된 session hash, 시작·종료 시간
- 사용자 입력과 turn count
- tool 이름, tool 입력, 결과 개수와 intent 요약
- 최종 상품 ID, Agent·촉감·LLM 모델 버전
- 실패 시 error

현재 v1은 이를 `shopping_agent/traces/*.jsonl`에만 저장한다. `LANGSMITH_API_KEY`,
`LANGSMITH_PROJECT`, `LANGSMITH_ENDPOINT`, `LANGSMITH_TRACING` 환경변수 자리는 마련했지만
LangSmith SDK exporter는 아직 연결하지 않았고 health의 `langsmith_export_active`는
`false`다. 나중에 exporter를 `TraceRecorder.finish()` 뒤에 추가해도 추천 로직은 수정하지
않는다.

주의: trace에는 원문 사용자 메시지가 들어갈 수 있다. 외부 전송 전에 개인정보 필터,
사용자 동의, 보존 기간, project 접근 권한을 먼저 결정해야 한다.

## 11. 실행과 운영 명령

```bash
cd /home/user/onsesang/material_span_grounding
shopping_agent/start.sh
shopping_agent/status.sh
shopping_agent/stop.sh
```

기본 주소:

- UI: `http://127.0.0.1:8878/agent-demo`
- Health: `http://127.0.0.1:8878/agent/v1/health`
- OpenAPI summary: `http://127.0.0.1:8878/agent/v1/openapi.json`

다른 PC에서 접속할 때는 backend를 바로 public bind하기보다 인증과 TLS가 설정된 reverse
proxy 뒤에 둔다. frontend가 다른 origin이면 `.env`의
`SHOPPING_AGENT_CORS_ORIGIN`을 정확한 frontend origin으로 설정한다.

## 12. 검증 결과와 한계

완료된 자동 검증:

- 회원가입·로그인·token 만료·로그아웃과 사용자 데이터 격리
- 채팅 취향 자동 저장과 correction/delete
- event idempotency, 체류 입력 검증, 장바구니 추가·삭제
- Agent chat, 상품 상세, exact review evidence 비노출 규칙
- 구매 API 부재와 비활성 버튼
- OpenAI/Gemini request·response adapter와 fallback
- 기존 촉감·추천 회귀 테스트
- 오프라인 구조 평가의 finite score, breakdown, category constraint, hallucinated product 0건

오프라인 구조 평가는 코드 계약이 깨지지 않았음을 확인하는 smoke test다. 개인화가 실제로
클릭률·장바구니율·만족도를 높인다는 뜻은 아니다. 다음 연구 단계에서는 시간 순서 기반
train/test 분리, 신규 사용자와 기존 사용자 cohort, 비개인화 baseline 대비 Recall@K,
NDCG@K, cart rate, preference correction rate를 평가해야 한다.
