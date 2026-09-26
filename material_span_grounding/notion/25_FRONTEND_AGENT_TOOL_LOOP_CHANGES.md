# 프론트엔드 전달: OpenAI 도구 호출 Agent 변경 사항

> 작성일: 2026-09-25
> 기준 문서: `notion/24_FRONTEND_SHOPPING_AGENT_API_V1.md`
> 엔드포인트, 인증, 기존 응답 필드는 바뀌지 않았다. 아래 필드와 `action` 값이 **추가**됐다.

## 1. 무엇이 바뀌었나

서버의 `SHOPPING_AGENT_LLM_PROVIDER=openai`이면 `POST /agent/v1/sessions/{session_id}/messages`가
OpenAI 도구 호출 agent로 동작한다. 모델이 한 턴 안에서 아래 도구를 골라 호출한 뒤 답한다.

| 도구 | 사용자 발화 예 | 응답의 `action` |
|---|---|---|
| `search_products` | "안 까끌하고 얇은 여름 원피스 찾아줘", "조금 더 두꺼운 걸로" | `search_products` |
| `get_product_detail` | "1번 촉감 자세히 알려줘" | `get_product_detail` |
| `compare_products` | "1번이랑 2번 중에 뭐가 더 부드러워?" | `compare_products` |
| `add_to_cart` | "2번 장바구니에 담아줘" | `add_to_cart` |
| `view_cart` | "장바구니에 뭐 있어?" | `view_cart` |
| (도구 없음) | 인사, 쇼핑과 무관한 요청 | `respond` |

한 턴에 검색이 한 번이라도 있었으면 `action`은 `search_products`다.
OpenAI 호출이 실패하면 서버가 자동으로 기존 로컬 라우터로 답하고, 그때는 기존 값
(`respond_greeting`, `respond_out_of_scope`, `search_products`)이 온다.

## 2. 응답에 추가된 필드

```ts
interface AgentMessageResponse {
  // ... 기존 필드 전부 유지 (notion/24 7절)
  action:
    | "search_products" | "get_product_detail" | "compare_products"
    | "add_to_cart" | "view_cart" | "respond"
    | "respond_greeting" | "respond_out_of_scope";   // 뒤 두 값은 fallback 때만
  tool_calls?: Array<{ name: string; arguments: Record<string, unknown>; ok: boolean }>;
  cart_updated?: boolean;            // 이번 턴에 장바구니가 바뀌었으면 true
  referenced_product_ids?: string[]; // 이번 턴 답변이 가리킨 상품
  unsupported_concepts?: string[];   // "비침"처럼 반영하지 못한 조건
  routing: { tool: string; source: "openai_tool_loop" | "local_intent_model" | string; confidence: number | null };
  provenance: {
    // ... 기존 필드
    agent_mode?: "openai_tool_loop";  // 없으면 로컬 라우터 fallback 응답
    llm_requests?: number;
  };
}
```

`?` 필드는 fallback 응답에는 없다. 없을 때 기본값(빈 배열, `false`)으로 처리한다.

## 3. 화면 처리 규칙

- `action === "search_products"`일 때만 상품 grid를 `products`로 교체한다. 순서를 바꾸지 않는다.
- 그 외 action은 `products = []`다. **기존 grid를 유지**하고 채팅 답변만 추가한다.
  답변의 "1번, 2번"은 직전 검색 grid의 순서와 같다.
- `cart_updated === true`면 `GET /agent/v1/cart`로 장바구니 배지를 갱신한다.
  서버가 이미 `cart_add` event를 기록했으니 프론트에서 다시 보내지 않는다.
- `unsupported_concepts`가 있으면 "이 조건은 반영하지 못했어요" 안내를 붙여도 된다(답변에도 이미 포함된다).
- `message`는 화면낭독기용 평문이다. 마크다운으로 해석하지 않는다.

## 4. 응답 시간과 오류

- 실측(gpt-5.4-mini): 한 턴 **중앙값 약 3.5초, 최대 약 5~6초**. 검색 턴이 가장 길다.
  로딩 상태를 보여주고, 전송 중 중복 submit을 막는다. fetch timeout은 **40초 이상**으로 둔다.
- OpenAI 장애 시에도 서버가 로컬 라우터로 200을 돌려준다. 이 경우 500이 아니다.

## 5. 이미지

- 상품 응답의 `image_url`(`/images/{id}.jpg`)은 이미지 캐시가 있는 서버에서만 200이다.
  예비 서버에는 전체 이미지가 없어 **404**가 온다(이전에는 500).
- 두 서버에서 같게 보이려면 `remote_image_url`(Amazon CDN)을 우선 쓰고,
  실패하면 `image_url`로 대체하는 것을 권장한다.

## 6. 인증 (다른 origin에서 붙는 경우)

cookie는 `SameSite=Strict`라 다른 도메인의 프론트에서는 동작하지 않는다.
로그인·회원가입 응답의 `access_token`을 저장해 모든 요청에
`Authorization: Bearer {access_token}`을 붙인다. 서버의 `SHOPPING_AGENT_CORS_ORIGIN`에
프론트 origin이 등록돼 있어야 한다.
