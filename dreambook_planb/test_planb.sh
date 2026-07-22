#!/usr/bin/env bash
# Plan B 快速测试 — 验证 5 Agent + PDF 能跑通
# 用法：
#   bash test_planb.sh
set -e

PYTHON="${DREAMBOOK_PYTHON:-python3}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "============================================================"
echo "  DreamBlueprint Plan B 测试"
echo "============================================================"
echo ""

# 1) check ollama
echo "=== 1. 检查 Ollama ==="
curl -s -m 3 http://127.0.0.1:11434/api/tags | grep -o '"name":"[^"]*"' | head -3
echo ""

# 2) install reportlab if missing
echo "=== 2. 检查 reportlab ==="
$PYTHON -c "import reportlab; print('reportlab:', reportlab.Version)" 2>/dev/null || {
    echo "装 reportlab..."
    $PYTHON -m pip install -q -i https://pypi.tuna.tsinghua.edu.cn/simple reportlab
}
echo ""

# 3) 跑 Plan B（用一个简单梦想做测试）
echo "=== 3. 跑 DreamBlueprint（测试梦想：我想成为宇航员）==="
$PYTHON "$SCRIPT_DIR/dream_blueprint.py" \
    --dream "我想成为宇航员" \
    --name 小明 \
    --age 8
