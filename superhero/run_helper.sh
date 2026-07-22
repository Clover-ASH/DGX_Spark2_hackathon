#!/usr/bin/env bash
# Superhero skill 入口（diffusers 后端）。
# 需要一个装了 diffusers + torch(+CUDA) 的 Python，通过 SUPERHERO_PYTHON 指定。
# 例：export SUPERHERO_PYTHON=/path/to/conda/envs/reid/bin/python3
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# 默认 python3；需用 SUPERHERO_PYTHON 指向含 diffusers+torch 的解释器。
PYTHON_BIN="${SUPERHERO_PYTHON:-python3}"
if [ ! -x "$PYTHON_BIN" ]; then
    echo "ERROR: python not found at $PYTHON_BIN" >&2
    echo "set SUPERHERO_PYTHON to a python with diffusers+torch" >&2
    exit 1
fi

# 默认参数透传给 helper
export FLUX_MODEL_PATH="${FLUX_MODEL_PATH:-$HOME/ms_cache/models/AI-ModelScope--FLUX.1-schnell/snapshots/master}"
export OLLAMA_URL="${OLLAMA_URL:-http://127.0.0.1:11434}"
export OLLAMA_MODEL="${OLLAMA_MODEL:-qwen3.6:35b-a3b-q4_K_M}"
export SUPERHERO_OUT="${SUPERHERO_OUT:-$HOME/superhero_output}"

exec "$PYTHON_BIN" "$SCRIPT_DIR/superhero_helper.py" "$@"
