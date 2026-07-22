#!/usr/bin/env bash
# ============================================================
# DreamBook 一键 demo 脚本（适合录屏）
#
# 用法：
#   bash demo.sh                 # 默认跑 Plan A（如果有 sample 照片）
#   bash demo.sh a               # 强制 Plan A
#   bash demo.sh b               # 强制 Plan B
# ============================================================
set -e

PYTHON="${DREAMBOOK_PYTHON:-python3}"
ROOT="$(cd "$(dirname "$0")" && pwd)"

PLAN="${1:-auto}"

echo ""
echo "╔══════════════════════════════════════════════════════════╗"
echo "║                                                          ║"
echo "║       📖  DreamBook · 让梦想被看见  📖                   ║"
echo "║                                                          ║"
echo "║   「我想成为 XXX」童年梦想绘本 / 蓝图 Agent              ║"
echo "║                                                          ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""
echo "  硬件: NVIDIA DGX Spark (GB10 Blackwell)"
echo "  LLM:  Ollama nemotron-3-nano:30b (NVIDIA 自家模型)"
echo "  图像: FLUX.1-schnell (4 步, 10秒/张)"
echo "  Agent: 5 Agent 协作 (Plan B)"
echo ""
echo "============================================================"
echo ""

# 找 sample 照片
SAMPLE=""
for p in "$ROOT/dreambook/sample" "$ROOT/sample" ~/dreambook/sample; do
  if [ -d "$p" ]; then
    SAMPLE=$(ls "$p"/*.{jpg,jpeg,png} 2>/dev/null | head -1)
    [ -n "$SAMPLE" ] && break
  fi
done

if [ "$PLAN" = "auto" ]; then
  if [ -n "$SAMPLE" ]; then
    PLAN=a
    echo "📍 检测到样例照片: $SAMPLE"
    echo "📍 自动选择: Plan A (绘本)"
  else
    PLAN=b
    echo "📍 未检测到照片"
    echo "📍 自动选择: Plan B (蓝图)"
  fi
  echo ""
fi

echo "============================================================"
echo ""

if [ "$PLAN" = "a" ]; then
  echo "🚀 启动 Plan A: 梦想绘本"
  echo "   输入: 我想成为宇航员 + 照片"
  echo "   风格: pixar (皮克斯 3D)"
  echo ""
  $PYTHON "$ROOT/dreambook_router.py" \
      --dream "我想成为宇航员" \
      --style pixar \
      --face "$SAMPLE" \
      --force a
else
  echo "🚀 启动 Plan B: 梦想蓝图"
  echo "   输入: 我想成为画家"
  echo "   主角: 小明, 8 岁"
  echo ""
  $PYTHON "$ROOT/dreambook_router.py" \
      --dream "我想成为画家" \
      --name 小明 \
      --age 8 \
      --force b
fi

echo ""
echo "============================================================"
echo "✅ Demo 完成！请查看输出的 PDF"
echo "============================================================"
