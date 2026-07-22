#!/usr/bin/env python3
"""DreamBook skill helper — 「我想成为 XXX」童年梦想绘本生成器。

Pipeline:
  1. 读取风格 JSON（5 预设 + 2 自定义），决定 prompt 前缀。
  2. 调 Ollama Qwen3.6 创作 6 页故事，每页 = {scene_description, story_text}。
     scene_description 喂给 FLUX 出图，story_text 印到 PDF 上。
  3. 循环 6 次：把用户孩子照片 + 当前页 scene_description + 风格前缀 → ComfyUI。
     PuLID 保证 6 页都是同一张孩子脸。
  4. 调 pdf_assembler 把 6 张图 + 6 段文字 + 封面拼成 PDF。
  5. 打印 MEDIA:<pdf> 让 OpenClaw 内联预览。

Usage:
  dreambook_helper.py --dream "我想成为宇航员" --style pixar
                      [--face <path>] [--pages 6] [--title "..."]
                      [--custom-prompt "..."]

Env:
  WORKSHOP_DIR    bundle root (auto-detected if unset)
  OPENCLAW_HOME   OpenClaw home (auto-detected if unset)
  COMFYUI_URL     default http://127.0.0.1:8200
  OLLAMA_URL      default http://127.0.0.1:11434
  OLLAMA_MODEL    default qwen3.6:35b
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
from typing import Any

import requests

# ---- paths ---------------------------------------------------------------
WORKSHOP_DIR = Path(
    os.environ.get("WORKSHOP_DIR", Path(__file__).resolve().parents[4])
).resolve()
OPENCLAW_HOME = Path(
    os.environ.get("OPENCLAW_HOME", WORKSHOP_DIR / "openclaw-home")
).resolve()
SCRIPT_DIR = Path(__file__).resolve().parent
STYLES_DIR = SCRIPT_DIR / "styles"
WORKFLOW_FILE = SCRIPT_DIR / "book_workflow.json"
PDF_ASSEMBLER = SCRIPT_DIR / "pdf_assembler.py"

COMFYUI_URL = os.environ.get("COMFYUI_URL", "http://127.0.0.1:8200")
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen3.6:35b")
COMFYUI_OUTPUT = WORKSHOP_DIR / "comfyui-app" / "ComfyUI" / "output"
PUBLISH_DIR = OPENCLAW_HOME / ".openclaw" / "workspace" / "outputs"

DEFAULT_NEGATIVE = (
    "ugly, deformed, blurry, low quality, watermark, text, logo, "
    "bad anatomy, extra limbs, disfigured, mutation, poorly drawn face, "
    "scary, horror, gore, adult, nsfw"
)


# ---- logging -------------------------------------------------------------
def log(msg: str) -> None:
    print(f"[dreambook] {msg}", file=sys.stderr, flush=True)


# ---- style ---------------------------------------------------------------
def load_style(style_name: str, custom_prompt: str | None) -> dict:
    """Load style JSON. If it's a custom slot and prompt is provided, write it."""
    path = STYLES_DIR / f"{style_name}.json"
    if not path.exists():
        available = [p.stem for p in STYLES_DIR.glob("*.json")]
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
                f"Pass --custom-prompt '...' on first use."
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
    """Call Ollama to produce structured story JSON. Returns parsed dict."""
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
            "think": False,        # Qwen3.6 reasoning 模式必须关闭
            "options": {"temperature": 0.9, "num_predict": 2500},
        },
        timeout=180,
    )
    resp.raise_for_status()
    content = resp.json()["message"]["content"].strip()
    story = parse_story_json(content, pages)

    if title_override:
        story["title"] = title_override
    log(f"story ready: title='{story['title']}', {len(story['pages'])} pages")
    return story


def parse_story_json(raw: str, pages: int) -> dict:
    """Best-effort extract JSON from LLM output (handles ```json fences)."""
    # strip code fences if present
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
    if m:
        raw = m.group(1)
    # fallback: find first { ... } block
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
    # pad/truncate to requested page count
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


# ---- ComfyUI image generation -------------------------------------------
def unload_ollama_models() -> None:
    """Free GPU memory before ComfyUI runs (DGX Spark is unified memory)."""
    try:
        requests.post(
            f"{OLLAMA_URL}/api/generate",
            json={"model": OLLAMA_MODEL, "keep_alive": 0},
            timeout=10,
        )
        log("ollama unloaded (free GPU for ComfyUI)")
    except Exception as e:
        log(f"ollama unload skipped: {e}")


