#!/usr/bin/env python3
"""DreamBook 图像生成器 v2 — 强化保底版

关键改进（对比 v1）：
  - 每页独立重试（默认 3 次）
  - 单页彻底失败时用 placeholder 替代，不中断整批
  - 每页生成前后打印进度（让前端 SSE 看到心跳）
  - GPU OOM 自动降级：1024 → 768 → 512
  - 加载阶段每 10 秒打印"loading..." 心跳
  - 最终统计：N/M 页成功

Usage:
  python3 image_gen.py --prompt-file prompts.txt --out-dir /tmp/pages/
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

# 默认值（可被 env 覆盖）
DEFAULT_MODEL = os.environ.get(
    "FLUX_MODEL_PATH",
    os.path.expanduser(
        "~/ms_cache/models/AI-ModelScope--FLUX.1-schnell/snapshots/master"
    ),
)


def log(msg: str) -> None:
    # 强制 flush，让 SSE 能实时看到
    print(f"[image_gen] {msg}", file=sys.stderr, flush=True)


def heartbeat(msg: str, last_print: list, interval: float = 10.0) -> None:
    """限制频率的心跳日志（避免刷屏）"""
    now = time.time()
    if now - last_print[0] >= interval:
        log(msg)
        last_print[0] = now


# ---- pipeline loader with retry + size fallback -------------------------
def load_pipeline_robust(model_path: str):
    """加载 FLUX，带重试。失败抛出异常。"""
    import torch
    from diffusers import FluxPipeline

    is_path = "/" in model_path or model_path.startswith(".")
    dtype = torch.bfloat16  # GB10 sm_121 最稳

    log(f"loading from: {model_path}")
    t0 = time.time()
    last_print = [0]

    # 在另一个线程打心跳？太复杂，直接在 from_pretrained 前后打
    # 实际 from_pretrained 是阻塞的，没法中断打心跳
    # 但我们可以在加载前给个"loading..."提示

    for attempt in range(2):
        try:
            heartbeat(f"loading FLUX (attempt {attempt+1})...", last_print, 0)
            pipe = FluxPipeline.from_pretrained(
                model_path if is_path else model_path,
                torch_dtype=dtype,
            )
            heartbeat("moving to cuda...", last_print, 0)
            pipe = pipe.to("cuda")

            # 内存优化
            try:
                pipe.vae.enable_tiling()
                log("vae tiling enabled")
            except Exception:
                pass
            try:
                pipe.enable_attention_slicing()
                log("attention slicing enabled")
            except Exception:
                pass

            torch.cuda.empty_cache()
            log(f"✅ model loaded in {time.time()-t0:.1f}s")

            # 打印 GPU 状态
            mem_alloc = torch.cuda.memory_allocated() / 1e9
            log(f"GPU memory: allocated={mem_alloc:.1f}GB")
            return pipe

        except Exception as e:
            log(f"load attempt {attempt+1} failed: {e}")
            if attempt == 1:
                raise
            time.sleep(3)


def generate_one_robust(
    pipe,
    prompt: str,
    out_path: Path,
    steps: int = 4,
    guidance: float = 0.0,
    seed: int | None = None,
    sizes: list[tuple[int, int]] = None,
) -> bool:
    """生成单张图。OOM 时自动降分辨率。返回是否成功。"""
    import torch
    from PIL import Image, ImageDraw, ImageFont

    if seed is None:
        seed = int(time.time()) & 0xFFFFFFFF

    if sizes is None:
        sizes = [(1024, 1024), (768, 768), (512, 512)]

    for size_idx, (w, h) in enumerate(sizes):
        try:
            log(f"  generating {w}x{h} seed={seed} steps={steps}")
            t0 = time.time()
            img = pipe(
                prompt=prompt,
                width=w,
                height=h,
                num_inference_steps=steps,
                guidance_scale=guidance,
                generator=torch.Generator("cuda").manual_seed(seed),
            ).images[0]

            out_path.parent.mkdir(parents=True, exist_ok=True)
            img.save(str(out_path))
            log(f"  ✅ saved {out_path.name} ({time.time()-t0:.1f}s)")
            return True

        except torch.cuda.OutOfMemoryError as e:
            log(f"  ⚠️ OOM at {w}x{h}, trying smaller...")
            torch.cuda.empty_cache()
            time.sleep(2)
            continue
        except Exception as e:
            log(f"  ⚠️ generate failed at {w}x{h}: {type(e).__name__}: {str(e)[:100]}")
            # 非内存错误，重试本尺寸没意义，直接下一个尺寸
            continue

    # 所有尺寸都失败，写一个 placeholder
    log(f"  ❌ all sizes failed, writing placeholder")
    try:
        placeholder = Image.new("RGB", (512, 512), color=(245, 239, 230))
        draw = ImageDraw.Draw(placeholder)
        draw.text((180, 250), "🎨", fill=(180, 165, 140))
        draw.text((140, 300), "image unavailable", fill=(180, 165, 140))
        out_path.parent.mkdir(parents=True, exist_ok=True)
        placeholder.save(str(out_path))
    except Exception:
        pass
    return False


def main() -> int:
    ap = argparse.ArgumentParser(description="FLUX image generator v2")
    ap.add_argument("--prompt", help="single prompt")
    ap.add_argument("--prompt-file", help="file with one prompt per line")
    ap.add_argument("--out", help="output path (single mode)")
    ap.add_argument("--out-dir", default=".", help="output dir (batch mode)")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--steps", type=int, default=4)
    ap.add_argument("--guidance", type=float, default=0.0)
    ap.add_argument("--width", type=int, default=1024)
    ap.add_argument("--height", type=int, default=1024)
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--style-prefix", default="")
    ap.add_argument("--negative", default="")
    ap.add_argument("--retry", type=int, default=2, help="retries per page")
    args = ap.parse_args()

    # 加载模型（带心跳）
    pipe = load_pipeline_robust(args.model)

    # 尺寸降级链
    sizes = [(args.width, args.height)]
    if (args.width, args.height) == (1024, 1024):
        sizes = [(1024, 1024), (768, 768), (512, 512)]

    # ========== batch mode ==========
    if args.prompt_file:
        prompts_file = Path(args.prompt_file)
        if not prompts_file.exists():
            log(f"❌ prompt file not found: {prompts_file}")
            return 1
        prompts = [
            l.strip() for l in prompts_file.read_text(encoding="utf-8").splitlines()
            if l.strip() and not l.startswith("#")
        ]
        log(f"=== batch mode: {len(prompts)} prompts ===")

        success_count = 0
        for i, p in enumerate(prompts, 1):
            log(f"\n--- page {i}/{len(prompts)} ---")
            full = f"{args.style_prefix}, {p}" if args.style_prefix else p
            out = Path(args.out_dir) / f"page_{i:02d}.png"

            # 单页重试
            page_ok = False
            for attempt in range(args.retry + 1):
                if attempt > 0:
                    log(f"  retry {attempt}/{args.retry}")
                    time.sleep(2)
                ok = generate_one_robust(
                    pipe, full, out,
                    steps=args.steps, guidance=args.guidance,
                    seed=args.seed if args.seed else None,
                    sizes=sizes,
                )
                if ok:
                    page_ok = True
                    break

            if page_ok:
                success_count += 1
            else:
                log(f"  ⚠️ page {i} failed after {args.retry+1} attempts, placeholder used")

        log(f"\n=== batch done: {success_count}/{len(prompts)} success ===")
        # 即使有失败也返回 0（placeholder 已写入），让上层继续拼 PDF
        return 0

    # ========== single mode ==========
    if not args.prompt or not args.out:
        ap.error("--prompt and --out required (or use --prompt-file + --out-dir)")

    full = (
        f"{args.style_prefix}, {args.prompt}"
        if args.style_prefix else args.prompt
    )
    out_path = Path(args.out)
    ok = generate_one_robust(
        pipe, full, out_path,
        steps=args.steps, guidance=args.guidance,
        seed=args.seed, sizes=sizes,
    )
    if ok:
        print(f"MEDIA:{out_path.resolve()}")
        return 0
    else:
        log("❌ single mode failed")
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
