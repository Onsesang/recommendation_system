#!/usr/bin/env bash
# Qwen3-VL-32B is scored LAST, after Exp24's must-have training and ablation.
#
# Why the reorder: InternVL3.5-8B settled at ~1.7 img/s (vs Qwen3-VL-8B's 17), so a
# VLM stage can take hours.  The task's priority list puts Exp24's R0/R1/R2/R3/R5/R7
# and the tactile-source ablation in the must-have set, while the 32B is the
# preferred-but-substitutable member of the Qwen family (an 8B of the same family is
# already scored).  Running a multi-hour nice-to-have ahead of must-haves would risk
# the wrong things being unfinished.
set -u
E22="/home/user/onsesang/material_span_grounding/experiments/22_open_tactile_benchmark"
E23="/home/user/onsesang/material_span_grounding/experiments/23_tactile_conditioned_retrieval"
E24="/home/user/onsesang/material_span_grounding/experiments/24_adaptive_tactile_recommendation"
ROOT="/home/user/onsesang/material_span_grounding"
PY="/home/user/onsesang/miniconda3/envs/texture/bin/python"
export HF_HOME="/home/user/onsesang/.cache/huggingface"
export HF_HUB_OFFLINE=0
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True

while pgrep -f "run_training_queue.sh|run_post_training.sh|04_score_vlm.py|08_catalog_tactile.py" >/dev/null 2>&1; do
  echo "$(date -Is) waiting for must-have GPU work"
  sleep 300
done
echo "$(date -Is) must-have work complete; starting Qwen3-VL-32B"

DEADLINE=$(( $(date +%s) + 5*3600 ))
attempt=0
while :; do
  [ "$(date +%s)" -gt "$DEADLINE" ] && { echo "$(date -Is) 32B: deadline reached, skipping"; break; }
  FREE=$(nvidia-smi --query-gpu=memory.free --format=csv,noheader,nounits | head -1)
  if [ "${FREE:-0}" -ge 72000 ]; then QUANT=bf16; BATCH=8
  elif [ "${FREE:-0}" -ge 34000 ]; then QUANT=nf4;  BATCH=4
  else echo "$(date -Is) 32B: only ${FREE} MiB free, waiting"; sleep 180; continue; fi
  attempt=$((attempt+1))
  echo "$(date -Is) 32B: ${FREE} MiB free -> ${QUANT} batch ${BATCH} (attempt ${attempt})"
  "$PY" -u "$E22/scripts/04_score_vlm.py" --model qwen3vl_32b --batch-size "$BATCH" \
        --quantize "$QUANT" --max-side 448 >> "$E22/logs/04_qwen3vl_32b.log" 2>&1
  status=$?
  if [ $status -eq 0 ]; then
    echo "$(date -Is) 32B COMPLETE (${QUANT})"
    "$PY" -c "
import json
from pathlib import Path
p = Path('$E22/logs/vlm_precision_used.json')
d = json.loads(p.read_text()) if p.is_file() else {}
d['qwen3vl_32b'] = {'precision': '${QUANT}', 'batch_size': ${BATCH}}
p.write_text(json.dumps(d, indent=2))"
    break
  fi
  echo "$(date -Is) 32B: exited ${status}; cache kept, backing off"
  [ $attempt -ge 20 ] && { echo "$(date -Is) 32B: too many attempts, giving up"; break; }
  sleep 240
done

echo "$(date -Is) regenerating every report with whatever models completed"
"$PY" -u "$E22/scripts/05_metrics.py" > "$E22/logs/05_metrics_final2.log" 2>&1
"$PY" -u "$E22/scripts/06_plots.py"   > "$E22/logs/06_plots_final2.log" 2>&1
"$PY" -u "$E22/scripts/07_report.py"  > "$E22/logs/07_report_final2.log" 2>&1
"$PY" -u "$E23/scripts/01_run_retrieval.py" > "$E23/logs/01_final2.log" 2>&1
"$PY" -u "$E23/scripts/02_qualitative.py"   > "$E23/logs/02_final2.log" 2>&1
"$PY" -u "$E23/scripts/03_plots.py"         > "$E23/logs/03_final2.log" 2>&1
"$PY" -u "$E23/scripts/04_report.py"        > "$E23/logs/04_final2.log" 2>&1
"$PY" -u "$E24/scripts/09_report.py"        > "$E24/logs/09_report_final2.log" 2>&1
"$PY" -u "$ROOT/scripts/make_final_report_22_24.py" > "$ROOT/logs/final_report_final2.log" 2>&1
echo "$(date -Is) 32B stage and final regeneration finished"
