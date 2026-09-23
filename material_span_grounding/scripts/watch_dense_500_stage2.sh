#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="/home/user/onsesang/material_span_grounding"
OUTPUT_ROOT="data/dense/v2"
ACTIVE_EXTRACTION_PID="${1:-}"
PYTHON="/home/user/onsesang/miniconda3/envs/texture/bin/python"
WEBHOOK_URL="${DISCORD_WEBHOOK_URL:?DISCORD_WEBHOOK_URL is required}"

cd "$PROJECT_ROOT"

notify() {
  local message="$1"
  local payload
  payload="$($PYTHON -c 'import json, sys; print(json.dumps({"content": sys.argv[1]}, ensure_ascii=False))' "$message")"
  curl --fail --silent --show-error --output /dev/null \
    -H "Content-Type: application/json" \
    --data "$payload" \
    "$WEBHOOK_URL"
}

notify_failure() {
  local exit_code=$?
  notify "[material_span_grounding] 2단계 실패: Dense 500 추출·검증 workflow가 종료 코드 ${exit_code}로 중단됐습니다. 로그: logs/dense_500_stage2.log" || true
  exit "$exit_code"
}
trap notify_failure ERR

if [[ -n "$ACTIVE_EXTRACTION_PID" ]]; then
  while kill -0 "$ACTIVE_EXTRACTION_PID" 2>/dev/null; do
    sleep 30
  done
fi

if ! "$PYTHON" -c 'import json; value=json.load(open("data/dense/v2/extraction_run.json")); assert value["status"] == "complete" and value["reviews"] == 4158' 2>/dev/null; then
  "$PYTHON" run.py recall-extract \
    --input data/dense/reviews_product_dense.jsonl \
    --output-root "$OUTPUT_ROOT" \
    --batch-size 6
fi

"$PYTHON" run.py recall-verify-prepare --output-root "$OUTPUT_ROOT"
"$PYTHON" run.py recall-verify --output-root "$OUTPUT_ROOT" --batch-size 8
"$PYTHON" -m material_span.dense_500_report --root "$OUTPUT_ROOT"

summary="$($PYTHON -c 'import json; m=json.load(open("experiments/09_dense_500_extraction/results/metrics.json")); e=m["extraction"]; v=m["verification"]; t=m["target_readiness"]; print("{} exact spans, {} accepted, {}/500 target products".format(e["union_exact_spans"], v["accepted"], t["products"]))')"
notify "[material_span_grounding] 2단계 완료: Dense 500의 4,158리뷰 Recall v2 추출 및 semantic verification을 마쳤습니다. ${summary}. 문서: notion/10_DENSE_500_EXTRACTION_RESULTS.md"
trap - ERR
