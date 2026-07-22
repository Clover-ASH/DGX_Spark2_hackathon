#!/usr/bin/env bash
# DreamBook 一键部署脚本 — 在 DGX Spark 节点上运行
#
# 前置条件：
#   1. workshop 已经跑通（comfyui-app/、ollama 服务、openclaw 已就绪）
#   2. 本脚本所在目录（dreambook/）包含完整 skill 文件
#
# 用法：
#   bash deploy.sh                          # 自动定位 WORKSHOP_DIR
#   WORKSHOP_DIR=/path bash deploy.sh       # 显式指定
set -euo pipefail

# locate WORKSHOP_DIR: try env var, then common paths
if [ -z "${WORKSHOP_DIR:-}" ]; then
    for candidate in \
        "$HOME/build_a_claw_workshop-bundle" \
        "$HOME/build_a_claw_workshop" \
        "$HOME/workshop" ; do
        if [ -d "$candidate" ] && [ -d "$candidate/comfyui-app" ]; then
            WORKSHOP_DIR="$candidate"
            break
        fi
    done
fi

if [ -z "${WORKSHOP_DIR:-}" ] || [ ! -d "$WORKSHOP_DIR/comfyui-app" ]; then
    echo "❌ 找不到 WORKSHOP_DIR（需要有 comfyui-app/ 子目录）" >&2
    echo "   请先跑通 workshop，或显式传 WORKSHOP_DIR=..." >&2
    exit 1
fi

SKILL_SRC="$(cd "$(dirname "$0")" && pwd)"
SKILL_DST="$WORKSHOP_DIR/openclaw-home/.openclaw/skills/dreambook"

echo "==> WORKSHOP_DIR = $WORKSHOP_DIR"
echo "==> skill src    = $SKILL_SRC"
echo "==> skill dst    = $SKILL_DST"
echo ""

# 1) copy skill files
mkdir -p "$SKILL_DST"
cp -v "$SKILL_SRC"/{SKILL.md,run_helper.sh,dreambook_helper.py,pdf_assembler.py,book_workflow.json} "$SKILL_DST/" 2>/dev/null || true
cp -rv "$SKILL_SRC/styles" "$SKILL_DST/"
chmod +x "$SKILL_DST/run_helper.sh"
echo ""

# 2) quick sanity check
echo "==> 校验文件..."
for f in SKILL.md run_helper.sh dreambook_helper.py pdf_assembler.py book_workflow.json; do
    [ -f "$SKILL_DST/$f" ] && echo "  ✅ $f" || echo "  ❌ $f 缺失"
done
echo "  styles 目录:"
ls "$SKILL_DST/styles/" | sed 's/^/    /'
echo ""

# 3) optional: install reportlab/pillow into comfyui venv
VENV="$WORKSHOP_DIR/comfyui-app/comfyui-env"
if [ -f "$VENV/bin/activate" ]; then
    echo "==> 给 ComfyUI venv 装 reportlab + pillow（PDF 拼装用）..."
    (
        source "$VENV/bin/activate"
        pip install --quiet reportlab pillow 2>&1 | tail -3 || true
        python3 -c "import reportlab, PIL; print('  ✅ reportlab', reportlab.Version, '+ pillow OK')"
    ) || echo "  ⚠️  pip install 失败，第一次出 PDF 时 run_helper.sh 会再装一次"
else
    echo "  ⚠️  ComfyUI venv 没找到 ($VENV)，跳过预装"
fi
echo ""

# 4) restart OpenClaw
if [ -x "$WORKSHOP_DIR/scripts/openclaw-ctl.sh" ]; then
    echo "==> 重启 OpenClaw 让它扫描 dreambook skill..."
    bash "$WORKSHOP_DIR/scripts/openclaw-ctl.sh" restart
    sleep 3
    echo "==> 已加载 skills:"
    (cd "$WORKSHOP_DIR" && ./openclaw skills list 2>/dev/null) | grep -E "dreambook|superhero" || true
else
    echo "  ⚠️  没找到 scripts/openclaw-ctl.sh，请手动重启 OpenClaw"
fi
echo ""

echo "🎉 DreamBook 部署完成！"
echo ""
echo "测试命令（绕过 Agent，直接命令行跑）："
echo "  cd \"$WORKSHOP_DIR\""
echo "  export WORKSHOP_DIR OPENCLAW_HOME=\$WORKSHOP_DIR/openclaw-home"
echo "  SKILL=\"\$OPENCLAW_HOME/.openclaw/skills/dreambook\""
echo "  # 准备一张测试人脸图到 sample/test.jpg，然后："
echo "  bash \"\$SKILL/run_helper.sh\" --face sample/test.jpg --dream \"我想成为宇航员\" --style pixar"
