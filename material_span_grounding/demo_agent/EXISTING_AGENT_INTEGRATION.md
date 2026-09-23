# 기존 Shopping Agent 조사 결과

## 위치와 현재 상태

- 구현: `shopping_agent/v1/`
- 실행 UI: `http://127.0.0.1:8878/agent-demo`
- API prefix: `/agent/v1`
- 영속 저장소: `shopping_agent/data/agent_v1.sqlite3`
- 조사 시점 서비스 상태: inactive
- `shopping_agent/.env`: 없음. 따라서 기본 설정에서는 외부 LLM key 없이 deterministic
  router/template로 동작한다.

기존 DB와 코드는 읽기만 했으며 계정, 대화, 취향, 이벤트, 장바구니 데이터를 수정하지
않았다.

## 이미 구현된 기능

| 기능 | 구현 위치 | 비고 |
| --- | --- | --- |
| 회원가입·로그인·로그아웃 | `v1/auth.py`, `v1/server.py` | PBKDF2-HMAC-SHA256, random salt, token hash |
| 인증 세션 | `v1/database.py`의 `auth_sessions` | HttpOnly, SameSite=Strict cookie; HTTPS에서는 Secure 설정 필요 |
| 대화 세션·메시지 | `v1/database.py`의 `agent_sessions`, `messages` | turn state와 user/assistant 원문 영속화 |
| 사용자 취향 메모리 | `v1/preferences.py`, `preferences` table | category-scoped, more/less/avoid/must_have, 수정·삭제 가능 |
| 행동 메모리 | `v1/personalization.py`, `behavior_events` | 클릭·체류·찜·장바구니 등, 시간 감쇠 적용 |
| 장바구니 | `cart_items` 및 `/agent/v1/cart*` | checkout은 의도적으로 비활성화 |
| LLM fallback | `v1/llm.py`, `v1/routing.py` | OpenAI/Gemini function calling 실패 시 local router |
| 추적 | `v1/tracing.py` | trace ID와 local JSONL; LangSmith remote export는 미구현 |
| 관리 UI | `v1/static/` | 로그인, 채팅, 상품, 취향 삭제, 장바구니 dialog |

주요 endpoint는 `/agent/v1/auth/*`, `/agent/v1/sessions/*`,
`/agent/v1/preferences*`, `/agent/v1/events`, `/agent/v1/cart*`다.

## 이번 Last2 데모와 바로 합치지 않은 이유

기존 Shopping Agent는 465개 상품의 review-image hybrid Ridge/BGE/FashionCLIP catalog를
사용한다. 이번 데모는 825,840개 상품의 고정 `fashionclip_last2.pt` 14D image inference
cache를 사용한다. 두 점수의 의미, 상품 ID coverage, evidence provenance가 다르므로 기존
`PersonalizedRanker`에 Last2 값을 끼워 넣으면 다음 문제가 생긴다.

1. 사용자 history 개인화를 재현하지 않는다는 이번 데모 범위를 벗어난다.
2. review-derived evidence와 image-derived prediction이 UI에서 섞일 수 있다.
3. 기존 465개 catalog 이벤트가 825K parent ASIN에 동일하게 연결된다고 보장할 수 없다.
4. 기존 개인화 ranking weight 합은 1.0으로 고정돼 있어 Last2 항 추가 시 별도 offline
   evaluation과 재설정이 필요하다.

그래서 현재 구현은 기존 broad category parser만 재사용하며, 대화 문맥은 Streamlit
session 안에서 유지하고 ranking은 explicit Last2 조건만 사용한다.

## 안전한 후속 통합 경계

로그인과 메모리를 붙일 경우 `shopping_agent`의 DB/auth 계층은 그대로 재사용할 수 있다.
권장 경계는 새로운 versioned provider/endpoint에서 다음만 수행하는 것이다.

```text
기존 auth + agent session
        ↓
현재 발화와 세션의 explicit query state
        ↓
demo_agent.TactileAgent
        ↓
825K Last2 explicit ranking
```

이때 저장된 장기 취향과 행동 이벤트는 기본 ranking에 넣지 않고, 사용자가 명시적으로
“내 저장 취향도 적용”을 선택할 때만 category-local로 적용해야 한다. 도입 전에는 ASIN
mapping audit, configurable weight, 별도 offline evaluation, 새 endpoint test가 필요하다.

## 발견한 운영상 주의점

- `configs/v1.json`에는 `raw_chat_retention_days: 30`이 있지만 메시지/원문 취향을 지우는
  purge job 또는 cleanup 함수는 현재 코드에서 발견되지 않았다.
- cookie의 `Secure` 속성은 `SHOPPING_AGENT_COOKIE_SECURE=true`일 때만 켜진다.
- LangSmith는 “ready/configured” metadata만 있고 실제 remote exporter는 없다.
- 조사 시 기존 service는 inactive였으며, 사용자 요청 없이 시작하거나 DB를 변경하지 않았다.
