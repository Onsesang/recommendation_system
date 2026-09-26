# 쇼핑 에이전트 API: 프론트 연동 전 남은 일

> 작성일: 2026-09-26
> 기준 코드: GitHub `Onsesang/recommendation_system` 브랜치 `ai_agent` (커밋 `74cb390`)
> 관련 문서: `notion/24_FRONTEND_SHOPPING_AGENT_API_V1.md`(API 명세), `notion/25_FRONTEND_AGENT_TOOL_LOOP_CHANGES.md`(도구 호출 변경)

## 0. 진행 상황 (2026-09-26 갱신)

메인 서버를 RTX 3060으로 정함. 명세서 v1.1은 `notion/27_API_SPEC_V1_1.html`(PDF 동봉).

| 항목 | 상태 |
|---|---|
| A2 CORS 여러 origin | ✅ `SHOPPING_AGENT_CORS_ORIGINS`, Vercel·localhost:3000 등록 |
| A3 인증 방식 | ✅ 명세 v1.1에 Bearer 전용 명시 |
| A4 이미지 규칙 | ✅ 명세 v1.1에 `remote_image_url` 우선 명시 |
| A5 명세 최종본 | ✅ v1.1 (Base URL 포함) |
| A6 rate limit | ✅ 가입 5회/시간, 로그인 10회/10분(IP), 메시지 20회/분·300회/일(사용자), 429 |
| 공개 주소 실사용 확인 | ✅ 임시 Quick Tunnel로 Vercel 페이지에서 가입~빼기·이미지·CORS 차단 확인 후 터널 닫음 |
| B7 테스트 계정 | ✅ 6개 삭제 (DB 백업 `data/agent_v1.sqlite3.bak-20260926`) |
| B5 서버 전환 | ⚠️ 동기화 없음. 명세에 "전환 시 재로그인·새 세션"으로 명시 |
| A1 고정 HTTPS 주소 | ✅ Tailscale Funnel `https://onsesang-pc-server.tail065d88.ts.net`. 외부 사용자 조건(공인 IP)에서 Vercel 페이지 호출·rate limit IP 구분 확인 |
| B1 FastAPI | ❌ 결정 필요 |
| 모델 확정 | ✅ `gpt-5.4-mini`, 오류 시 요청 단위로 `gpt-5.4-nano` 대체 → 둘 다 실패 시 로컬 라우터 |

## 1. 지금 상태

| 항목 | 상태 |
|---|---|
| Agent | OpenAI `gpt-5.4-mini` 도구 호출(검색·상세·비교·담기·빼기·장바구니 조회). Gemini 미사용 |
| 시연 질의 48턴 자동 판정 | 96/96 통과 (48턴 × 2회), 응답 시간 중앙값 3.0초, p90 4.6초 |
| 추천 검수(사람) | 상위 5개 정확도 85% (mini). 옷 종류가 다른 상품 제외 후 "안 맞음" 11개 → 0개 |
| 답변 말투 | 촉감 수치·"높음/낮음" 제거, 자연어 표현으로 변경 |
| 테스트 | shopping_agent 70개, recommendation_api 67개 통과 |
| 서버 | 3060 예비 서버에서 `shopping-agent.service` 실행 중 (`127.0.0.1:8878`, 외부 비공개) |
| 프론트 | Vercel `onsesang-front.vercel.app`. 로그인·회원가입 화면만 있고 API 호출 없음. UI 수정 후 연동 예정 |

## 2. 남은 일

### A. 배포 전 반드시 필요 (없으면 프론트가 연결할 수 없음)

| # | 할 일 | 현재 | 해야 할 것 |
|---|---|---|---|
| A1 | **고정 HTTPS 주소** | 공개 주소 없음. 이전 Quick Tunnel 주소는 재시작마다 바뀌고 지금은 꺼져 있음 | Cloudflare 계정·도메인으로 named tunnel 또는 다른 고정 주소. Vercel은 HTTPS라 API도 HTTPS여야 함(mixed content). **계정 소유자 결정 필요** |
| A2 | **CORS** | origin 1개만 허용(`SHOPPING_AGENT_CORS_ORIGIN`), 값은 옛 trycloudflare 주소 | 여러 origin 허용으로 코드 수정 + `https://onsesang-front.vercel.app`, 로컬 개발 주소 등록 |
| A3 | **인증 방식 확정** | 쿠키 `SameSite=Strict` + Bearer 토큰 둘 다 발급 | 도메인이 다르므로 쿠키는 전달되지 않음. 프론트는 **Bearer 토큰**(`Authorization` 헤더)만 쓰도록 명세에 못 박기. 토큰 저장 위치(메모리/스토리지)는 프론트와 합의 |
| A4 | **상품 이미지** | 이 서버에는 이미지 캐시가 없어 `/images/{id}.jpg`가 404 | 프론트는 `remote_image_url`(Amazon CDN)을 쓰도록 명세에 명시. 또는 서버에 이미지 동기화 |
| A5 | **API 명세 최종본** | `notion/24`(기본) + `notion/25`(도구 호출 변경)로 나뉘어 있음. 24의 Base URL은 `127.0.0.1` | 둘을 합친 최종본: 고정 Base URL, Bearer 인증, `action` 값 전체(`remove_from_cart` 포함), 이미지 규칙, 에러 형식, 응답 시간(3~5초, 최대 약 10초) 안내 |
| A6 | **회원가입·로그인 보호** | rate limit 없음, 누구나 가입 가능 | 회원가입·로그인 rate limit(IP당). 공개 기간에 OpenAI 비용이 새지 않도록 메시지 API에도 사용자당 한도 권장 |

