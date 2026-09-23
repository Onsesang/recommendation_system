#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
PY=/home/user/onsesang/miniconda3/envs/texture/bin/python

# Each stage is resume-safe. Test scripts refuse to run until all validation
# decisions are locked and refuse duplicate one-shot backbone test evaluation.
$PY inspect_environment.py
$PY prepare_amazon_fashion.py
$PY prepare_metadata.py
$PY dry_run.py
$PY recommender.py --models popularity bpr lightgcn sasrec esasrec
$PY select_backbone.py
$PY generate_candidates.py --split validation --model-key strong
$PY build_tactile_profiles.py
$PY tune_tactile_reranker.py --model-key strong
$PY build_generic_features.py
$PY train_multimodal.py
if "$PY" -c "import json;print(json.load(open('artifacts/multimodal_selection.json'))['status']=='validation_locked')" | grep -q True; then
  $PY generate_candidates.py --split validation --model-key smore
  $PY tune_tactile_reranker.py --model-key smore
fi
$PY evaluate_backbones_test.py
$PY generate_candidates.py --split test --model-key strong
$PY evaluate_general_rec.py
if "$PY" -c "import json;print(json.load(open('artifacts/multimodal_selection.json'))['status']=='validation_locked')" | grep -q True; then
  $PY generate_candidates.py --split test --model-key smore
fi
$PY evaluate_multimodal_test.py
$PY evaluate_tactile_rec.py
$PY sanity_checks.py
$PY make_report.py
