#!/usr/bin/env bash
# Waits for the Qwen labelling process to finish, then runs the remaining
# stages. Exactly one Discord notification is sent, by 07_run_pipeline.py.
#
# The webhook is read from a 0600 file so it never appears in `ps` output.
set -u

EXPERIMENT_DIR="/home/user/onsesang/material_span_grounding/experiments/21_fabricvst_external"
SECRET_FILE="${EXPERIMENT_DIR}/.discord_webhook"
PYTHON="/home/user/onsesang/miniconda3/envs/texture/bin/python"
LABEL_PID="${1:?usage: run_after_labeling.sh <qwen_pid>}"

export HF_HOME="/home/user/onsesang/.cache/huggingface"
if [ -r "$SECRET_FILE" ]; then
  DISCORD_WEBHOOK_URL="$(cat "$SECRET_FILE")"
  export DISCORD_WEBHOOK_URL
fi

echo "waiting for labelling pid ${LABEL_PID} ..."
while kill -0 "$LABEL_PID" 2>/dev/null; do
  sleep 60
done
echo "labelling process ended at $(date -Is)"

# Resume any reviews the labelling run left behind before moving on.
"$PYTHON" -u "${EXPERIMENT_DIR}/scripts/03_qwen_pseudolabel.py" --pool selected --batch-size 96 \
  >> "${EXPERIMENT_DIR}/logs_qwen_pseudolabel.log" 2>&1

exec "$PYTHON" -u "${EXPERIMENT_DIR}/scripts/07_run_pipeline.py"
