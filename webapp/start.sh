#!/usr/bin/env bash
# ============================================================
# DreamBook Web 服务启动脚本
#
# 用法：
#   bash start.sh                 # 前台运行（看日志）
#   bash start.sh --bg            # 后台运行（断开 SSH 不停）
#   bash start.sh --stop          # 停止
#   bash start.sh --status        # 看状态
# ============================================================
set -e

PYTHON="${DREAMBOOK_PYTHON:-python3}"
HOST="${DREAMBOOK_HOST:-0.0.0.0}"
PORT="${DREAMBOOK_PORT:-8000}"
PID_FILE="$HOME/dreambook_web.pid"
LOG_FILE="$HOME/dreambook_web.log"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

CMD="$PYTHON -u $SCRIPT_DIR/server.py"

# 先装依赖
$PYTHON -c "import fastapi, uvicorn" 2>/dev/null || {
    echo "[start] installing fastapi + uvicorn + python-multipart..."
    $PYTHON -m pip install -q -i https://pypi.tuna.tsinghua.edu.cn/simple \
        fastapi "uvicorn[standard]" python-multipart 2>&1 | tail -3
}

case "${1:-}" in
  --stop)
    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE")
        kill "$PID" 2>/dev/null && echo "[stop] killed PID $PID" || echo "[stop] process not running"
        rm -f "$PID_FILE"
    else
        echo "[stop] no pid file"
    fi
    ;;

  --status)
    if [ -f "$PID_FILE" ] && kill -0 "$(cat $PID_FILE)" 2>/dev/null; then
        echo "[status] running, PID=$(cat $PID_FILE), port=$PORT"
        echo "[status] health check:"
        curl -s -m 2 http://127.0.0.1:$PORT/api/health | head -c 300
        echo
    else
        echo "[status] not running"
    fi
    ;;

  --bg)
    echo "[start] background mode, port=$PORT"
    nohup $PYTHON -u "$SCRIPT_DIR/server.py" > "$LOG_FILE" 2>&1 &
    echo $! > "$PID_FILE"
    sleep 2
    if kill -0 "$(cat $PID_FILE)" 2>/dev/null; then
        echo "[start] ✅ started, PID=$(cat $PID_FILE)"
        echo "[start] log: $LOG_FILE"
        # 找公网端口映射
        echo ""
        echo "[start] 访问方式："
        echo "  本机:   http://localhost:$PORT"
        # 推算公网端口（SSH <port> → web <port+2000>）
        SSH_PORT=<your-ssh-port>
        WEB_PORT=$((SSH_PORT - 1000))
        echo "  公网:   http://<your-spark-ip>:$WEB_PORT"
        echo ""
        echo "[start] 实时日志: tail -f $LOG_FILE"
    else
        echo "[start] ❌ failed to start, see $LOG_FILE"
        tail -20 "$LOG_FILE"
        rm -f "$PID_FILE"
        exit 1
    fi
    ;;

  *)
    echo "[start] foreground mode, port=$PORT (Ctrl+C 退出)"
    echo "[start] access: http://localhost:$PORT"
    exec $PYTHON -u "$SCRIPT_DIR/server.py"
    ;;
esac