### B. 배포 전 권장 (시연 품질·안정성)

| # | 할 일 | 내용 |
|---|---|---|
| B1 | FastAPI 전환 여부 결정 | 계획상 FastAPI로 배포. 명세를 먼저 확정하고 같은 경로·응답 형식으로 옮기면 프론트 영향 없음. **전환 후에 공개할지, 지금 서버로 먼저 공개할지 결정 필요** (FastAPI 미설치 상태) |
| B2 | 검색 순위 | 색상 조건 약함("청바지"에 흰 바지, "남색"에 다른 색), 촉감 반영 약함("하늘하늘한 치마"에 달라붙는 치마), 이미지 없는 상품 섞임 |
| B3 | 답변 안정성 | 드물게 다른 언어 단어 섞임(반복 실행 95턴 중 2턴), 직전 턴 반복(약 1/5 빈도의 특정 흐름). 서버에서 감지해 재생성하는 보호 장치 권장 |
| B4 | 취급 외 요청 | "운동화 추천해줘"에 모델이 옷 종류 없이 검색하면 실제 신발이 나올 수 있음 |
| B5 | 장애 대비 | 메인 → 예비(3060) DB 동기화 없음, 전환 스크립트 없음. 예비로 넘어가면 로그인·장바구니가 사라짐 |
| B6 | 운영 설정 정리 | `.env`의 `COOKIE_SECURE=true`라 로컬 http 데모(`/agent-demo`)에서 로그인 유지 안 됨. 로컬 확인 시 `false`로 두고, 공개 서버는 `true` 유지 |
| B7 | 테스트 계정 정리 | 운영 DB에 `smoke_`·`eval_` 계정 5개 남아 있음 |

### C. 프론트 담당자와 합의할 것

- 프론트의 현재 화면 구성과 API의 차이 목록 (프론트 UI 수정 범위)
- 대화 목록 화면 필요 여부: 지금 API는 세션 생성·조회만 있고 **세션 목록 API가 없음**
- 상품 grid 규칙: `action === "search_products"`일 때만 `products`(30개, 순위순)로 교체, 그 외에는 유지
- 장바구니 배지: `cart_updated === true`면 `GET /agent/v1/cart`로 갱신 (서버가 이벤트를 이미 기록)
- 답변 `message`는 화면낭독기용 평문. 마크다운으로 해석하지 않음
- 응답 대기 표시: 검색 턴 3~5초, 최대 약 10초. 타임아웃은 30초 이상 권장
- 장애 시 전환 방식 (B5와 연결)

## 3. 권장 순서

1. **UI 직접 확인**: 로컬 `/agent-demo`로 시연 질의를 손으로 확인 (B6 설정 필요)
2. **결정**: 고정 주소(A1)와 FastAPI 전환 시점(B1)
3. **서버 수정**: CORS 다중 origin(A2), rate limit(A6), 필요 시 FastAPI 전환
4. **명세 최종본**(A3·A4·A5 반영) → 프론트 담당자와 C 항목 합의
5. **배포**: 고정 주소 공개, 프론트 실제 화면에서 체감 속도·장애 전환 리허설
6. 병행: 검색 순위(B2)·답변 안정성(B3) 개선

## 4. 확인 방법

```bash
# 시연 질의 자동 판정 (48턴)
python -m shopping_agent.evaluation.tool_agent_scenarios --models gpt-5.4-mini --repeats 2
# 사람 검수 UI
python -m shopping_agent.evaluation.review_app shopping_agent/evaluation/results/<실행>/results.json
# 서버 상태
curl http://127.0.0.1:8878/agent/v1/health
```
