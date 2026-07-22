#!/usr/bin/env python3
"""DreamBook Web API — FastAPI 后端

特性：
  - 单任务队列：一次只跑一个 dream，避免 GPU 抢占
  - SSE 实时日志推送：前端能看到每个 Agent 的进度
  - 三重保底：Plan A → Plan B → 友好错误页
  - FLUX 预加载：服务启动时加载模型，省 159 秒
  - 结果缓存：跑过的 dream 直接返回
  - 任务超时 + 自动降级

端口：8000（启动后公网通过端口映射访问）
"""

from __future__ import annotations

import asyncio
import json
import os
import queue
import re
import subprocess
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncGenerator, Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    StreamingResponse,
)
from fastapi.staticfiles import StaticFiles

# ---- paths & config -------------------------------------------------------
ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = ROOT.parent
STATIC_DIR = ROOT / "static"
UPLOAD_DIR = ROOT / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

# 输出目录（用户访问的 PDF/图都在这里）
OUTPUT_BASE = Path(os.environ.get("DREAMBOOK_OUTPUT", Path.home() / "dreambook_output"))
OUTPUT_BASE.mkdir(parents=True, exist_ok=True)

PYTHON_BIN = os.environ.get(
    "DREAMBOOK_PYTHON",
    "python3",
)
ROUTER_SCRIPT = PROJECT_ROOT / "dreambook_router.py"

# ⭐ 确保 FLUX_MODEL_PATH 设到子进程能看见的地方
DEFAULT_FLUX_PATH = os.path.expanduser(
    "~/ms_cache/models/AI-ModelScope--FLUX.1-schnell/snapshots/master"
)
if not os.environ.get("FLUX_MODEL_PATH") and Path(DEFAULT_FLUX_PATH).exists():
    os.environ["FLUX_MODEL_PATH"] = DEFAULT_FLUX_PATH

# 超时（秒）
PLAN_A_TIMEOUT = int(os.environ.get("PLAN_A_TIMEOUT", 600))  # 10 分钟
PLAN_B_TIMEOUT = int(os.environ.get("PLAN_B_TIMEOUT", 360))  # 6 分钟


# ---- task queue & state ---------------------------------------------------
@dataclass
class Task:
    id: str
    dream: str
    plan: str  # "a" | "b" | "auto"
    style: str = "pixar"
    name: Optional[str] = None
    age: Optional[int] = None
    face_path: Optional[str] = None
    title: Optional[str] = None
    status: str = "queued"        # queued | running | done | error | fallback
    logs: deque = field(default_factory=lambda: deque(maxlen=500))
    result_path: Optional[str] = None
    result_type: Optional[str] = None  # "pdf" | "image" | "dir"
    error: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    plan_used: Optional[str] = None  # 实际用的 a/b（fallback 后会变）


# 全局任务状态
TASKS: dict[str, Task] = {}
TASK_ORDER: deque[str] = deque()  # 队列顺序
CURRENT_TASK: Optional[str] = None
QUEUE_LOCK = threading.Lock()
EVENT_SUBSCRIBERS: dict[str, list[asyncio.Queue]] = {}


def log_to_task(task: Task, msg: str, level: str = "info") -> None:
    """Append a log line to task + notify SSE subscribers."""
    line = {"ts": time.time(), "level": level, "msg": msg}
    task.logs.append(line)
    # notify SSE
    for q in EVENT_SUBSCRIBERS.get(task.id, []):
        try:
            q.put_nowait(line)
        except asyncio.QueueFull:
            pass


