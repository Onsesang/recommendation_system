# Personalized Shopping Agent

기존 `recommendation_api`의 catalog/design/tactile 기능을 도구로 사용하고 로그인, 대화
세션, 행동 이벤트, 자동 취향 기억, 개인화 정렬, 장바구니를 제공하는 독립 애플리케이션이다.

## 버전

- 코드: `shopping_agent/v1/`
- Public API prefix: `/agent/v1`
- 현재 버전: `shopping_agent/CURRENT_VERSION`
- 촉감 모델은 provider 계약 뒤에 있어 Agent API와 별도로 교체할 수 있다.

## 설정

실제 키를 commit하지 않는다. `shopping_agent/.env`의 빈 값에 사용할 provider 키를 넣는다.

```dotenv
SHOPPING_AGENT_LLM_PROVIDER=openai
OPENAI_API_KEY=...
OPENAI_MODEL=gpt-5.6
```

또는:

```dotenv
SHOPPING_AGENT_LLM_PROVIDER=gemini
GEMINI_API_KEY=...
GEMINI_MODEL=gemini-3.7-flash
```

키가 없거나 provider가 `deterministic`이면 외부 호출 없이 근거 기반 fallback 응답을
사용한다. `.env`는 `.gitignore`에 포함된다.

## 실행

```bash
/home/user/onsesang/miniconda3/envs/texture/bin/python -m shopping_agent.v1.server
```

지속 실행은 아래 script를 사용한다.

```bash
shopping_agent/start.sh
shopping_agent/status.sh
shopping_agent/stop.sh
```

`systemd --user`를 사용할 수 있는 환경에서는 `start.sh`가
`material-shopping-agent-v1.service`로 실행해 터미널이 닫혀도 유지한다. 로그는
`journalctl --user -u material-shopping-agent-v1.service -n 100 --no-pager`로 확인한다.

- Agent UI: `http://127.0.0.1:8878/agent-demo`
- Health: `http://127.0.0.1:8878/agent/v1/health`
- API summary: `http://127.0.0.1:8878/agent/v1/openapi.json`

## 범위

- 회원가입·로그인·로그아웃
- 사용자별 agent session과 대화 기록
- 모델 function calling 기반 인사·비쇼핑·쇼핑 요청 라우팅
- 채팅에서 category-scoped 취향 자동 저장
- 클릭·체류·찜·장바구니 이벤트
- 기존 review-grounded tactile/design 검색 기반 개인화 정렬
- 장바구니 추가·삭제
- 구매 버튼은 비활성화되며 주문·결제 API는 제공하지 않음
- 모든 추천에 score breakdown, 모델·도구 provenance, trace ID 포함

## 대화 도구 라우팅

`shopping_agent/v1/agent_tools.py`가 `respond_greeting`,
`respond_out_of_scope`, `search_products` 함수 도구와 호출 정책을 정의한다. OpenAI와
Gemini는 function calling으로 하나를 선택하고, API 키가 없거나 원격 호출이 실패하면
`configs/v1.json`의 학습 예시로 만든 로컬 문자 n-gram 분류기가 같은 도구를 선택한다.
사용자 문장을 직접 비교하는 조건문으로 라우팅하지 않는다.

## 예비 서버(RTX 3060) 동기화

A100에서 코드를 고친 뒤 한 번 실행한다. 코드 전송 → (선택) 원격 테스트 → 서비스 재시작 →
health 확인 → 남은 차이 0 확인 순서로 진행하고, 원격 테스트가 실패하면 재시작하지 않는다.

```bash
./shopping_agent/sync_backup.sh --dry-run   # 바뀔 파일만 확인
./shopping_agent/sync_backup.sh --test      # 권장: 테스트 통과 시에만 재시작
./shopping_agent/sync_backup.sh --data      # 런타임 데이터(configs/backup_data_files.txt)도 전송
./shopping_agent/sync_backup.sh --env       # .env(API 키)도 전송. 예비 서버 고유 값은 덮어씀
```

사용자 DB(`shopping_agent/data/*.sqlite3`)는 이 스크립트가 옮기지 않는다.

## OpenAI 도구 호출 agent

`SHOPPING_AGENT_LLM_PROVIDER=openai`이고 `configs/v1.json`의 `tool_agent.enabled`가 true이면
메시지 턴을 `v1/tool_agent.py`의 Responses API 도구 호출 루프가 처리한다. 도구는
`search_products`, `get_product_detail`, `compare_products`, `add_to_cart`,
`remove_from_cart`, `view_cart`이고,
검색 순위·촉감 점수·장바구니는 모두 기존 서비스가 계산한다. 원격 호출이 실패하면 로컬
라우터 파이프라인으로 자동 전환한다. 장바구니는 대화에서 이미 보여준 상품만 담을 수 있다.

모델은 `gpt-5.4-mini`로 확정했다(2026-09-26, mini·nano 비교와 사람 검수 결과). 기본 모델 요청이 실패하면
(HTTP 오류, timeout, 빈 응답) 그 요청만 `OPENAI_FALLBACK_MODEL`(기본 `gpt-5.4-nano`)로 다시 보내고, 그 턴의
나머지도 대체 모델로 처리한다. 둘 다 실패하면 로컬 라우터가 답한다. 응답의 `provenance.llm_model`과
`llm_model_fallback_used`에 실제로 답한 모델이 기록된다.

실제 API로 시연 시나리오를 평가한다. 시나리오는 `evaluation/demo_scenarios.json`에 있고
(작성법: `evaluation/SCENARIOS.md`), 도구 선택·구조화 조건·지칭·장바구니 부작용·답변 규칙을
자동 판정한 뒤 사람이 판정할 검수표(`review.md`, `review.csv`)를 만든다.

```bash
python -m shopping_agent.evaluation.tool_agent_scenarios --check
python -m shopping_agent.evaluation.tool_agent_scenarios \
    --models gpt-5.4-mini gpt-5.4-nano --reasoning-efforts low --repeats 2
```

프론트엔드 변경 사항은 `notion/25_FRONTEND_AGENT_TOOL_LOOP_CHANGES.md`에 있다.

## LangSmith 준비

모든 agent run은 `trace_id`, 입력, tool call, 모델 버전, 출력 요약을 로컬 JSONL trace로
남길 수 있는 추상화 뒤에 있다. `LANGSMITH_*` 값은 미래 exporter용 설정 자리이며, v1은
원격 전송을 수행하지 않는다. 추후 LangSmith SDK exporter를 붙이면 같은 run 경계를
전송할 수 있다. API와 추천 로직은 tracing backend에 의존하지 않는다.
