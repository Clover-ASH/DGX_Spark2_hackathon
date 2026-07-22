#!/usr/bin/env python3
"""DreamBook Router — A+B 合体的统一入口

智能路由：
  - 有照片 → 走绘本（Plan A：FLUX 出图 + PDF）
  - 没照片 → 走蓝图（Plan B：5 Agent 协作 + PDF）

两者共享同一个 dream 输入，输出都是精美 PDF。

Usage:
  # 有照片 → 绘本
  python3 dreambook_router.py --dream "我想成为宇航员" --style pixar --face /path/to/child.jpg

  # 没照片 → 蓝图
  python3 dreambook_router.py --dream "我想成为宇航员" --name 小明 --age 8

  # 自动判断（推荐）
  python3 dreambook_router.py --dream "我想成为宇航员"  # 无 --face 自动走 Plan B
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent

# A: 绘本
DREAMBOOK_A = SCRIPT_DIR / "dreambook" / "dreambook_diffusers.py"
# B: 蓝图
DREAMBOOK_B = SCRIPT_DIR / "dreambook_planb" / "dream_blueprint.py"

PYTHON_BIN = os.environ.get(
    "DREAMBOOK_PYTHON",
    "python3",
)


def log(msg: str) -> None:
    print(f"[router] {msg}", file=sys.stderr, flush=True)


def has_face_image(face_path: str | None) -> bool:
    """Check if a usable face image is provided."""
    if not face_path:
        return False
    p = Path(face_path)
    return p.is_file() and p.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}


def run_plan_a(args) -> int:
    """绘本方案：FLUX + PuLID(后续) + PDF"""
    import subprocess

    log("=" * 60)
    log("📚 启动 Plan A：梦想绘本（FLUX 出图）")
    log(f"   梦想: {args.dream}")
    log(f"   风格: {args.style}")
    log(f"   照片: {args.face}")
    log("=" * 60)

    cmd = [
        PYTHON_BIN,
        str(DREAMBOOK_A),
        "--dream", args.dream,
        "--style", args.style,
    ]
    if args.face:
        cmd += ["--face", args.face]
    if args.title:
        cmd += ["--title", args.title]
    if args.custom_prompt:
        cmd += ["--custom-prompt", args.custom_prompt]

    t0 = time.time()
    proc = subprocess.run(cmd)
    elapsed = time.time() - t0
    log(f"Plan A 完成，耗时 {elapsed/60:.1f} 分钟")
    return proc.returncode


def run_plan_b(args) -> int:
    """蓝图方案：5 Agent 协作 + PDF"""
    import subprocess

    log("=" * 60)
    log("📖 启动 Plan B：梦想蓝图（5 Agent 协作）")
    log(f"   梦想: {args.dream}")
    if args.name:
        log(f"   名字: {args.name}")
    if args.age:
        log(f"   年龄: {args.age}")
    log("=" * 60)

    cmd = [
        PYTHON_BIN,
        str(DREAMBOOK_B),
        "--dream", args.dream,
    ]
    if args.name:
        cmd += ["--name", args.name]
    if args.age:
        cmd += ["--age", str(args.age)]

    t0 = time.time()
    proc = subprocess.run(cmd)
    elapsed = time.time() - t0
    log(f"Plan B 完成，耗时 {elapsed/60:.1f} 分钟")
    return proc.returncode


def main() -> int:
    ap = argparse.ArgumentParser(
        description="DreamBook Router — 梦想绘本/蓝图 智能入口"
    )
    ap.add_argument("--dream", required=True, help='e.g. "我想成为宇航员"')

    # 路由判断
    ap.add_argument("--face", help="孩子照片路径（提供则走绘本 A）")

    # A 专用
    ap.add_argument("--style", default="pixar",
                    help="绘本风格: pixar|ghibli|watercolor|oil_painting|comic|custom_1|custom_2")
    ap.add_argument("--title", help="绘本标题")
    ap.add_argument("--custom-prompt", help="自定义风格提示词")

    # B 专用
    ap.add_argument("--name", help="主角名字（蓝图用）")
    ap.add_argument("--age", type=int, help="主角年龄（蓝图用）")

    # 强制选择
    ap.add_argument("--force", choices=["a", "b"],
                    help="强制走 A 或 B，跳过自动判断")

    args = ap.parse_args()

    # 智能路由
    if args.force:
        plan = args.force
    elif has_face_image(args.face):
        plan = "a"
    else:
        plan = "b"

    log(f"智能路由决策：→ Plan {plan.upper()}")
    if plan == "a" and not has_face_image(args.face) and not args.force:
        log("(没有照片但你想走 A？加 --force a)")

    if plan == "a":
        return run_plan_a(args)
    else:
        return run_plan_b(args)


if __name__ == "__main__":
    sys.exit(main())
