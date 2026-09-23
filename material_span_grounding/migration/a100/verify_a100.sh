#!/usr/bin/env bash
set -Eeuo pipefail

WORKSPACE_ROOT="${A100_WORKSPACE_ROOT:-/home/user/onsesang}"
PROJECT_ROOT="${1:-$WORKSPACE_ROOT/material_span_grounding}"
CONDA_BIN="${CONDA_EXE:-$WORKSPACE_ROOT/miniconda3/bin/conda}"
TEXTURE_PY="$WORKSPACE_ROOT/miniconda3/envs/texture/bin/python"
VLLM_PY="$WORKSPACE_ROOT/miniconda3/envs/material_vllm312/bin/python"

test -d "$PROJECT_ROOT"
test -x "$CONDA_BIN"
test -x "$TEXTURE_PY"
test -x "$VLLM_PY"

echo "== Host GPU =="
nvidia-smi --query-gpu=name,driver_version,memory.total,compute_cap --format=csv,noheader

echo "== Required local inputs =="
test -f "$WORKSPACE_ROOT/seoyoung/data/splits/train.json"
test -f "$WORKSPACE_ROOT/seoyoung/data/interim/recommendation_interactions.parquet"
test -d "$WORKSPACE_ROOT/yoojeong/amazon_reviews_all/review_Amazon_Fashion"
test -d "$WORKSPACE_ROOT/texture_project/images_train"
test -f "$WORKSPACE_ROOT/texture_project/data/product_images.json"
find "$WORKSPACE_ROOT/texture_project/images_train" -maxdepth 1 -type f | wc -l

echo "== texture CUDA stack =="
"$TEXTURE_PY" - <<'PY'
import torch, transformers
print("torch", torch.__version__, "build_cuda", torch.version.cuda)
print("transformers", transformers.__version__)
assert torch.cuda.is_available()
print("gpu", torch.cuda.get_device_name(0), "capability", torch.cuda.get_device_capability(0))
x = torch.ones((1024, 1024), device="cuda")
print("cuda_sum", x.sum().item())
PY

echo "== material_vllm312 CUDA stack =="
"$VLLM_PY" - <<'PY'
import torch, transformers, vllm
print("torch", torch.__version__, "build_cuda", torch.version.cuda)
print("transformers", transformers.__version__, "vllm", vllm.__version__)
assert torch.cuda.is_available()
print("gpu", torch.cuda.get_device_name(0), "capability", torch.cuda.get_device_capability(0))
PY

echo "== Root unit tests =="
cd "$PROJECT_ROOT"
"$TEXTURE_PY" -m unittest discover -s tests -v

echo "== v2 unit tests =="
cd "$PROJECT_ROOT/tactile_coldstart_qwen_v2_full"
PYTHONPATH=src "$TEXTURE_PY" -m unittest discover -s tests -v

echo "== Completed v2 manifests =="
"$TEXTURE_PY" - <<'PY'
import json
from pathlib import Path

root = Path.cwd()
required = {
    "phase0_full_pool.json": "complete",
    "phase1_taxonomy.json": "complete",
    "phase2_axis_grounding.json": "complete",
    "phase3_diagnostics.json": "complete",
    "phase4_human_audit.json": "skipped_by_user_pending",
    "phase5_targets.json": "complete",
    "phase6_7_models.json": "complete",
    "phase8_external.json": "complete_with_leeds_unavailable",
    "phase9_selective.json": "complete",
    "phase10_retrieval.json": "complete",
    "phase11_final.json": "complete",
}
for name, expected in required.items():
    row = json.loads((root / "manifests" / name).read_text(encoding="utf-8"))
    actual = row.get("status")
    print(name, actual)
    if actual != expected:
        raise SystemExit(f"{name}: expected {expected}, got {actual}")
PY

echo "A100 migration verification completed successfully."
