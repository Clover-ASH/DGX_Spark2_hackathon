#!/usr/bin/env bash
# 启动 superhero 常驻服务（模型加载一次，后续秒级出图）。
#
# 用法：
#   bash start_server.sh           # 前台启动（看加载日志）
#   bash start_server.sh --bg      # 后台启动（nohup，断开 SSH 不停）
#   bash start_server.sh --status  # 查看状态
#   bash start_server.sh --stop    # 停止
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHON_BIN="${SUPERHERO_PYTHON:-python3}"
PORT="${SUPERHERO_PORT:-8765}"
PID_FILE="/tmp/superhero_server.pid"
LOG_FILE="/tmp/superhero_server.log"

export FLUX_MODEL_PATH="${FLUX_MODEL_PATH:-$HOME/ms_cache/models/AI-ModelScope--FLUX.1-schnell/snapshots/master}"
export OLLAMA_URL="${OLLAMA_URL:-http://127.0.0.1:11434}"
export OLLAMA_MODEL="${OLLAMA_MODEL:-qwen3.6:35b-a3b-q4_K_M}"

cmd="${1:-start}"

case "$cmd" in
  --bg)
    # 先杀旧的
    [ -f "$PID_FILE" ] && kill "$(cat "$PID_FILE")" 2>/dev/null || true
    pkill -f "superhero_server.py" 2>/dev/null || true
    # 演示前必须清干净 GPU（webapp/server.py 会占脏显存）
    pkill -f "webapp/server.py" 2>/dev/null || true
    sleep 1
    nohup "$PYTHON_BIN" "$SCRIPT_DIR/superhero_server.py" --port "$PORT" \
        > "$LOG_FILE" 2>&1 &
    echo $! > "$PID_FILE"
    echo "✅ 服务后台启动 (PID=$(cat "$PID_FILE"))，模型加载约 150s"
    echo "   日志: tail -f $LOG_FILE"
    echo "   状态: bash $0 --status"
    ;;
  --status)
    if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
      echo "进程运行中 (PID=$(cat "$PID_FILE"))"
    else
      echo "进程未运行"
      exit 1
    fi
    echo "--- 健康检查 ---"
    curl -s "http://127.0.0.1:$PORT/health" 2>&1 || echo "(服务未响应)"
    echo
    ;;
  --stop)
    [ -f "$PID_FILE" ] && kill "$(cat "$PID_FILE")" 2>/dev/null && echo "已停止" || echo "未运行"
    pkill -f "superhero_server.py" 2>/dev/null || true
    rm -f "$PID_FILE"
    ;;
  start|"")
    exec "$PYTHON_BIN" "$SCRIPT_DIR/superhero_server.py" --port "$PORT"
    ;;
  *)
    echo "用法: $0 [--bg|--status|--stop]"
    exit 1
    ;;
esac
