# 소재 Span 사람 검수 웹 앱

## 한 줄 요약

Qwen 2차 의미 검증 표본 139개를 실제 상품 이미지와 원문 리뷰를 함께 보면서
`Good / Bad / Edit`으로 검수하고, Qwen이 놓친 소재 표현도 `Add Missing Span`으로
추가하여 결과를 JSON과 CSV에 즉시 저장하는 웹 앱을 구축했다.

## 검수 범위

| 항목 | 값 |
|---|---:|
| 전체 검수 span | 139 |
| 통과 span 층화 표본 | 100 |
| 기각 span 전체 | 39 |
| 고유 상품 | 119 |
| 실제 상품 이미지가 있는 항목 | 138 |
| 만료된 이미지 소스 | 1 |
| 1,000px 이상 실제 이미지 | 115 / 118 상품 |
| 실제 이미지 중앙 해상도 | 1.92 MP |

만료된 1개 ASIN(`B000HSTWY0`)은 메타데이터에 기록된 두 Amazon 이미지
호스트 모두 HTTP 404였다. 잘못된 대체 이미지를 넣지 않고 `SOURCE UNAVAILABLE`로
명확히 표시했다.

## 화면 구성

- 왼쪽: 상품 원본 이미지, ASIN, 상품명
- 오른쪽: exact span, span이 강조된 전체 리뷰, Qwen 판정과 구조화 metadata
- 누락 검수: 원문 선택, 누락 span 추가·수정·삭제, Full Review Checked 상태
- 이미지 클릭: 원본 크기 확대 보기
- 상단: 전체 진행률, Annotator, CSV 다운로드
- 필터: All, Unreviewed, Good, Bad, Edited
- Item 번호 직접 이동 및 저장 후 자동 이동

## 조작

| 기능 | 버튼 | 키보드 |
|---|---|---|
| 이전 항목 | Previous | `←` 또는 `↑` |
| 다음 항목 | Next | `→` 또는 `↓` |
| 유효 소재 span 승인 | Good | `G` |
| 소재 span 기각 | Bad | `B` |
| claim·scope·극성·시각성 수정 | Edit | `E` |
| Qwen 누락 span 추가 | Add Missing Span | 버튼 |
| 리뷰 전체 누락 검사 완료 | Mark full review checked | 버튼 |
| 현재 판단 취소 | Reset | 버튼 |

텍스트 입력이나 Edit dialog가 열린 동안에는 단축키가 실행되지 않아 실수로 다른
항목을 저장하는 것을 막는다.

## 저장 설계

원본 사람 검수 CSV는 읽기 전용으로 유지한다. 각 판단은 다음 순서로 저장된다.

1. 백엔드 enum 및 필수 필드 검증
2. 임시 JSON 생성 및 `fsync`
3. atomic replace로 annotation 원본 교체
4. 139개 전체 행을 유지한 live CSV 자동 재생성

누락 span은 기존 annotation과 분리해 저장한다. 서버는 입력 quote가 Full Review의 exact
substring인지 검사하며, 기존에 이미 추출된 quote나 같은 리뷰에 이미 등록된 누락 quote는
중복 추가하지 못하게 한다. 같은 리뷰에서 두께·단단함처럼 서로 다른 표현은 여러 개의
독립 span으로 저장할 수 있다.

저장 파일:

- `audit_app/data/annotations.json`: action과 수정 시각을 포함한 원본
- `audit_app/data/human_semantic_audit_live.csv`: 기존 분석 코드와 호환되는 CSV
- `audit_app/data/missing_spans.json`: 누락 span과 리뷰 확인 상태의 원자적 저장 원본
- `audit_app/data/human_missing_spans_live.csv`: 사람이 추가한 누락 span
- `audit_app/data/human_review_recall_checks_live.csv`: Full Review Checked 기록
- `experiments/02_semantic_verification/human_semantic_audit.csv`: 변경하지 않는 입력

## 백엔드 API

| Endpoint | 역할 |
|---|---|
| `GET /api/health` | 서버 및 진행 상태 |
| `GET /api/items` | 검수 항목과 현재 annotation |
| `GET /api/image/{asin}` | 경로 검증 후 원본 이미지 전송 |
| `POST /api/annotations/{span_id}` | Good·Bad·Edit 저장 |
| `DELETE /api/annotations/{span_id}` | 현재 판단 Reset |
| `GET /api/export` | live CSV 다운로드 |
| `POST /api/missing-spans` | 누락 span 추가 및 exact quote 검사 |
| `PUT /api/missing-spans/{id}` | 누락 span 수정 |
| `DELETE /api/missing-spans/{id}` | 누락 span 삭제 |
| `POST·DELETE /api/review-checks/{review_id}` | 리뷰 전체 확인 상태 설정·해제 |
| `GET /api/export-missing` | 누락 span CSV 다운로드 |
| `GET /api/export-recall-checks` | 리뷰 확인 CSV 다운로드 |

외부 패키지 설치 없이 Python 표준 라이브러리만 사용한다. ASIN과 span ID는 정규식으로
검증하고 요청 본문은 64 KiB로 제한했다.

## Recall 해석

Observed span recall은 다음과 같이 계산한다.

`사람이 승인한 기존 추출 span / (사람이 승인한 기존 추출 span + 사람이 추가한 누락 span)`

다만 `Full Review Checked`이며 그 리뷰에 속한 기존 extracted 후보가 전부 Good/Bad/Edit로
판정된 리뷰만 분모에 포함한다. 아직 검사를 하지 않은 리뷰를 “누락 없음”으로 간주하지
않기 위한 장치다. 추출 span이 전혀 없었던 리뷰는 현재 139개 표본 밖이므로 이 지표는
corpus-wide recall이 아니라 표본 내 observed recall이다.

## 검증 결과

- 기존 파이프라인·recall 지표 단위 테스트: 12개 통과
- 웹 앱·누락 저장 단위 테스트: 7개 통과
- manifest: 139개 ID 고유성 및 exact quote 포함 여부 통과
- 실제 HTTP: index, item API, 원본 JPEG, 누락 이미지 안내 응답 모두 200
- 실제 저장 왕복: POST → atomic JSON → live CSV → DELETE/Reset 통과
- 테스트 annotation 삭제 후 초기 진행 상태: 0 / 139

## 실행과 접속

```bash
cd /home/user/onsesang/material_span_grounding
./audit_app/start.sh
./audit_app/status.sh
```

기본 접속 주소는 `http://127.0.0.1:8765`다. 원격 서버를 사용하는 경우 8765 포트를
로컬 브라우저로 포워딩한다. 외부 인터넷에 직접 공개할 때는 로그인과 HTTPS가 있는
reverse proxy를 먼저 두어야 한다.

## 검수 후 다음 단계

139개 검수가 끝나면 live CSV로 Qwen 검증 precision, 잘못된 기각률, scope·극성·시각성
일치율을 계산한다. 오류 유형이 허용 범위면 동일 사용자 반복 제거로 진행하고, 그렇지
않으면 v1.1 프롬프트의 경계 사례를 보완해 재검증한다.
