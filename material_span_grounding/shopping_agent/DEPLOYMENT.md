# Shopping Agent v1 — 배포 메모

> 2026-09-26 갱신: 메인 서버는 이 RTX 3060. 공개 주소는 **Tailscale Funnel** 고정 주소
> `https://onsesang-pc-server.tail065d88.ts.net` (→ `127.0.0.1:8878`). 아래 Quick Tunnel 내용은 이전 방식이다.
>
> ```bash
> tailscale funnel status                 # 공개 상태 확인
> tailscale funnel --bg 8878              # 켜기 (operator 설정이 되어 있어 sudo 불필요)
> tailscale funnel --https=443 off        # 끄기
> ```
> - Funnel은 실제 사용자 IP를 X-Forwarded-For로 넘기므로 rate limit이 사용자별로 동작한다.
> - tailnet에 접속한 기기에서는 이 주소가 100.x 내부 IP로 풀려, 크롬이 Vercel 사이트의 호출을
>   내부 네트워크 접근으로 보고 차단하거나 권한을 물을 수 있다. 외부 사용자와 같은 조건으로 보려면
>   Tailscale을 끈 기기에서 확인한다.

`/agent-demo`를 Cloudflare Quick Tunnel로 공개한 구성이다. 코드는 변경하지 않았고
설정 파일(`shopping_agent/.env`)과 tunnel 관리 script만 추가했다.

## 현재 구성

| 항목 | 값 |
| --- | --- |
| 공개 URL | `https://circuit-brand-agree-partition.trycloudflare.com/agent-demo` |
| 로컬 바인딩 | `127.0.0.1:8878` (외부에 직접 노출되지 않음) |
| 공개 경로 | Cloudflare Quick Tunnel → localhost |
| LLM provider | `deterministic` (외부 API 호출 없음, 로컬 n-gram router + 근거 기반 템플릿) |
| Catalog | **825,840 상품 (Amazon Fashion 2023 전체)**, Last2 이미지 예측 촉감 14종 |
| Catalog 모드 | `SHOPPING_AGENT_CATALOG=full` (`curated`로 되돌리면 465 리뷰 근거 catalog) |
| 프로세스 관리 | `systemd --user` unit 2개 |

## 서비스

```bash
shopping_agent/start.sh        # material-shopping-agent-v1.service
shopping_agent/status.sh
shopping_agent/stop.sh

shopping_agent/tunnel.sh start   # material-agent-tunnel.service
shopping_agent/tunnel.sh status
shopping_agent/tunnel.sh url     # 현재 공개 URL 출력
shopping_agent/tunnel.sh logs
shopping_agent/tunnel.sh stop
```

## URL이 바뀌었을 때

Quick Tunnel은 Cloudflare 계정 없이 쓰는 대신 hostname이 재시작마다 새로 발급된다.
tunnel을 재시작했다면 다음 순서로 맞춘다.

```bash
shopping_agent/tunnel.sh url
# 출력된 URL을 shopping_agent/.env 의 SHOPPING_AGENT_CORS_ORIGINS(쉼표 구분)에 추가
shopping_agent/stop.sh && shopping_agent/start.sh
```

고정 hostname이 필요하면 Cloudflare 계정에 도메인을 붙여 named tunnel
(`cloudflared tunnel create` + `route dns`)로 바꾼다.

## 보안 상태

지켜지는 것:

- 비밀번호는 PBKDF2-HMAC-SHA256, 310,000 iteration, 사용자별 16-byte salt로 저장된다.
- 세션 쿠키는 `HttpOnly; SameSite=Strict; Secure`다. `Secure`는
  `SHOPPING_AGENT_COOKIE_SECURE=true`로 켜져 있고, tunnel이 HTTPS를 종단하므로 유효하다.
- 결제·주문 API는 존재하지 않는다. 구매 버튼은 비활성 상태다.
- `.env`에 실제 API key가 없다. deterministic provider라 외부로 나가는 호출이 없다.

열려 있는 위험:

- URL을 아는 누구나 회원가입할 수 있다. 초대·허용 목록이 없다.
- rate limit이 없다. 로그인 시도 횟수 제한도 없다.
- 서버는 stdlib `ThreadingHTTPServer`다. 시연 트래픽 기준이며 부하 대응 장치가 없다.
- `shopping_agent/data/agent_v1.sqlite3`에 실제 사용자 이메일과 대화가 쌓인다.
  공개 상태에서 들어온 계정도 같은 DB에 저장된다.
- `SHOPPING_AGENT_COOKIE_SECURE=true`이므로 `http://127.0.0.1:8878`에서는 로그인
  쿠키가 저장되지 않는다. 로컬에서 테스트하려면 이 값을 `false`로 되돌리고 재시작한다.

시연이 끝나면 `shopping_agent/tunnel.sh stop`으로 공개 경로를 닫는 것을 권장한다.
agent 자체는 계속 켜두어도 localhost에서만 접근 가능하다.

## Catalog 모드

| | `curated` | `full` (현재) |
| --- | --- | --- |
| 상품 수 | 465 | 825,840 |
| 촉감 신호 | 리뷰 span 근거 384-d target | Last2 이미지 예측 확률 14종 |
| 근거 출처 | 실제 구매자 리뷰 | 상품 이미지 |
| 리뷰 근거 overlay | 전부 | 406개만 (`review_grounded_overlay`로 표시) |
| 표현 못 하는 개념 | 없음 | sheerness, breathability, linting, pilling |

`.env`의 `SHOPPING_AGENT_CATALOG`로 전환하고 재시작한다. 두 모드는 같은 DB를 쓰므로
계정·취향·장바구니는 유지되지만, 장바구니에 담긴 product_id가 상대 모드에 없으면
그 항목은 조회되지 않는다.

전체 모드의 촉감 확률은 **리뷰 근거가 아니라 이미지 예측**이다. 모든 응답의
`tactile_target_source`와 `score_breakdown.evidence_source`가 출처를 표시한다.

## 평가

```bash
python -m shopping_agent.evaluation.full_catalog_offline_eval
```

결과는 `shopping_agent/evaluation/full_catalog_v1.json`에 기록된다. 사람이 라벨링한
relevance set이 없으므로 정확도가 아니라 진단 지표다.

## 의존 관계 메모

- `shopping_agent`는 `recommendation_api`를 HTTP가 아니라 in-process import로 쓴다.
  따라서 8877 포트 서버가 떠 있지 않아도 agent는 단독으로 동작한다.
- 실행에는 `/home/user/onsesang/miniconda3/envs/texture/bin/python`을 절대 경로로 쓴다.
  현재 워크스테이션에서 `conda run -n texture python`은 base(3.14) python으로 잘못
  해석되므로 script 안에서 사용하지 않는다.
- 상품 이미지는 `/home/user/onsesang/texture_project/images_train`에서 서빙된다.
