#!/usr/bin/env bash
# Waits for the Exp24 post-training chain, then regenerates the integrated report.
set -u
ROOT="/home/user/onsesang/material_span_grounding"
PY="/home/user/onsesang/miniconda3/envs/texture/bin/python"
while pgrep -f "run_post_training.sh|run_training_queue.sh|run_vlm_when_free.sh" >/dev/null 2>&1; do
  echo "$(date -Is) waiting for the GPU pipeline"
  sleep 300
done
echo "$(date -Is) pipeline finished; regenerating the integrated report"
"$PY" -u "$ROOT/scripts/make_final_report_22_24.py"
echo "$(date -Is) finalize done"