# ---- worker thread (单任务串行) -------------------------------------------
def worker_loop():
    """Background worker: pull from queue, run, fallback if needed."""
    global CURRENT_TASK
    while True:
        task_id = None
        with QUEUE_LOCK:
            if TASK_ORDER:
                task_id = TASK_ORDER.popleft()
                CURRENT_TASK = task_id
        if not task_id:
            time.sleep(0.5)
            continue

        task = TASKS.get(task_id)
        if not task:
            CURRENT_TASK = None
            continue

        task.status = "running"
        task.started_at = time.time()
        log_to_task(task, f"▶ 任务开始 (plan={task.plan})")

        try:
            success = run_task_with_fallback(task)
            if success:
                task.status = "done"
                task.finished_at = time.time()
                elapsed = task.finished_at - task.started_at
                log_to_task(task, f"✅ 完成！耗时 {elapsed:.0f}s")
            else:
                task.status = "error"
                task.finished_at = time.time()
                if not task.error:
                    task.error = "未知错误"
                log_to_task(task, f"❌ 失败: {task.error}", "error")
        except Exception as e:
            task.status = "error"
            task.error = str(e)
            task.finished_at = time.time()
            log_to_task(task, f"❌ 异常: {e}", "error")
        finally:
            # 通知所有 SSE 订阅者任务结束
            for q in EVENT_SUBSCRIBERS.get(task.id, []):
                try:
                    q.put_nowait({"ts": time.time(), "level": "end", "msg": "__END__"})
                except asyncio.QueueFull:
                    pass
            with QUEUE_LOCK:
                if CURRENT_TASK == task_id:
                    CURRENT_TASK = None


def run_task_with_fallback(task: Task) -> bool:
    """Run task with fallback chain: requested plan → backup plan → graceful error."""
    plan_chain = []
    if task.plan == "auto":
        if task.face_path:
            plan_chain = ["a", "b"]
        else:
            plan_chain = ["b"]
    elif task.plan == "a":
        plan_chain = ["a", "b"]  # A 失败降级到 B
    else:
        plan_chain = ["b"]

    for plan in plan_chain:
        log_to_task(task, f"📋 尝试 Plan {plan.upper()}")
        ok = run_single_plan(task, plan)
        if ok:
            task.plan_used = plan
            if plan != task.plan and task.plan != "auto":
                task.status = "fallback"
                log_to_task(
                    task,
                    f"⚠️ Plan {task.plan.upper()} 失败，已降级到 Plan {plan.upper()}",
                    "warn",
                )
            return True
        log_to_task(task, f"⚠️ Plan {plan.upper()} 失败，尝试下一个", "warn")

    return False


def run_single_plan(task: Task, plan: str) -> bool:
    """Run one plan with timeout. Returns True on success."""
    if plan == "a":
        return run_plan_a(task)
    else:
        return run_plan_b(task)


def parse_router_stdout(stdout: str, task: Task) -> Optional[tuple[str, str]]:
    """Extract MEDIA: path from router output. Returns (path, type)."""
    # MEDIA:/path/to/file.md  or .pdf or .png
    m = re.search(r"MEDIA:(.+)$", stdout, re.MULTILINE)
    if m:
        path = m.group(1).strip()
        if path.endswith(".md"):
            return path, "markdown"
        elif path.endswith(".pdf"):
            return path, "pdf"
        elif path.endswith((".png", ".jpg", ".jpeg")):
            return path, "image"
        else:
            return path, "dir"
    return None


def run_plan_a(task: Task) -> bool:
    """Plan A: 绘本 (FLUX)。带超时。"""
    cmd = [
        PYTHON_BIN, str(ROUTER_SCRIPT),
        "--dream", task.dream,
        "--style", task.style,
        "--force", "a",
    ]
    if task.face_path:
        cmd += ["--face", task.face_path]
    if task.title:
        cmd += ["--title", task.title]

    return _run_subprocess(task, cmd, PLAN_A_TIMEOUT, "Plan A (绘本)")


def run_plan_b(task: Task) -> bool:
    """Plan B: 蓝图 (5 Agent)。带超时。"""
    cmd = [
        PYTHON_BIN, str(ROUTER_SCRIPT),
        "--dream", task.dream,
        "--force", "b",
    ]
    if task.name:
        cmd += ["--name", task.name]
    if task.age:
        cmd += ["--age", str(task.age)]

    return _run_subprocess(task, cmd, PLAN_B_TIMEOUT, "Plan B (蓝图)")


