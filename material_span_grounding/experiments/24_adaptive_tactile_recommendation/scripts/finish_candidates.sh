#!/usr/bin/env bash
set -u
EXP="/home/user/onsesang/material_span_grounding/experiments/24_adaptive_tactile_recommendation"
# wait for whatever candidate run is currently in flight
while pgrep -f "04_candidates.py" >/dev/null 2>&1; do sleep 15; done
exec bash "$EXP/scripts/run_candidates_all.sh"
