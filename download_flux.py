#!/usr/bin/env python3
"""FLUX.1-schnell 下载脚本（modelscope，排除无用单文件版）

Usage:
    python3 download_flux.py
"""
import os, time, sys
from pathlib import Path

# ⭐ 改成 home 目录（/data/models 没写权限）
CACHE_DIR = os.path.expanduser('~/ms_cache')
Path(CACHE_DIR).mkdir(parents=True, exist_ok=True)
os.environ['MODELSCOPE_CACHE'] = CACHE_DIR

from modelscope.hub.snapshot_download import snapshot_download

MODEL_ID = 'AI-ModelScope/FLUX.1-schnell'

print(f"\n{'='*60}")
print(f"开始下载: {MODEL_ID}")
print(f"缓存目录: {CACHE_DIR}")
print(f"预计: ~24GB (已排除 23.8GB 无用单文件 flux1-schnell.safetensors)")
print(f"{'='*60}\n", flush=True)

t0 = time.time()
try:
    path = snapshot_download(
        model_id=MODEL_ID,
        cache_dir=CACHE_DIR,
        allow_patterns=[
            "*.json", "*.txt",
            "transformer/*",
            "text_encoder/*",
            "text_encoder_2/*",
            "vae/*",
            "tokenizer/*",
            "tokenizer_2/*",
            "scheduler/*",
        ],
        ignore_patterns=["flux1-schnell.safetensors", "*.jpeg", "*.png"],
    )
    elapsed = time.time() - t0
    print(f"\n{'='*60}")
    print(f"✅ 下载完成！")
    print(f"路径: {path}")
    print(f"耗时: {elapsed/60:.1f} 分钟")
    print(f"{'='*60}")
    print(f"\n下一步验证模型能跑：")
    print(f"  python3 test_flux.py")
except Exception as e:
    print(f"\n❌ 下载失败: {e}", file=sys.stderr)
    import traceback; traceback.print_exc()
    sys.exit(1)
