#!/usr/bin/env python3
"""DreamBook 主流水线 — diffusers 版本（不依赖 ComfyUI）

对比 dreambook_helper.py 的改动：
  - 去掉 ComfyUI HTTP API 调用
  - 直接 from diffusers import FluxPipeline
  - 模型只加载一次，6 页复用（速度快 5 倍）
  - 不需要 PuLID（简化版，靠详细 prompt 保持角色一致性）
  - 用 modelscope 缓存路径

Pipeline:
  1. Ollama 生成 6 页故事
  2. 加载 FLUX pipeline（一次性）
  3. 循环 6 次：scene_description → FLUX 出图
  4. 拼装 PDF
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import shutil
import sys
import time
from pathlib import Path

import requests

# ---- paths ---------------------------------------------------------------
SCRIPT_DIR = Path(__file__).resolve().parent
STYLES_DIR = SCRIPT_DIR / "styles"
PDF_ASSEMBLER = SCRIPT_DIR / "pdf_assembler.py"
MARKDOWN_ASSEMBLER = SCRIPT_DIR / "markdown_assembler.py"
IMAGE_GEN = SCRIPT_DIR / "image_gen.py"

# 输出到 home 下，OpenClaw 能读到
HOME = Path.home()
PUBLISH_DIR = HOME / "dreambook_output"

# ---- model config --------------------------------------------------------
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "nemotron-3-nano:30b")  # ⭐ NVIDIA 自家模型
FLUX_MODEL_PATH = os.environ.get(
    "FLUX_MODEL_PATH",
    os.path.expanduser(
        "~/ms_cache/models/AI-ModelScope--FLUX.1-schnell/snapshots/master"
    ),
)
PYTHON_BIN = os.environ.get(
    "DREAMBOOK_PYTHON",
    "python3"
)

DEFAULT_NEGATIVE = (
    "ugly, deformed, blurry, low quality, watermark, text, logo, "
    "bad anatomy, extra limbs, disfigured, scary, horror, gore, adult, nsfw"
)


def log(msg: str) -> None:
    print(f"[dreambook] {msg}", file=sys.stderr, flush=True)


# ---- style ---------------------------------------------------------------
def load_style(style_name: str, custom_prompt: str | None) -> dict:
    path = STYLES_DIR / f"{style_name}.json"
    if not path.exists():
        available = sorted(p.stem for p in STYLES_DIR.glob("*.json"))
        raise SystemExit(
            f"style '{style_name}' not found. Available: {available}"
        )
    style = json.loads(path.read_text(encoding="utf-8"))

    if style.get("is_custom"):
        if custom_prompt:
            style["prompt_prefix"] = custom_prompt.strip()
            path.write_text(
                json.dumps(style, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            log(f"saved custom prompt to {path}")
        if not style.get("prompt_prefix"):
            raise SystemExit(
                f"style '{style_name}' is a custom slot but has no prompt. "
                f"Pass --custom-prompt on first use."
            )
    return style


# ---- LLM story generation ------------------------------------------------
STORY_SYS_PROMPT = """你是一位顶级儿童绘本作家。你的任务是把"我想成为 XXX"这个梦想，
拆解成一本 {pages} 页的儿童绘本，每一页都展示主角追寻梦想的一个成长瞬间。

主角是一个真实存在的小孩（用户的照片），你要让每一页的画面都包含这个孩子，
并且通过 6 页展现一个完整的、有起伏的、温暖励志的成长故事。

只输出 JSON，不要任何额外解释、不要 markdown 代码块。JSON 结构：
{{
  "title": "绘本标题（中文，8字内）",
  "pages": [
    {{
      "page": 1,
      "scene_description": "用英文写一段详细的画面描述，供文生图模型使用。必须包含主角这个孩子，描述他的动作、表情、服装、场景、光线。80-120 词。",
      "story_text": "这一页的中文旁白文字，儿童文学风格，2-3 句话，30-60 字。"
    }}
  ]
}}"""

STORY_USER_TEMPLATE = """梦想主题：{dream}
绘本风格（仅作故事氛围参考）：{style_label}

