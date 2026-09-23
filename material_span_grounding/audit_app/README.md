# Material Span Human Audit App

Qwen 2차 의미 검증 결과를 상품 원본 이미지와 함께 사람이 검수하는 웹 앱이다.
원본 검수 CSV는 수정하지 않으며 모든 판단을 별도 JSON과 live CSV에 저장한다.

## 실행

```bash
cd /home/user/onsesang/material_span_grounding
python audit_app/build_manifest.py
python -m audit_app.server --host 127.0.0.1 --port 8765
```

브라우저에서 `http://localhost:8765`로 접속한다.

현재 systemd 서비스 두 개는 `audit_app/data/vllm_dense_500_200_a`와
`audit_app/data/vllm_dense_500_200_b`를 사용한다. 각 표본은 100 span이며 서로 겹치지
않는다. 표본은 review-complete이므로 선택된 리뷰의
sibling span이 일부만 잘려 들어가지 않는다.

## 조작

- `←` 또는 `↑`: 저장 없이 이전 항목
- `→` 또는 `↓`: 현재 항목을 Good으로 저장하고 다음 항목
- `Good & Next`: 오른쪽 방향키와 동일
- `G`: Good — 추출 span을 유효한 소재 evidence로 승인
- `B`: Bad — 소재 evidence가 아니라고 기각
- `E`: Edit — claim, scope, polarity, 시각 관찰 가능성 등을 수정
- `Add Missing Span`: 전체 리뷰에서 Qwen이 놓친 exact quote와 구조화 metadata 추가
- `Mark full review checked`: 해당 리뷰를 끝까지 읽고 누락 검사를 완료했음을 명시
- `ALL EXTRACTED SPANS IN THIS REVIEW`: 같은 리뷰에서 이미 수집된 모든 span과 판정 상태
- `New V2` 필터: surface/use 또는 behavior/care lens에서 새로 발견한 span만 보기
- 상품 이미지 클릭: 원본 해상도 확대 보기
- Reset: 현재 사람 판단 삭제
- Judgments CSV: 기존 span 판정 다운로드
- Missing CSV: 사람이 추가한 누락 span 다운로드
- Recall CSV: full-review 확인 상태 다운로드

버튼은 Qwen과의 일치 여부가 아니라 사람의 최종 유효성 판정을 뜻한다. 따라서 Qwen
Reject에 동의하면 `Bad`, Qwen Reject를 뒤집어 유효하다고 판단하면 `Good`을 누른 뒤
Edit 창에서 구조화 필드를 입력한다.

누락 span은 기존 extracted span을 대체하지 않는다. 예를 들어 수축 span이 맞지만 같은
리뷰의 두께 표현이 누락됐다면 수축은 Good으로 유지하고 두께 문장을 별도 span으로
추가한다. Full Review 문장을 드래그한 뒤 `Add Missing Span`을 누르면 exact quote 입력에
선택 문장을 사용할 수 있다.

v2에서는 같은 리뷰의 span이 source CSV에서 연속 배치되고 화면의 sibling 목록에도 모두
표시된다. 현재 span만 보고 다른 소재 표현을 누락으로 판단하지 말고 sibling 목록을 먼저
확인한다. `Extraction` metadata는 `v1`, `surface_use`, `behavior_care` 출처를 표시한다.

## 저장 위치

현재 활성 vLLM dense-500 분할 세트:

- A: `audit_app/data/vllm_dense_500_200_a/` — Tailscale `http://100.96.162.32:8765`
- B: `audit_app/data/vllm_dense_500_200_b/` — Tailscale `http://100.96.162.32:8766`

아래 경로는 기본 v1 실행 시 사용하는 위치다.

- 원자적 저장 원본: `audit_app/data/annotations.json`
- 자동 생성 CSV: `audit_app/data/human_semantic_audit_live.csv`
- 누락/recall 원자적 저장: `audit_app/data/missing_spans.json`
- 누락 span CSV: `audit_app/data/human_missing_spans_live.csv`
- 리뷰 확인 CSV: `audit_app/data/human_review_recall_checks_live.csv`
- 자동 품질 지표: `experiments/03_human_semantic_audit/results/metrics.json`
- 원본 입력 CSV: `experiments/02_semantic_verification/human_semantic_audit.csv` (읽기 전용)

Annotator 값은 필수이며 브라우저의 local storage에 기억된다. 저장 API는 요청마다
JSON을 교체 저장한 후 live CSV를 다시 생성하므로 서버가 중간에 종료돼도 이미 저장된
결과는 유지된다.

이전 항목으로 돌아가 `Bad`나 `Edit`을 저장하면 같은 `span_id`의 기존 Good 결과를
원자적으로 덮어쓴다. 저장 후 자동 이동이 켜져 있으면 수정 결과 저장 후 다음 항목으로
돌아간다.

사람 판단이 저장될 때마다 `/api/quality`와 품질 보고서도 자동 갱신된다. 라벨 50개,
Qwen 통과 30개, Qwen 기각 15개가 모이기 전에는 모델 변경을 시작하지 않는다.

Observed span recall은 `accepted extracted / (accepted extracted + human-added
missing)`으로 계산한다. 단, `Full Review Checked`이며 그 리뷰의 기존 extracted 후보를
모두 판정한 리뷰만 포함한다. 현재 표본은 추출 span이 1개 이상인 리뷰로 만들어졌으므로
이 값은 전체 코퍼스 recall이 아니라 표본 내 진단값이다.

## 백그라운드 운영

```bash
./audit_app/start.sh
./audit_app/status.sh
./audit_app/stop.sh
```

배포 환경에서는 `material-audit.service`와 `material-audit-watch.service` 두 개의
systemd user service를 사용한다. 둘 다 비정상 종료 시 자동 재시작되며 Codex 실행
세션과 독립적으로 유지된다. 로그는 다음 명령으로 확인한다.

```bash
journalctl --user -u material-audit.service -u material-audit-watch.service -f
```

기본값은 안전하게 `127.0.0.1:8765`에만 바인딩한다. 원격 개발 환경에서는
8765 포트를 로컬로 포워딩한 뒤 브라우저에서 접속한다. 다른 호스트에 공개할 때는
인증과 HTTPS가 있는 reverse proxy 뒤에 두는 것을 권장한다.
