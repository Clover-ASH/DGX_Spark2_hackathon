#!/usr/bin/env python3
"""FLUX 单图测试 — 下载完用这个验证 GB10 上能跑

Usage:
    python3 test_flux.py
"""
import torch, time, sys, os
from pathlib import Path
from diffusers import FluxPipeline

MODEL_PATH = os.path.expanduser(
    "~/ms_cache/models/AI-ModelScope--FLUX.1-schnell/snapshots/master"
)

if not Path(MODEL_PATH).exists():
    print(f"❌ 模型路径不存在: {MODEL_PATH}")
    print("请先跑 download_flux.py 下载模型")
    sys.exit(1)

print(f"loading FLUX from {MODEL_PATH}...", flush=True)
t0 = time.time()
pipe = FluxPipeline.from_pretrained(MODEL_PATH, torch_dtype=torch.bfloat16)
pipe = pipe.to("cuda")

# 内存优化（GB10 必开）
pipe.vae.enable_tiling()
pipe.enable_attention_slicing()
torch.cuda.empty_cache()
print(f"loaded in {time.time()-t0:.1f}s", flush=True)

# 打印 GPU 显存
mem_alloc = torch.cuda.memory_allocated() / 1e9
mem_reserved = torch.cuda.memory_reserved() / 1e9
print(f"GPU memory: allocated={mem_alloc:.1f}GB, reserved={mem_reserved:.1f}GB")

print(f"\ngenerating test image...", flush=True)
t1 = time.time()
try:
    img = pipe(
        prompt="a brave child astronaut floating in space, earth in background, "
               "cinematic, vibrant colors, children's book illustration, "
               "clear visible face, soft lighting, pixar style",
        width=1024, height=1024,
        num_inference_steps=4,
        guidance_scale=0.0,
        generator=torch.Generator("cuda").manual_seed(42),
    ).images[0]
    img.save("/tmp/flux_test.png")
    print(f"\n{'='*60}")
    print(f"✅ 生成成功！耗时: {time.time()-t1:.1f}s")
    print(f"✅ 图片: /tmp/flux_test.png  尺寸: {img.size}")
    print(f"{'='*60}")
    print(f"\n🎉 FLUX 在 GB10 上跑通了！现在可以跑完整 dreambook。")
except Exception as e:
    print(f"\n❌ 生成失败: {type(e).__name__}: {e}", file=sys.stderr)
    import traceback; traceback.print_exc()
    sys.exit(1)
