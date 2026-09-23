#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="/home/user/onsesang/material_span_grounding"
VLLM_ENV="/home/user/onsesang/miniconda3/envs/material_vllm312"

if [[ -z "${DISCORD_WEBHOOK_URL:-}" ]]; then
  echo "DISCORD_WEBHOOK_URL is required" >&2
  exit 2
fi

export PATH="${VLLM_ENV}/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
export CC="/usr/bin/gcc-12"
export VLLM_USE_V2_MODEL_RUNNER="0"
export VLLM_USE_FLASHINFER_SAMPLER="0"
export VLLM_WORKER_MULTIPROC_METHOD="spawn"

cd "${PROJECT_ROOT}"
exec "${VLLM_ENV}/bin/python" run.py vllm-rerun