def reload_ollama_models() -> None:
    """Wake Ollama back up so the next skill call is fast."""
    try:
        requests.post(
            f"{OLLAMA_URL}/api/generate",
            json={"model": OLLAMA_MODEL, "prompt": "", "keep_alive": "30m"},
            timeout=30,
        )
    except Exception:
        pass


def upload_image(path: str) -> str:
    fname = Path(path).name
    with open(path, "rb") as fh:
        resp = requests.post(
            f"{COMFYUI_URL}/upload/image",
            files={"image": (fname, fh, "image/png")},
            data={"overwrite": "true"},
            timeout=60,
        )
    resp.raise_for_status()
    return resp.json().get("name", fname)


def submit_prompt(workflow: dict) -> str:
    resp = requests.post(
        f"{COMFYUI_URL}/api/prompt", json={"prompt": workflow}, timeout=30
    )
    resp.raise_for_status()
    data = resp.json()
    if "error" in data:
        raise RuntimeError(json.dumps(data, ensure_ascii=False))
    return data["prompt_id"]


def wait_for_completion(prompt_id: str, timeout: int = 600) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        time.sleep(4)
        try:
            resp = requests.get(
                f"{COMFYUI_URL}/api/history/{prompt_id}", timeout=10
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            continue
        if prompt_id not in data:
            continue
        entry = data[prompt_id]
        status = entry.get("status", {})
        if status.get("completed") or status.get("status_str") == "success":
            return entry.get("outputs", {})
        for msg in status.get("messages", []):
            if isinstance(msg, list) and msg[0] == "execution_error":
                raise RuntimeError(f"ComfyUI error: {msg[1]}")
    raise TimeoutError(f"Prompt {prompt_id} did not finish within {timeout}s")


def extract_first_image(outputs: dict) -> Path:
    for node_out in outputs.values():
        for img in node_out.get("images", []) or []:
            sub = img.get("subfolder") or ""
            fname = img.get("filename") or ""
            if not fname:
                continue
            return COMFYUI_OUTPUT / sub / fname if sub else COMFYUI_OUTPUT / fname
    raise RuntimeError("No output image in ComfyUI history")


def build_workflow(
    face_filename: str,
    scene_description: str,
    style: dict,
    page_num: int,
) -> dict:
    """Patch the template with face + scene + style."""
    wf = json.loads(WORKFLOW_FILE.read_text(encoding="utf-8"))

    positive = (
        f"{style.get('prompt_prefix', '')}. {scene_description}. "
        f"children's picture book illustration, page {page_num}, "
        f"consistent character identity, clear visible face"
    )
    negative = style.get("negative_prefix") or DEFAULT_NEGATIVE

    wf["5"]["inputs"]["image"] = face_filename
    wf["7"]["inputs"]["text"] = positive
    wf["8"]["inputs"]["text"] = negative
    wf["9"]["inputs"]["guidance"] = style.get("cfg", 3.5)
    wf["11"]["inputs"]["seed"] = random.randint(1, 2**32)
    wf["11"]["inputs"]["steps"] = style.get("steps", 24)
    wf["13"]["inputs"]["filename_prefix"] = "dreambook"
    return wf


def generate_one_image(
    face_filename: str, scene: str, style: dict, page_num: int
) -> Path:
    wf = build_workflow(face_filename, scene, style, page_num)
    prompt_id = submit_prompt(wf)
    outputs = wait_for_completion(prompt_id, timeout=600)
    return extract_first_image(outputs)


# ---- inbound fallback ----------------------------------------------------
def latest_inbound_image() -> Path | None:
    inbound = OPENCLAW_HOME / ".openclaw" / "media" / "inbound"
    if not inbound.is_dir():
        return None
    candidates = [
        p
        for p in inbound.iterdir()
        if p.is_file() and p.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


def publish_for_openclaw(src: Path, dst_dir: Path) -> Path:
    dst_dir.mkdir(parents=True, exist_ok=True)
    dst = (dst_dir / src.name).resolve()
    if dst.exists():
        dst.unlink()
    try:
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)
    return dst


# ---- main ----------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser(description="DreamBook generator")
    ap.add_argument("--dream", required=True, help='e.g. "我想成为宇航员"')
    ap.add_argument(
        "--style",
        required=True,
        help="pixar|ghibli|watercolor|oil_painting|comic|custom_1|custom_2",
    )
    ap.add_argument("--face", help="face image absolute path")
    ap.add_argument("--pages", type=int, default=6)
    ap.add_argument("--title", help="override book title")
    ap.add_argument(
        "--custom-prompt",
        help="when style=custom_1/custom_2, write this prompt into the style file",
    )
    args = ap.parse_args()

    # 1) resolve face
    face_path: str | None = args.face
    if not face_path or not Path(face_path).is_file():
        latest = latest_inbound_image()
        if latest is None:
            print(
                "ERROR: 没找到人脸照片。请先在对话里上传一张正面照。",
                file=sys.stderr,
            )
            return 1
        face_path = str(latest)
        log(f"face image -> {face_path}")

    # 2) load style
    style = load_style(args.style, args.custom_prompt)

    # 3) output dir for this run
    ts = time.strftime("%Y%m%d_%H%M%S")
    run_dir = PUBLISH_DIR / f"dreambook_{ts}"
    run_dir.mkdir(parents=True, exist_ok=True)

    # 4) generate story
    story = generate_story(args.dream, style["label"], args.pages, args.title)

    # 5) upload face once, reuse for all pages
    unload_ollama_models()
    log(f"uploading face {face_path}")
    face_filename = upload_image(face_path)

    # 6) generate one image per page
    page_images: list[Path] = []
    for idx, page in enumerate(story["pages"], start=1):
        scene = page.get("scene_description", "")
        text = page.get("story_text", "")
        log(f"--- page {idx}/{args.pages} ---")
        log(f"scene: {scene[:80]}…")
        log(f"text : {text}")
        for attempt in range(2):
            try:
                src = generate_one_image(face_filename, scene, style, idx)
                published = publish_for_openclaw(src, run_dir)
                # rename to page_XX.png for stable PDF ordering
                final = run_dir / f"page_{idx:02d}.png"
                if final.exists():
                    final.unlink()
                published.rename(final)
                page_images.append(final)
                log(f"page {idx} image saved -> {final}")
                break
            except Exception as e:
                if attempt == 0:
                    log(f"page {idx} failed once ({e}), retrying…")
                    time.sleep(3)
                    continue
                log(f"page {idx} FAILED twice: {e}")
                # leave a placeholder so PDF still builds
                page_images.append(None)  # type: ignore[arg-type]

    # 7) assemble PDF
    story["pages"] = [
        {**p, "image_path": str(page_images[i]) if i < len(page_images) else ""}
        for i, p in enumerate(story["pages"])
    ]
    meta_path = run_dir / "story.json"
    meta_path.write_text(
        json.dumps(story, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    pdf_path = run_dir / f"{story['title']}.pdf"
    log(f"assembling PDF -> {pdf_path}")
    rc = assemble_pdf(story, page_images, pdf_path)
    if rc != 0:
        log("WARNING: PDF assembly reported non-zero rc, but continuing")

    reload_ollama_models()
    log(f"DONE: {pdf_path}")
    # Print the MEDIA line — OpenClaw renders this inline
    # Prefer PDF if it exists, else first page image
    if pdf_path.exists():
        print(f"MEDIA:{pdf_path}")
    elif page_images and page_images[0]:
        print(f"MEDIA:{page_images[0]}")
    else:
        print(f"RUN_DIR:{run_dir}")
    return 0


def assemble_pdf(story: dict, images: list[Path | None], out_pdf: Path) -> int:
    """Call pdf_assembler.py as a subprocess (keeps reportlab import optional)."""
    if not PDF_ASSEMBLER.exists():
        log(f"pdf_assembler not found at {PDF_ASSEMBLER}, skipping PDF")
        return 1
    import subprocess

    cmd: list[str] = [
        sys.executable,
        str(PDF_ASSEMBLER),
        "--story-json",
        str(out_pdf.parent / "story.json"),
        "--out",
        str(out_pdf),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        log(f"pdf_assembler stderr:\n{proc.stderr[-800:]}")
    else:
        log(f"pdf_assembler: {proc.stdout.strip()}")
    return proc.returncode


if __name__ == "__main__":
    sys.exit(main())
