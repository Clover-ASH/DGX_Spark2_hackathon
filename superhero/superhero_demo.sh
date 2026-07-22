#!/usr/bin/env bash
# Superhero demo 客户端 —— 调用常驻服务，录制时用这个。
#
# 前提：superhero_server.py 已在后台启动并 ready（见 start_server.sh）
#
# 用法：
#   ./superhero_demo.sh "金色铠甲闪电侠"     # 中文 → LLM 扩写 → 出图
#   ./superhero_demo.sh                       # 默认超级英雄 prompt
#   ./superhero_demo.sh --en "a red suit hero" # 跳过 LLM 直接英文
set -euo pipefail

SERVER="${SUPERHERO_SERVER:-http://127.0.0.1:8765}"
PYTHON="${SUPERHERO_PYTHON:-python3}"

# 检查服务是否就绪
ready=$("$PYTHON" -c "
import urllib.request, json, sys
try:
    d = json.load(urllib.request.urlopen('$SERVER/health', timeout=3))
    print('1' if d.get('ready') else '0')
except Exception:
    print('0')
" 2>/dev/null || echo "0")

if [ "$ready" != "1" ]; then
    echo "❌ superhero 服务未就绪。请先启动:"
    echo "   nohup bash ~/superhero/start_server.sh >/tmp/superhero_server.log 2>&1 &"
    echo "   然后等 ~150s（模型加载），用以下命令检查:"
    echo "   curl -s $SERVER/health"
    exit 1
fi

echo "═══════════════════════════════════════════════════════"
echo "  🦸 Superhero Photo Generator (DGX Spark 本地 Agent)"
echo "═══════════════════════════════════════════════════════"
echo

# 解析参数
desc=""
prompt=""
if [ "${1:-}" = "--en" ]; then
    shift
    prompt="${1:-}"
    [ -z "$prompt" ] && { echo "用法: $0 --en \"english prompt\""; exit 1; }
else
    desc="${1:-}"
fi

if [ -n "$desc" ]; then
    echo "📝 用户输入: $desc"
    echo "🤖 正在用 qwen3.6 扩写 FLUX prompt..."
    url="$SERVER/generate?desc=$(python3 -c "import urllib.parse,sys; print(urllib.parse.quote(sys.argv[1]))" "$desc")"
elif [ -n "$prompt" ]; then
    echo "📝 英文 prompt: $prompt"
    url="$SERVER/generate?prompt=$(python3 -c "import urllib.parse,sys; print(urllib.parse.quote(sys.argv[1]))" "$prompt")"
else
    echo "📝 使用默认超级英雄 prompt"
    url="$SERVER/generate"
fi
echo "🎨 FLUX 出图中..."
echo

result=$("$PYTHON" -c "
import urllib.request, json, sys
try:
    d = json.load(urllib.request.urlopen('''$url''', timeout=300))
    print(json.dumps(d))
except Exception as e:
    print(json.dumps({'error': str(e)}))
")

echo "───────────────────────────────────────────────────────"
echo "$result" | "$PYTHON" -c "
import json, sys
d = json.load(sys.stdin)
if 'error' in d:
    print('❌ 失败:', d['error']); sys.exit(1)
if d.get('used_llm'):
    print('🤖 LLM 扩写 prompt:')
    print('   ', d['prompt'][:150])
    print()
print(f\"⏱  耗时: {d['elapsed']}s\")
print(f\"📦 图片: {d['media']}\")
print()
print('MEDIA:' + d['media'])
"
echo "───────────────────────────────────────────────────────"
