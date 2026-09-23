#!/usr/bin/env bash
# Scores each VLM as soon as the shared A100 has room, preferring BF16.
#
# Rules this encodes:
#  * never kill or deprioritise another user's job -- only take memory that is free;
#  * BF16 is the default precision (Step "GPU / memory management"); quantisation is
#    a fallback that must be recorded, so the precision actually used is written into
#    the output .npz and into logs/vlm_precision_used.json;
#  * 04_score_vlm.py caches every (image, attribute) pair, so an OOM costs nothing
#    but time -- the loop retries and work resumes.
#  * a model is never scored partly in BF16 and partly in NF4: the cache file name
#    carries the precision, so switching precision starts a clean cache.
set -u

EXP="/home/user/onsesang/material_span_grounding/experiments/22_open_tactile_benchmark"
PYTHON="/home/user/onsesang/miniconda3/envs/texture/bin/python"
export HF_HOME="/home/user/onsesang/.cache/huggingface"
export HF_HUB_OFFLINE=0
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True

free_mib() { nvidia-smi --query-gpu=memory.free --format=csv,noheader,nounits | head -1; }

# Courtesy gate.  Another user's LongBench run owns this GPU.  Sharing it was
# measured as net-negative for both sides and, worse, our 7 GiB allocation pushed
# their sibling process into a CUDA OOM that killed it at 90/200.  So we now stay
# completely off the device -- not merely under a memory cap -- until every foreign
# job has exited, then take the whole card in BF16.
OTHER_PIDS="83996 84693 80079"
wait_for_other_jobs() {
  while :; do
    alive=0
    for pid in $OTHER_PIDS; do
      kill -0 "$pid" 2>/dev/null && alive=$((alive+1))
    done
    if [ "$alive" -eq 0 ]; then
      echo "$(date -Is) foreign jobs finished; taking the GPU"
      return
    fi
    echo "$(date -Is) yielding: ${alive} foreign job(s) still running, $(free_mib) MiB free"
    sleep 120
  done
}
wait_for_other_jobs

# model : bf16_need : bf16_batch : nf4_need : nf4_batch
PLAN=(
  "qwen3vl_8b:26000:24:11000:4"
  "internvl3_5_8b:26000:24:11000:4"
  "qwen3vl_32b:72000:8:34000:2"
)

# Wait up to this long for a BF16-sized window before accepting the NF4 fallback.
BF16_PATIENCE=$(( 100 * 60 ))
DEADLINE=$(( $(date +%s) + 8*3600 ))

for entry in "${PLAN[@]}"; do
  IFS=: read -r MODEL BNEED BBATCH QNEED QBATCH <<<"$entry"
  echo "=== $MODEL: BF16 needs ${BNEED} MiB, NF4 fallback needs ${QNEED} MiB ==="
  started=$(date +%s)
  attempt=0
  while :; do
    now=$(date +%s)
    [ "$now" -gt "$DEADLINE" ] && { echo "$MODEL: global deadline reached, skipping"; break; }
    FREE=$(free_mib)
    QUANT=""; BATCH=""
    if [ "${FREE:-0}" -ge "$BNEED" ]; then
      QUANT=bf16; BATCH=$BBATCH
    elif [ $(( now - started )) -ge $BF16_PATIENCE ] && [ "${FREE:-0}" -ge "$QNEED" ]; then
      QUANT=nf4; BATCH=$QBATCH
      echo "$(date -Is) $MODEL: BF16 window did not appear within patience, falling back to NF4"
    else
      echo "$(date -Is) $MODEL: ${FREE} MiB free, waiting for a BF16-sized window"
      sleep 120; continue
    fi
    attempt=$((attempt+1))
    echo "$(date -Is) $MODEL: ${FREE} MiB free -> ${QUANT} batch ${BATCH} (attempt ${attempt})"
    "$PYTHON" -u "${EXP}/scripts/04_score_vlm.py" \
      --model "$MODEL" --batch-size "$BATCH" --quantize "$QUANT" --max-side 448 \
      >> "${EXP}/logs/04_${MODEL}.log" 2>&1
    status=$?
    if [ $status -eq 0 ]; then
      echo "$(date -Is) $MODEL: COMPLETE (${QUANT})"
      "$PYTHON" -c "
import json,sys
from pathlib import Path
p = Path('${EXP}/logs/vlm_precision_used.json')
d = json.loads(p.read_text()) if p.is_file() else {}
d['${MODEL}'] = {'precision': '${QUANT}', 'batch_size': ${BATCH}, 'free_mib_at_start': ${FREE}}
p.write_text(json.dumps(d, indent=2))
"
      break
    fi
    echo "$(date -Is) $MODEL: exited ${status}; cache kept, backing off"
    [ $attempt -ge 40 ] && { echo "$MODEL: too many attempts, moving on"; break; }
    sleep 180
  done
done
echo "$(date -Is) supervisor finished"
