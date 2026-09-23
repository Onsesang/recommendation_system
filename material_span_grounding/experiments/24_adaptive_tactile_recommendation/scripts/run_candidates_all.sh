#!/usr/bin/env bash
set -u
EXP="/home/user/onsesang/material_span_grounding/experiments/24_adaptive_tactile_recommendation"
PY="/home/user/onsesang/miniconda3/envs/texture/bin/python"
# CPU only: the shared A100 still belongs to another user's job.
for split in validation train test; do
  if [ -f "$EXP/cache/candidates__${split}.npz" ]; then
    echo "$(date -Is) $split: cached, skipping"; continue
  fi
  echo "$(date -Is) $split: generating"
  "$PY" -u "$EXP/scripts/04_candidates.py" --split "$split" --device cpu --batch 128 \
    > "$EXP/logs/04_candidates_${split}.log" 2>&1 || echo "$(date -Is) $split FAILED"
done
echo "$(date -Is) all candidate splits done"
