#!/usr/bin/env bash
# DreamBook entry script invoked by OpenClaw.
# Activates ComfyUI's bundled venv (which has `requests`) and runs the helper.
#
# Skill lives at:
#   $WORKSHOP_DIR/openclaw-home/.openclaw/skills/dreambook/run_helper.sh
# so 4 parents up from this script is $WORKSHOP_DIR.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
WORKSHOP_DIR="$(cd "$SCRIPT_DIR/../../../.." && pwd)"
APP="$WORKSHOP_DIR/comfyui-app"
VENV="$APP/comfyui-env"

if [ ! -f "$VENV/bin/activate" ]; then
    echo "ERROR: ComfyUI venv not found at $VENV" >&2
    echo "Run the workshop [部署 ComfyUI] section first." >&2
    exit 1
fi

cd "$APP"
# shellcheck source=/dev/null
source "$VENV/bin/activate"

# Make sure reportlab/pillow are available for PDF assembly
python3 -c "import reportlab, PIL" 2>/dev/null || {
    echo "[dreambook] installing reportlab + pillow for PDF assembly…" >&2
    pip install --quiet reportlab pillow 2>&1 | tail -3 >&2 || true
}

export WORKSHOP_DIR
export COMFYUI_URL="${COMFYUI_URL:-http://127.0.0.1:${COMFYUI_PORT:-8200}}"
export OLLAMA_URL="${OLLAMA_URL:-http://127.0.0.1:11434}"
export OLLAMA_MODEL="${OLLAMA_MODEL:-qwen3.6:35b}"
export HF_HOME="${HF_HOME:-$WORKSHOP_DIR/hf-cache}"

exec python3 "$SCRIPT_DIR/dreambook_helper.py" "$@"
