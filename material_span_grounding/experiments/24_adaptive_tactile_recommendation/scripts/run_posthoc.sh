#!/usr/bin/env bash
set -u
EXP="/home/user/onsesang/material_span_grounding/experiments/24_adaptive_tactile_recommendation"
PY="/home/user/onsesang/miniconda3/envs/texture/bin/python"
while [ "$(ls $EXP/cache/candidates__*.npz 2>/dev/null | wc -l)" -lt 3 ]; do
  echo "$(date -Is) waiting for candidate splits ($(ls $EXP/cache/candidates__*.npz 2>/dev/null | wc -l)/3)"
  sleep 30
done
echo "$(date -Is) all candidate splits ready; running R1/R1b/R2/R7 on CPU"
"$PY" -u "$EXP/scripts/05_rerank.py" --device cpu > "$EXP/logs/05_rerank.log" 2>&1
status=$?
echo "$(date -Is) 05_rerank exit ${status}"
if [ $status -eq 0 ]; then
  "$PY" -u "$EXP/scripts/06_analysis.py" > "$EXP/logs/06_analysis.log" 2>&1
  echo "$(date -Is) 06_analysis exit $?"
fi
