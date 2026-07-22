#!/usr/bin/env python3
"""Superhero 常驻服务 — 模型只加载一次，后续请求秒级出图。

为 demo 录制设计：避免每次出图都重新加载 FLUX（~150s）。
启动时加载 FLUX.1-schnell 到 GPU 常驻，提供 HTTP 接口：
  GET /health        健康检查 + 是否就绪
  GET /generate?desc=...   LLM 扩写 + FLUX 出图，返回 {media, prompt, elapsed}
  GET /generate?prompt=... 跳过 LLM，直接出图

Usage:
  python3 superhero_server.py --port 8765
  # 后台启动: nohup ... &  ，日志写 /tmp/superhero_server.log
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import traceback
from pathlib import Path

os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

DEFAULT_MODEL = os.environ.get(
    "FLUX_MODEL_PATH",
    os.path.expanduser(
        "~/ms_cache/models/AI-ModelScope--FLUX.1-schnell/snapshots/master"
    ),
)
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen3.6:35b-a3b-q4_K_M")
DEFAULT_OUT = os.environ.get(
    "SUPERHERO_OUT", os.path.expanduser("~/superhero_output")
)

DEFAULT_PROMPT = (
    "Dynamic action shot of a superhero flying over a sunlit city, wearing a "
    "bright white and green suit with a full flowing white and green cape, face "
    "clearly visible, looking forward with confident heroic expression, arms "
    "slightly forward in flight pose, golden afternoon sunlight, soft rim "
    "lighting on face, shallow depth of field background, city buildings below, "
    "white clouds, cinematic color grading, sharp facial details, photorealistic, 8k"
)

# ---- 全局 pipeline（启动时加载一次）----
PIPE = None
PIPE_READY = False
LOAD_ERROR = None


def log(msg: str) -> None:
    print(f"[server] {msg}", flush=True)


def llm_expand(desc: str) -> str:
    import requests
    sys_p = (
        "You are a prompt engineer for FLUX.1 image model. Given a short hero "
        "description (any language), output ONE single English prompt line: a "
        "vivid, photorealistic superhero action shot. No explanation, no quotes, "
        "no markdown. Keep face visible. 60-100 words."
    )
    payload = {
        "model": OLLAMA_MODEL,
        "messages": [
            {"role": "system", "content": sys_p},
            {"role": "user", "content": f"Hero description: {desc}"},
        ],
        "stream": False,
        "think": False,
        "options": {"temperature": 0.7},
    }
    r = requests.post(f"{OLLAMA_URL}/api/chat", json=payload, timeout=90)
    r.raise_for_status()
    content = r.json().get("message", {}).get("content", "").strip()
    content = content.strip('"`').strip().replace("\n", " ")
    return content if content else f"superhero: {desc}, cinematic, photorealistic, 8k"


def load_pipeline(model_path: str):
    """启动时加载 FLUX 常驻。"""
    global PIPE_READY, LOAD_ERROR
    import torch
    from diffusers import FluxPipeline

    log(f"loading FLUX from: {model_path} (一次性，约 150s)")
    t0 = time.time()
    try:
        pipe = FluxPipeline.from_pretrained(model_path, torch_dtype=torch.bfloat16)
        pipe = pipe.to("cuda")
        try:
            pipe.vae.enable_tiling()
        except Exception:
            pass
        try:
            pipe.enable_attention_slicing()
        except Exception:
            pass
        torch.cuda.empty_cache()
        log(f"✅ FLUX ready in {time.time()-t0:.1f}s "
            f"(GPU {torch.cuda.memory_allocated()/1e9:.1f}GB)")
        return pipe
    except Exception as e:
        LOAD_ERROR = f"{type(e).__name__}: {e}"
        log(f"❌ load failed: {LOAD_ERROR}")
        raise


def generate(pipe, prompt: str, out_path: Path, seed: int | None = None) -> bool:
    import torch
    if seed is None:
        seed = int(time.time()) & 0xFFFFFFFF
    for (w, h) in [(1024, 1024), (768, 768), (512, 512)]:
        try:
            img = pipe(
                prompt=prompt, width=w, height=h,
                num_inference_steps=4, guidance_scale=0.0,
                generator=torch.Generator("cuda").manual_seed(seed),
            ).images[0]
            out_path.parent.mkdir(parents=True, exist_ok=True)
            img.save(str(out_path))
            return True
        except torch.cuda.OutOfMemoryError:
            log(f"OOM at {w}x{h}, trying smaller")
            torch.cuda.empty_cache()
            time.sleep(2)
        except Exception as e:
            log(f"generate failed at {w}x{h}: {e}")
            continue
    return False


def main() -> int:
    global PIPE, PIPE_READY
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--model", default=DEFAULT_MODEL)
    args = ap.parse_args()

    # 启动时加载（阻塞，加载完才开始服务）
    PIPE = load_pipeline(args.model)
    PIPE_READY = True

    # 用标准库 http.server，无需额外依赖
    from http.server import BaseHTTPRequestHandler, HTTPServer
    from urllib.parse import urlparse, parse_qs

    class Handler(BaseHTTPRequestHandler):
        def _json(self, code, obj):
            body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, fmt, *a):
            pass  # 静默默认日志，用我们自己的 log

        def do_GET(self):
            u = urlparse(self.path)
            if u.path == "/health":
                self._json(200, {"ready": PIPE_READY, "error": LOAD_ERROR})
                return
            if u.path == "/generate":
                q = parse_qs(u.query)
                desc = (q.get("desc", [""])[0]).strip()
                prompt = (q.get("prompt", [""])[0]).strip()
                seed = q.get("seed", [None])[0]
                seed = int(seed) if seed else None
                if not PIPE_READY:
                    self._json(503, {"error": "model not ready"})
                    return
                try:
                    t0 = time.time()
                    used_llm = False
                    if prompt:
                        final = prompt
                    elif desc:
                        log(f"LLM expanding: {desc!r}")
                        final = llm_expand(desc)
                        used_llm = True
                        log(f"LLM prompt: {final[:100]}...")
                    else:
                        final = DEFAULT_PROMPT
                    ts = time.strftime("%Y%m%d_%H%M%S")
                    out_dir = Path(DEFAULT_OUT)
                    out_dir.mkdir(parents=True, exist_ok=True)
                    out_path = out_dir / f"superhero_{ts}.png"
                    ok = generate(PIPE, final, out_path, seed=seed)
                    elapsed = time.time() - t0
                    if ok:
                        log(f"✅ {out_path.name} ({elapsed:.1f}s)")
                        self._json(200, {
                            "media": str(out_path.resolve()),
                            "prompt": final,
                            "used_llm": used_llm,
                            "elapsed": round(elapsed, 1),
                        })
                    else:
                        self._json(500, {"error": "generation failed at all sizes"})
                except Exception as e:
                    log(f"ERROR: {e}")
                    self._json(500, {"error": str(e)})
                return
            self._json(404, {"error": "not found"})

    log(f"HTTP service on http://127.0.0.1:{args.port}  [/health /generate]")
    HTTPServer(("127.0.0.1", args.port), Handler).serve_forever()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        log("interrupted")
        sys.exit(130)
    except Exception as e:
        log(f"FATAL: {e}")
        traceback.print_exc()
        sys.exit(1)
