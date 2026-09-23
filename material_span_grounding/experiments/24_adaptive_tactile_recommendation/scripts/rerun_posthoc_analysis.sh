#!/usr/bin/env bash
# 05_rerank.py was re-run after the union-padding fix, so the significance tables
# and plots derived from its ranks must be regenerated too.
set -u
EXP="/home/user/onsesang/material_span_grounding/experiments/24_adaptive_tactile_recommendation"
PY="/home/user/onsesang/miniconda3/envs/texture/bin/python"
while pgrep -f "05_rerank.py" >/dev/null 2>&1; do sleep 30; done
echo "$(date -Is) 05_rerank finished; regenerating analysis"
"$PY" -u "$EXP/scripts/06_analysis.py" > "$EXP/logs/06_analysis.log" 2>&1 && echo "$(date -Is) 06_analysis OK"
"$PY" -u "$EXP/scripts/07_plots.py"    > "$EXP/logs/07_plots.log" 2>&1 && echo "$(date -Is) 07_plots OK"
"$PY" -u "$EXP/scripts/09_report.py"   > "$EXP/logs/09_report.log" 2>&1 && echo "$(date -Is) 09_report OK"
echo "$(date -Is) post-hoc analysis refresh done"