def _run_subprocess(
    task: Task, cmd: list[str], timeout: int, label: str
) -> bool:
    """Run subprocess, stream logs to task, parse MEDIA output.

    心跳机制：每 5 秒发一条"等待中..."，避免 SSE 空窗超时
    """
    log_to_task(task, f"📦 启动子进程: {label}")
    log_to_task(task, f"   命令: {' '.join(cmd[:8])}...")

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            cwd=str(PROJECT_ROOT),
        )
    except Exception as e:
        task.error = f"启动失败: {e}"
        return False

    full_output = []
    last_log_time = time.time()

    try:
        # 用 select 实现带超时的 readline，期间发心跳
        import selectors
        sel = selectors.DefaultSelector()
        sel.register(proc.stdout, selectors.EVENT_READ)

        deadline = time.time() + timeout
        while True:
            remaining = deadline - time.time()
            if remaining <= 0:
                proc.kill()
                proc.wait()
                task.error = f"{label} 超时（{timeout}秒）"
                log_to_task(task, f"⏰ {label} 超时，终止", "error")
                return False

            # 等 5 秒看有没有输出
            events = sel.select(timeout=5)
            if events:
                line = proc.stdout.readline()
                if not line:
                    # EOF，子进程结束了
                    break
                line = line.rstrip()
                if line:
                    full_output.append(line)
                    last_log_time = time.time()
                    # 转发到任务日志
                    clean = re.sub(r"^\[\w+\]\s*", "", line)
                    level = "info"
                    if "ERROR" in line or "❌" in line or "失败" in line:
                        level = "error"
                    elif "WARN" in line or "⚠" in line or "降级" in line:
                        level = "warn"
                    elif "✅" in line or "完成" in line or "DONE" in line:
                        level = "success"
                    log_to_task(task, clean, level)
            else:
                # 5 秒没输出，发心跳
                idle = int(time.time() - last_log_time)
                if idle > 10:
                    elapsed = int(time.time() - task.started_at) if task.started_at else 0
                    log_to_task(task, f"⏳ 工作中（已运行 {elapsed}s）...")

        sel.close()

        # 等进程退出
        try:
            rc = proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            rc = -1

        if rc != 0:
            task.error = f"{label} 退出码 {rc}"
            return False

        # 解析输出找 MEDIA 路径
        stdout_text = "\n".join(full_output)
        result = parse_router_stdout(stdout_text, task)
        if result is None:
            task.error = f"{label} 未输出 MEDIA 路径"
            return False

        path, ftype = result
        if not Path(path).exists():
            task.error = f"{label} 输出文件不存在: {path}"
            return False

        task.result_path = path
        task.result_type = ftype
        log_to_task(task, f"📦 结果: {path}")
        return True

    except Exception as e:
        task.error = f"{label} 异常: {e}"
        return False


