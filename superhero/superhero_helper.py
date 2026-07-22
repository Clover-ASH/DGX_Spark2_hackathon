#!/usr/bin/env python3
"""Superhero Photo Generator — diffusers backend (FLUX.1-schnell on DGX Spark).

等效实现 OpenClaw workshop 的 superhero skill，但后端从 ComfyUI HTTP API
换成 diffusers 直跑 FLUX（本节点无 ComfyUI，但有完整的 FLUX.1-schnell +
reid env 的 diffusers 0.39 + torch 2.9.1+cu130，已在 GB10 sm_121 验证可跑）。

不依赖 PuLID（节点未安装），因此不保证人脸身份一致性；FLUX 根据文本 prompt
生成超级英雄风格肖像。若需要"脸像本人"，需另装 PuLID-Flux。

Pipeline:
  1. 解析用户输入：一句话描述（可选）+ 人脸图（可选，当前不参与生成）。
  2. 若给了描述 → 调 Ollama qwen3.6 把中文/口语描述扩写成 FLUX 英文 prompt；
     若没给 → 用内置默认超级英雄 prompt。
  3. 用 FLUX.1-schnell（bf16，4 步）生成 1024×1024 图，OOM 自动降级到 768/512。
  4. 保存 PNG，打印 `MEDIA:<绝对路径>`（对齐 OpenClaw rich-output 协议）。

Usage:
  superhero_helper.py                       # 默认超级英雄 prompt
  superhero_helper.py --desc "飞行的钢铁侠"  # LLM 扩写
  superhero_helper.py --prompt "<英文prompt>"  # 直接用，跳过 LLM

Environment:
  FLUX_MODEL_PATH — FLUX 模型目录（默认 ~/ms_cache/.../FLUX.1-schnell/.../master）
  OLLAMA_URL      — 默认 http://127.0.0.1:11434
  OLLAMA_MODEL    — 默认 qwen3.6:35b-a3b-q4_K_M
  SUPERHERO_OUT   — 输出目录（默认 ~/superhero_output）
"""

from __future__ import annotations

import argparse
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

# 没给描述时的兜底 prompt（对齐 notebook 节点 7 的正向 prompt）
DEFAULT_PROMPT = (
    "Dynamic action shot of a superhero flying over a sunlit city, wearing a "
    "bright white and green suit with a full flowing white and green cape, face "
    "clearly visible, looking forward with confident heroic expression, arms "
    "slightly forward in flight pose, golden afternoon sunlight, soft rim "
    "lighting on face, shallow depth of field background, city buildings below, "
    "white clouds, cinematic color grading, sharp facial details, photorealistic, 8k"
)


def log(msg: str) -> None:
    print(f"[superhero] {msg}", file=sys.stderr, flush=True)


def llm_expand_prompt(desc: str) -> str:
    """用 Ollama qwen3.6 把用户的口语描述扩写成 FLUX 英文 prompt。

    qwen3.6 默认把答案塞进 thinking 字段，content 为空，所以必须 think:false。
    失败时回退到"默认 prompt + 用户描述拼接"，不中断流程。
    """
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
    try:
        log(f"asking {OLLAMA_MODEL} to expand: {desc!r}")
        r = requests.post(f"{OLLAMA_URL}/api/chat", json=payload, timeout=90)
        r.raise_for_status()
        content = r.json().get("message", {}).get("content", "").strip()
        # 去掉可能的引号/换行
        content = content.strip('"`').strip().replace("\n", " ")
        if content:
            log(f"LLM prompt: {content[:120]}...")
            return content
        log("LLM returned empty content, fallback")
    except Exception as e:
        log(f"LLM expand failed ({e}), fallback to default + desc")
    return f"superhero: {desc}, cinematic, photorealistic, 8k"


def load_pipeline(model_path: str):
    """加载 FLUX.1-schnell 到 cuda（bf16，GB10 sm_121 已验证可跑）。"""
    import torch
    from diffusers import FluxPipeline

    log(f"loading FLUX from: {model_path}")
    t0 = time.time()
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
    log(f"✅ model loaded in {time.time()-t0:.1f}s "
        f"(GPU {torch.cuda.memory_allocated()/1e9:.1f}GB allocated)")
    return pipe


def generate(pipe, prompt: str, out_path: Path,
             steps: int = 4, seed: int | None = None) -> bool:
    """生成一张图，OOM 自动降分辨率。返回是否成功。"""
    import torch

    if seed is None:
        seed = int(time.time()) & 0xFFFFFFFF

    for (w, h) in [(1024, 1024), (768, 768), (512, 512)]:
        try:
            log(f"generating {w}x{h} seed={seed} steps={steps}")
            t0 = time.time()
            img = pipe(
                prompt=prompt,
                width=w, height=h,
                num_inference_steps=steps,
                guidance_scale=0.0,
                generator=torch.Generator("cuda").manual_seed(seed),
            ).images[0]
            out_path.parent.mkdir(parents=True, exist_ok=True)
            img.save(str(out_path))
            log(f"✅ saved {out_path.name} ({time.time()-t0:.1f}s)")
            return True
        except torch.cuda.OutOfMemoryError:
            log(f"⚠️ OOM at {w}x{h}, trying smaller...")
            torch.cuda.empty_cache()
            time.sleep(2)
        except Exception as e:
            log(f"⚠️ generate failed at {w}x{h}: {type(e).__name__}: {str(e)[:120]}")
            continue
    return False


def main() -> int:
    ap = argparse.ArgumentParser(description="Superhero photo generator (FLUX diffusers)")
    ap.add_argument("--desc", help="hero description in any language (LLM 扩写为 prompt)")
    ap.add_argument("--prompt", help="direct FLUX prompt (skip LLM)")
    ap.add_argument("--face", help="face image path (accepted for compat; 不参与生成)")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--out", help="output png path (default: <OUT>/superhero_<ts>.png)")
    ap.add_argument("--steps", type=int, default=4)
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--no-llm", action="store_true", help="skip LLM, use default prompt")
    args = ap.parse_args()

    # 1. 决定 prompt
    if args.prompt:
        prompt = args.prompt
        log(f"using direct prompt")
    elif args.desc and not args.no_llm:
        prompt = llm_expand_prompt(args.desc)
    else:
        prompt = DEFAULT_PROMPT
        log("using default superhero prompt")

    log(f"final prompt: {prompt[:150]}")

    # 2. 加载 + 出图
    pipe = load_pipeline(args.model)

    out_dir = Path(DEFAULT_OUT)
    if args.out:
        out_path = Path(args.out)
    else:
        out_dir.mkdir(parents=True, exist_ok=True)
        ts = time.strftime("%Y%m%d_%H%M%S")
        out_path = out_dir / f"superhero_{ts}.png"

    ok = generate(pipe, prompt, out_path, steps=args.steps, seed=args.seed)
    if ok:
        abs_path = out_path.resolve()
        log(f"done: {abs_path}")
        print(f"MEDIA:{abs_path}")
        return 0
    log("❌ generation failed at all sizes")
    return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        log("interrupted")
        sys.exit(130)
    except Exception as e:
        log(f"FATAL: {type(e).__name__}: {e}")
        traceback.print_exc()
        sys.exit(1)
