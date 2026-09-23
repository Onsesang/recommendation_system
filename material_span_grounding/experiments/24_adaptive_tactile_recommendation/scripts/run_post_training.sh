#!/usr/bin/env bash
# Runs after the GPU training queue: evaluate trained backbones, run the tactile
# source ablation, regenerate plots and all three reports.
set -u
EXP="/home/user/onsesang/material_span_grounding/experiments/24_adaptive_tactile_recommendation"
E22="/home/user/onsesang/material_span_grounding/experiments/22_open_tactile_benchmark"
E23="/home/user/onsesang/material_span_grounding/experiments/23_tactile_conditioned_retrieval"
PY="/home/user/onsesang/miniconda3/envs/texture/bin/python"
export HF_HOME="/home/user/onsesang/.cache/huggingface"
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True

# wait for the training queue script itself to exit
while pgrep -f "run_training_queue.sh" >/dev/null 2>&1; do
  echo "$(date -Is) waiting for the training queue"
  sleep 180
done
echo "$(date -Is) training queue finished"

echo "$(date -Is) evaluating trained checkpoints"
"$PY" -u "$EXP/scripts/10_evaluate_trained.py" > "$EXP/logs/10_evaluate_trained.log" 2>&1 \
  || echo "$(date -Is) 10_evaluate_trained FAILED"

echo "$(date -Is) tactile source ablation"
"$PY" -u "$EXP/scripts/11_ablation.py" > "$EXP/logs/11_ablation.log" 2>&1 \
  || echo "$(date -Is) 11_ablation FAILED"

echo "$(date -Is) refreshing Exp22 metrics/plots/report with the VLMs included"
"$PY" -u "$E22/scripts/05_metrics.py" > "$E22/logs/05_metrics_final.log" 2>&1
"$PY" -u "$E22/scripts/06_plots.py"   > "$E22/logs/06_plots_final.log" 2>&1
"$PY" -u "$E22/scripts/07_report.py"  > "$E22/logs/07_report_final.log" 2>&1

echo "$(date -Is) refreshing Exp23 with the VLMs included"
"$PY" -u "$E23/scripts/01_run_retrieval.py" > "$E23/logs/01_final.log" 2>&1
"$PY" -u "$E23/scripts/02_qualitative.py"   > "$E23/logs/02_final.log" 2>&1
"$PY" -u "$E23/scripts/03_plots.py"         > "$E23/logs/03_final.log" 2>&1
"$PY" -u "$E23/scripts/04_report.py"        > "$E23/logs/04_final.log" 2>&1

echo "$(date -Is) refreshing Exp24 plots and report"
"$PY" -u "$EXP/scripts/07_plots.py"  > "$EXP/logs/07_plots_final.log" 2>&1
"$PY" -u "$EXP/scripts/09_report.py" > "$EXP/logs/09_report_final.log" 2>&1

echo "$(date -Is) post-training chain finished"