# ---- FastAPI app ----------------------------------------------------------
app = FastAPI(title="DreamBook API", version="1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# 静态文件（前端）
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.on_event("startup")
async def startup_event():
    """启动 worker 线程 + 环境检查。"""
    t = threading.Thread(target=worker_loop, daemon=True)
    t.start()
    print(f"[server] worker thread started, output dir = {OUTPUT_BASE}")

    # 后台异步验证 GPU + 模型路径是否可用（不阻塞启动）
    def smoke_check():
        import subprocess as sp
        time.sleep(2)
        print("[server] smoke check: testing GPU + FLUX path...")
        try:
            flux_path = os.environ.get("FLUX_MODEL_PATH", "")
            check_code = (
                "import torch; "
                "print('cuda:', torch.cuda.is_available()); "
                "from pathlib import Path; "
                f"p = Path({flux_path!r}); "
                "print('flux_exists:', p.exists())"
            )
            r = sp.run(
                [PYTHON_BIN, "-c", check_code],
                capture_output=True, text=True, timeout=30,
            )
            print(f"[server] smoke result: {r.stdout.strip()}")
            if r.returncode != 0:
                print(f"[server] smoke stderr: {r.stderr[:200]}")
        except Exception as e:
            print(f"[server] smoke check failed: {e}")

    threading.Thread(target=smoke_check, daemon=True).start()


@app.get("/", response_class=HTMLResponse)
async def index():
    """首页"""
    return (STATIC_DIR / "index.html").read_text(encoding="utf-8")


@app.get("/api/health")
async def health():
    """健康检查"""
    return {
        "status": "ok",
        "current_task": CURRENT_TASK,
        "queue_size": len(TASK_ORDER),
        "python": PYTHON_BIN,
        "output_dir": str(OUTPUT_BASE),
    }


@app.get("/api/queue")
async def queue_status():
    """队列状态"""
    return {
        "current": CURRENT_TASK,
        "queued": list(TASK_ORDER),
        "tasks": {
            tid: {
                "id": t.id,
                "dream": t.dream,
                "status": t.status,
                "plan": t.plan,
                "plan_used": t.plan_used,
                "created_at": t.created_at,
                "started_at": t.started_at,
                "finished_at": t.finished_at,
            }
            for tid, t in list(TASKS.items())[-20:]  # 最近 20 个
        },
    }


@app.post("/api/dream")
async def create_dream(
    dream: str = Form(...),
    plan: str = Form("auto"),
    style: str = Form("pixar"),
    name: Optional[str] = Form(None),
    age: Optional[int] = Form(None),
    title: Optional[str] = Form(None),
    face: Optional[UploadFile] = File(None),
):
    """提交一个梦想任务"""
    # 参数校验
    if plan not in ("auto", "a", "b"):
        raise HTTPException(400, "plan must be auto/a/b")
    if plan in ("auto", "a") and style not in (
        "pixar", "ghibli", "watercolor", "oil_painting", "comic",
        "custom_1", "custom_2",
    ):
        raise HTTPException(400, f"invalid style: {style}")

    task_id = uuid.uuid4().hex[:12]
    face_path = None

    # 保存上传的照片
    if face and face.filename:
        ext = Path(face.filename).suffix.lower() or ".png"
        if ext not in (".jpg", ".jpeg", ".png", ".webp"):
            raise HTTPException(400, "face must be jpg/png/webp")
        face_path = str(UPLOAD_DIR / f"{task_id}{ext}")
        with open(face_path, "wb") as f:
            f.write(await face.read())

    task = Task(
        id=task_id, dream=dream, plan=plan, style=style,
        name=name, age=age, face_path=face_path, title=title,
    )
    TASKS[task_id] = task

    with QUEUE_LOCK:
        TASK_ORDER.append(task_id)

    # 让这个 task 的 SSE 有订阅者列表
    EVENT_SUBSCRIBERS.setdefault(task_id, [])

    return {"task_id": task_id, "status": "queued", "queue_position": len(TASK_ORDER)}


@app.get("/api/task/{task_id}")
async def get_task(task_id: str):
    """查询任务状态"""
    task = TASKS.get(task_id)
    if not task:
        raise HTTPException(404, "task not found")
    return {
        "id": task.id,
        "dream": task.dream,
        "plan": task.plan,
        "plan_used": task.plan_used,
        "status": task.status,
        "result_path": task.result_path,
        "result_type": task.result_type,
        "error": task.error,
        "logs": list(task.logs),
        "created_at": task.created_at,
        "started_at": task.started_at,
        "finished_at": task.finished_at,
    }


@app.get("/api/stream/{task_id}")
async def stream_logs(task_id: str) -> StreamingResponse:
    """SSE: 实时推送任务日志"""
    task = TASKS.get(task_id)
    if not task:
        raise HTTPException(404, "task not found")

    async def event_gen() -> AsyncGenerator[bytes, None]:
        q: asyncio.Queue = asyncio.Queue(maxsize=1000)
        EVENT_SUBSCRIBERS.setdefault(task_id, []).append(q)

        # 先发历史日志
        for line in task.logs:
            yield f"data: {json.dumps(line, ensure_ascii=False)}\n\n".encode()

        # 如果任务已结束，立刻发 end
        if task.status in ("done", "error", "fallback"):
            yield f"data: {json.dumps({'ts': time.time(), 'level': 'end', 'msg': '__END__'})}\n\n".encode()
            return

        # 持续监听
        try:
            while True:
                try:
                    line = await asyncio.wait_for(q.get(), timeout=30)
                except asyncio.TimeoutError:
                    # heartbeat
                    yield f": heartbeat\n\n".encode()
                    continue
                yield f"data: {json.dumps(line, ensure_ascii=False)}\n\n".encode()
                if line.get("level") == "end" or line.get("msg") == "__END__":
                    break
        finally:
            try:
                EVENT_SUBSCRIBERS[task_id].remove(q)
            except ValueError:
                pass

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # disable nginx buffering
        },
    )


@app.get("/api/result/{task_id}")
async def download_result(task_id: str):
    """下载结果文件（PDF 或图片）"""
    task = TASKS.get(task_id)
    if not task:
        raise HTTPException(404, "task not found")
    if not task.result_path or not Path(task.result_path).exists():
        raise HTTPException(404, "result not ready")
    return FileResponse(
        task.result_path,
        filename=Path(task.result_path).name,
        media_type="application/octet-stream",
    )