请生成 {pages} 页绘本结构。

要求：
1. 第 1 页：孩子怀揣梦想的初始场景（天真、期待）。
2. 中间页：遇到挑战、努力学习、获得帮助、突破自我。
3. 最后一页：梦想成真或成长时刻（温暖、励志）。
4. 每页 scene_description 必须是英文，必须包含 "a child" 或 "the young boy/girl"，
   描述孩子外貌（正面、可见脸）、动作、服装、场景细节、光线氛围。
5. 不要在 scene_description 里写"photorealistic"——文生图风格由系统注入。
6. story_text 用温暖、有节奏感的中文，适合 4-8 岁孩子听。"""


def generate_story(
    dream: str, style_label: str, pages: int, title_override: str | None
) -> dict:
    sys_prompt = STORY_SYS_PROMPT.format(pages=pages)
    user_prompt = STORY_USER_TEMPLATE.format(
        dream=dream, style_label=style_label, pages=pages
    )

    log(f"asking {OLLAMA_MODEL} to write {pages}-page story…")
    resp = requests.post(
        f"{OLLAMA_URL}/api/chat",
        json={
            "model": OLLAMA_MODEL,
            "messages": [
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "stream": False,
            "think": False,        # 关闭 reasoning 模式（workshop 教训）
            "options": {"temperature": 0.9, "num_predict": 2500},
        },
        timeout=300,
    )
    resp.raise_for_status()
    content = resp.json()["message"]["content"].strip()
    story = parse_story_json(content, pages)

    if title_override:
        story["title"] = title_override
    log(f"story ready: title='{story['title']}', {len(story['pages'])} pages")
    return story


def parse_story_json(raw: str, pages: int) -> dict:
    """Best-effort extract JSON from LLM output."""
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
    if m:
        raw = m.group(1)
    if not raw.startswith("{"):
        start = raw.find("{")
        end = raw.rfind("}")
        if start >= 0 and end > start:
            raw = raw[start : end + 1]
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise SystemExit(f"LLM did not return valid JSON: {e}\nraw:\n{raw[:500]}")
    if "pages" not in data or not isinstance(data["pages"], list):
        raise SystemExit(f"LLM JSON missing 'pages': {data}")
    data["pages"] = data["pages"][:pages]
    while len(data["pages"]) < pages:
        data["pages"].append(
            {
                "page": len(data["pages"]) + 1,
                "scene_description": "a child smiling, warm soft light, "
                "children's book illustration",
                "story_text": "梦想，正在一点点发光。",
            }
        )
    if "title" not in data:
        data["title"] = "我的梦想绘本"
    return data


# ---- image generation via diffusers (called as subprocess) ---------------
def generate_images_batch(
    story: dict,
    style: dict,
    run_dir: Path,
) -> list[Path | None]:
    """Generate all page images by calling image_gen.py with --prompt-file."""
    import subprocess

    # 1) write prompts to file
    prompts_file = run_dir / "prompts.txt"
    style_prefix = style.get("prompt_prefix", "")
    lines = []
    for page in story["pages"]:
        scene = page.get("scene_description", "")
        full = (
            f"{style_prefix}, {scene}, children's picture book illustration, "
            f"clear visible face, consistent character"
        )
        lines.append(full)
    prompts_file.write_text("\n".join(lines), encoding="utf-8")
    log(f"prompts written to {prompts_file} ({len(lines)} pages)")

    # 2) call image_gen.py with batch mode
    # ⚠️ FLUX-schnell 训练用 4 步，超过反而质量下降 + 速度慢 6 倍
    # 强制用 4 步，忽略 style.json 里的 steps（那是给 dev 用的）
    cmd = [
        PYTHON_BIN,
        str(IMAGE_GEN),
        "--prompt-file", str(prompts_file),
        "--out-dir", str(run_dir),
        "--model", FLUX_MODEL_PATH,
        "--steps", "4",           # ⭐ schnell 固定 4 步
        "--guidance", "0.0",      # schnell 必须用 0
        "--width", "1024",
        "--height", "1024",
        "--retry", "2",           # 单页失败重试 2 次
    ]
    log(f"calling: {' '.join(cmd[:6])}...")
    log("⚠️  模型加载约需 2-3 分钟，期间无输出是正常的，请耐心等待")
    # ⭐ 关键：不要 capture_output，让子进程直接打印到当前终端
    # 这样你能看到 [image_gen] 的实时进度
    proc = subprocess.run(cmd)
    if proc.returncode != 0:
        log(f"image_gen FAILED (exit {proc.returncode})")
        # 但即使 returncode != 0，可能有部分图生成了
    else:
        log(f"image_gen done")

    # 3) collect page images
    images: list[Path | None] = []
    for i in range(1, len(story["pages"]) + 1):
        p = run_dir / f"page_{i:02d}.png"
        images.append(p if p.exists() else None)
    return images


# ---- Markdown 装配（取代 PDF） -------------------------------------------
def assemble_markdown(story: dict, run_dir: Path) -> Path | None:
    """把 6 张图 + 故事拼成 markdown 绘本 + zip 包。返回 .md 路径。"""
    import subprocess

    if not MARKDOWN_ASSEMBLER.exists():
        log(f"markdown_assembler not found at {MARKDOWN_ASSEMBLER}")
        return None

    # 先写 story.json（图片在 run_dir 里，名字是 page_XX.png）
    meta_path = run_dir / "story.json"
    meta_path.write_text(
        json.dumps(story, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    cmd = [
        PYTHON_BIN,
        str(MARKDOWN_ASSEMBLER),
        "--story-json", str(meta_path),
        "--image-dir", str(run_dir),       # page_01.png 等就在这里
        "--run-dir", str(run_dir),         # 输出根目录
    ]
    log(f"assembling markdown绘本...")
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        log(f"markdown_assembler FAILED: {proc.stderr[-500:]}")
        return None

    # 解析输出：MD_OK:/path/to/绘本.md
    import re
    m = re.search(r"MD_OK:(.+)$", proc.stdout, re.MULTILINE)
    if m:
        md_path = Path(m.group(1).strip())
        log(f"✅ markdown 装配完成: {md_path}")
        return md_path
    log(f"markdown_assembler 输出异常: {proc.stdout}")
    return None


# ---- main ----------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser(description="DreamBook (diffusers version)")
    ap.add_argument("--dream", required=True)
    ap.add_argument("--style", required=True)
    ap.add_argument("--pages", type=int, default=6)
    ap.add_argument("--title")
    ap.add_argument("--custom-prompt")
    args = ap.parse_args()

    style = load_style(args.style, args.custom_prompt)

    # 1) output dir
    ts = time.strftime("%Y%m%d_%H%M%S")
    run_dir = PUBLISH_DIR / f"dreambook_{ts}"
    run_dir.mkdir(parents=True, exist_ok=True)

    # 2) generate story
    story = generate_story(args.dream, style["label"], args.pages, args.title)

    # 3) generate images
    log("=" * 50)
    log("开始出图 (FLUX-schnell, 4 步/页, 预计 1-2 分钟)")
    log("=" * 50)
    images = generate_images_batch(story, style, run_dir)
    success = sum(1 for i in images if i)
    log(f"出图完成: {success}/{len(images)} 张成功")

    # 4) 装配 markdown 绘本 + zip 包
    log("assembling markdown绘本...")
    md_path = assemble_markdown(story, run_dir)

    log(f"DONE: {run_dir}")
    # OpenClaw MEDIA protocol - 输出 markdown 路径
    if md_path and md_path.exists():
        print(f"MEDIA:{md_path}")
    elif any(images):
        print(f"MEDIA:{[i for i in images if i][0]}")
    else:
        print(f"RUN_DIR:{run_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
