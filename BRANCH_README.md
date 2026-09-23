# material_span_grounding

`material_span_grounding/` 의 **코드와 문서(노션 포함)** 만 담은 브랜치입니다.
학습된 모델 weight는 GitHub Releases에 있고, `checkpoints/` 의 스크립트로 복원합니다.

## 담긴 것
- 소스 코드 `*.py *.sh *.js *.yaml *.html *.css` 등
- 문서 `*.md` — 루트 핸드오프 문서, `docs/tactile/`, `notion/` (노션 export 26개)
- 설정 `configs/*.json`, `prompts/*.txt`
- 체크포인트 매니페스트 / sha256 / 복원 스크립트 (`checkpoints/`)

## 담기지 않은 것
- 데이터: `*.jpg`(81 GB) `*.npz` `*.parquet` `*.jsonl` `*.csv` 등 — 용량상 제외
- 모델 weight `*.pt` — GitHub Releases 참조 (`./checkpoints/fetch_checkpoints.sh`)
- 벤더 코드 `experiments/16_strong_recommender_tactile/vendor/` (SMORE, transformer_benchmark)
  — 자체 `.git` 을 가진 서드파티라 별도로 clone 필요
- 비밀 파일 `.env`, `.discord_webhook`

## 체크포인트 받기
```bash
./checkpoints/fetch_checkpoints.sh                  # 전체
./checkpoints/fetch_checkpoints.sh 24_adaptive_tactile_recommendation
```
