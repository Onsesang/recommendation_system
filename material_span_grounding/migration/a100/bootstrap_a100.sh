#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
WORKSPACE_ROOT="${A100_WORKSPACE_ROOT:-/home/user/onsesang}"
EXPECTED_PROJECT_ROOT="$WORKSPACE_ROOT/material_span_grounding"
CONDA_ROOT="${A100_CONDA_ROOT:-$WORKSPACE_ROOT/miniconda3}"
CONDA_BIN="$CONDA_ROOT/bin/conda"
HF_CACHE_ROOT="$WORKSPACE_ROOT/.cache/huggingface"

echo "Project: $PROJECT_ROOT"
echo "Home: $HOME"
echo "Fixed workspace: $WORKSPACE_ROOT"
if [[ "$PROJECT_ROOT" != "$EXPECTED_PROJECT_ROOT" ]]; then
  echo "ERROR: project must be restored at $EXPECTED_PROJECT_ROOT, got $PROJECT_ROOT" >&2
  exit 9
fi
uname -a
if ! command -v nvidia-smi >/dev/null 2>&1; then
  echo "ERROR: nvidia-smi is unavailable. Ask the server administrator to install a working A100 driver." >&2
  exit 10
fi
nvidia-smi --query-gpu=name,driver_version,memory.total,compute_cap --format=csv,noheader
if ! nvidia-smi --query-gpu=name --format=csv,noheader | grep -q 'A100'; then
  echo "ERROR: an NVIDIA A100 was not detected. Driver installation is intentionally outside this script." >&2
  exit 11
fi

if [[ ! -x "$CONDA_BIN" ]]; then
  mkdir -p "$WORKSPACE_ROOT/incoming"
  installer="$WORKSPACE_ROOT/incoming/Miniconda3-latest-Linux-x86_64.sh"
  if command -v curl >/dev/null 2>&1; then
    curl -fL --retry 5 -o "$installer" \
      https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh
  elif command -v wget >/dev/null 2>&1; then
    wget -O "$installer" \
      https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh
  else
    echo "ERROR: curl or wget is required to download Miniconda." >&2
    exit 12
  fi
  bash "$installer" -b -p "$CONDA_ROOT"
fi
export PATH="$CONDA_ROOT/bin:$PATH"
if ! command -v git >/dev/null 2>&1; then
  "$CONDA_BIN" install -n base -y git
fi

mkdir -p "$HF_CACHE_ROOT" "$HOME/.cache"
if [[ "$(readlink -f "$HOME/.cache/huggingface")" == "$HF_CACHE_ROOT" ]]; then
  echo "Hugging Face cache already resolves to $HF_CACHE_ROOT"
elif [[ -L "$HOME/.cache/huggingface" ]]; then
  if [[ "$(readlink -f "$HOME/.cache/huggingface")" != "$HF_CACHE_ROOT" ]]; then
    echo "ERROR: existing Hugging Face cache symlink points outside $WORKSPACE_ROOT" >&2
    exit 13
  fi
elif [[ -e "$HOME/.cache/huggingface" ]]; then
  echo "ERROR: $HOME/.cache/huggingface already exists. Preserve it and let Codex resolve the cache location safely." >&2
  exit 14
else
  ln -s "$HF_CACHE_ROOT" "$HOME/.cache/huggingface"
fi
export HF_HOME="$HF_CACHE_ROOT"
export HF_HUB_CACHE="$HF_CACHE_ROOT/hub"
mkdir -p "$HF_HUB_CACHE"

create_env() {
  local env_name="$1"
  local spec="$2"
  local pytorch_index="${3:-}"
  if "$CONDA_BIN" env list | awk '{print $1}' | grep -qx "$env_name"; then
    echo "Environment $env_name already exists; preserving it for Codex to audit."
    return 0
  fi
  if [[ -n "$pytorch_index" ]]; then
    PIP_EXTRA_INDEX_URL="$pytorch_index" "$CONDA_BIN" env create -f "$spec"
  else
    "$CONDA_BIN" env create -f "$spec"
  fi
}

create_env texture "$SCRIPT_DIR/environment.texture.yml" \
  https://download.pytorch.org/whl/cu121
create_env material_vllm312 "$SCRIPT_DIR/environment.material_vllm312.yml"

"$CONDA_ROOT/envs/texture/bin/python" "$SCRIPT_DIR/relocate_paths.py" \
  --project-root "$PROJECT_ROOT" --old-home /home/onsesang --new-home "$WORKSPACE_ROOT"

if [[ ! -f "$PROJECT_ROOT/shopping_agent/.env.example" ]]; then
  cp "$SCRIPT_DIR/shopping_agent.env.example.safe" "$PROJECT_ROOT/shopping_agent/.env.example"
fi

"$CONDA_ROOT/envs/texture/bin/python" "$SCRIPT_DIR/download_models.py" \
  --cache-dir "$HF_HUB_CACHE"

A100_WORKSPACE_ROOT="$WORKSPACE_ROOT" CONDA_EXE="$CONDA_BIN" \
  "$SCRIPT_DIR/verify_a100.sh" "$PROJECT_ROOT"