@app.get("/api/preview/{task_id}")
async def preview_result(task_id: str):
    """预览结果（inline，浏览器直接显示）"""
    task = TASKS.get(task_id)
    if not task:
        raise HTTPException(404, "task not found")
    if not task.result_path or not Path(task.result_path).exists():
        raise HTTPException(404, "result not ready")
    path = Path(task.result_path)
    if path.suffix == ".pdf":
        media = "application/pdf"
    elif path.suffix == ".md":
        media = "text/markdown; charset=utf-8"
    elif path.suffix in (".png", ".jpg", ".jpeg"):
        media = f"image/{path.suffix[1:]}"
    else:
        media = "application/octet-stream"
    return FileResponse(
        task.result_path,
        media_type=media,
        headers={
            "Content-Disposition": f"inline; filename=\"{path.name}\"",
            "Cache-Control": "no-cache",
        },
    )


@app.get("/api/markdown/{task_id}")
async def get_markdown(task_id: str):
    """返回 markdown 原文（前端用 marked.js 渲染）"""
    task = TASKS.get(task_id)
    if not task:
        raise HTTPException(404, "task not found")
    if not task.result_path:
        raise HTTPException(404, "result not ready")
    path = Path(task.result_path)
    if path.suffix == ".md":
        content = path.read_text(encoding="utf-8")
        # 把相对路径 images/xxx.png 转成绝对 URL
        run_dir = path.parent
        # images/page_01.png → /api/file/<task_id>/images/page_01.png
        import re
        content = re.sub(
            r"!\[([^\]]*)\]\(images/([^)]+)\)",
            rf"![\1](/api/file/{task_id}/images/\2)",
            content,
        )
        return JSONResponse({"markdown": content, "title": path.stem})
    elif path.suffix == ".pdf":
        # Plan B 仍然是 PDF，返回标记让前端用 iframe
        return JSONResponse({"markdown": None, "pdf_url": f"/api/preview/{task_id}"})
    return JSONResponse({"markdown": None, "error": "unknown format"})


@app.get("/api/file/{task_id}/{file_path:path}")
async def get_file(task_id: str, file_path: str):
    """访问任务输出目录里的文件（图片等）"""
    task = TASKS.get(task_id)
    if not task:
        raise HTTPException(404, "task not found")
    if not task.result_path:
        raise HTTPException(404, "result not ready")
    # result_path 是 .md 文件，输出目录是它的父目录
    run_dir = Path(task.result_path).parent
    target = (run_dir / file_path).resolve()
    # 安全检查：必须在 run_dir 内
    if not str(target).startswith(str(run_dir)):
        raise HTTPException(403, "forbidden")
    if not target.exists():
        raise HTTPException(404, "file not found")
    if target.suffix == ".png":
        media = "image/png"
    elif target.suffix in (".jpg", ".jpeg"):
        media = "image/jpeg"
    else:
        media = "application/octet-stream"
    return FileResponse(
        str(target),
        media_type=media,
        headers={"Cache-Control": "public, max-age=3600"},
    )


@app.get("/api/zip/{task_id}")
async def download_zip(task_id: str):
    """下载整个绘本 zip 包"""
    task = TASKS.get(task_id)
    if not task:
        raise HTTPException(404, "task not found")
    if not task.result_path:
        raise HTTPException(404, "result not ready")
    run_dir = Path(task.result_path).parent
    # 找 zip
    zips = list(run_dir.glob("*.zip"))
    if not zips:
        # Plan B 没有 zip，返回 PDF
        pdf = task.result_path if task.result_path.endswith(".pdf") else None
        if pdf and Path(pdf).exists():
            return FileResponse(pdf, filename=Path(pdf).name,
                                media_type="application/pdf")
        raise HTTPException(404, "zip not found")
    zip_path = zips[0]
    return FileResponse(
        str(zip_path),
        filename=zip_path.name,
        media_type="application/zip",
    )


if __name__ == "__main__":
    import uvicorn
    host = os.environ.get("DREAMBOOK_HOST", "0.0.0.0")
    port = int(os.environ.get("DREAMBOOK_PORT", 8000))
    print(f"[server] starting on {host}:{port}")
    print(f"[server] open http://localhost:{port}")
    uvicorn.run(app, host=host, port=port, log_level="info")
