#!/usr/bin/env python3
"""Assemble DreamBook PDF from story.json + page images.

Layout:
  - Cover page: title + dream subtitle + child hero photo
  - 6 content pages: each = full-bleed illustration + story text below
  - Back cover: "To be continued…"

Dependencies: reportlab, PIL  (both pure-python, pip install reportlab pillow)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from PIL import Image
except ImportError as e:
    print(
        f"ERROR: missing dependency: {e}. "
        "Run: pip install reportlab pillow",
        file=sys.stderr,
    )
    sys.exit(2)


# ---- font registration (Chinese support) --------------------------------
def find_chinese_font() -> str:
    """Try common CJK font paths on DGX Spark; fall back to reportlab built-in."""
    candidates = [
        # 节点实测可用的字体（按优先级）
        "/usr/share/fonts/truetype/arphic/uming.ttc",          # AR PL UMing（文鼎）
        "/usr/share/fonts/truetype/arphic/ukai.ttc",           # AR PL UKai（楷体）
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Black.ttc",# Noto Sans CJK
        "/usr/share/fonts/opentype/noto/NotoSerifCJK-Bold.ttc",
        # 备用
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
        "/usr/share/fonts/droid-fallback/DroidSansFallbackFull.ttf",
    ]
    for p in candidates:
        if Path(p).exists():
            try:
                # TTC 文件需要指定 subfontIndex
                if p.endswith(".ttc"):
                    pdfmetrics.registerFont(TTFont("DreamBookCJK", p, subfontIndex=0))
                else:
                    pdfmetrics.registerFont(TTFont("DreamBookCJK", p))
                print(f"  using CJK font: {p}", file=sys.stderr)
                return "DreamBookCJK"
            except Exception as e:
                print(f"  font {p} failed: {e}", file=sys.stderr)
                continue
    print(
        "WARNING: no CJK font found, Chinese text may not render correctly",
        file=sys.stderr,
    )
    return "Helvetica"


def draw_text_wrapped(
    c: canvas.Canvas,
    text: str,
    x: float,
    y: float,
    max_width: float,
    font: str,
    size: float,
    leading: float,
) -> float:
    """Draw Chinese-aware wrapped text. Returns new y after drawing."""
    c.setFont(font, size)
    y_cursor = y
    line = ""
    for ch in text:
        if ch == "\n":
            c.drawString(x, y_cursor, line)
            y_cursor -= leading
            line = ""
            continue
        trial = line + ch
        if pdfmetrics.stringWidth(trial, font, size) > max_width:
            c.drawString(x, y_cursor, line)
            y_cursor -= leading
            line = ch
        else:
            line = trial
    if line:
        c.drawString(x, y_cursor, line)
        y_cursor -= leading
    return y_cursor


def draw_image_fit(
    c: canvas.Canvas,
    img_path: Path,
    box_x: float,
    box_y: float,
    box_w: float,
    box_h: float,
) -> None:
    """Draw image fitted (contain) into box, centered."""
    if not img_path or not Path(img_path).exists():
        # placeholder rectangle
        c.setFillColorRGB(0.9, 0.9, 0.9)
        c.rect(box_x, box_y, box_w, box_h, fill=1, stroke=0)
        c.setFillColorRGB(0.5, 0.5, 0.5)
        c.setFont("Helvetica", 14)
        c.drawCentredString(
            box_x + box_w / 2, box_y + box_h / 2, "(image missing)"
        )
        return
    try:
        with Image.open(img_path) as im:
            iw, ih = im.size
        scale = min(box_w / iw, box_h / ih)
        draw_w = iw * scale
        draw_h = ih * scale
        draw_x = box_x + (box_w - draw_w) / 2
        draw_y = box_y + (box_h - draw_h) / 2
        c.drawImage(
            str(img_path),
            draw_x,
            draw_y,
            draw_w,
            draw_h,
            preserveAspectRatio=True,
            mask="auto",
        )
    except Exception as e:
        print(f"WARNING: cannot draw {img_path}: {e}", file=sys.stderr)


def build_pdf(story: dict, images: list[Path | None], out_pdf: Path) -> None:
    cjk = find_chinese_font()
    page_w, page_h = A4
    margin = 15 * mm
    c = canvas.Canvas(str(out_pdf), pagesize=A4)

    pages = story.get("pages", [])
    title = story.get("title", "我的梦想绘本")

    # ---------- Cover ----------
    c.setFillColorRGB(0.96, 0.94, 0.88)
    c.rect(0, 0, page_w, page_h, fill=1, stroke=0)

    # cover image: child hero photo (page 1 image, or first available)
    cover_img = images[0] if images else None
    if cover_img:
        draw_image_fit(
            c,
            cover_img,
            margin,
            page_h * 0.42,
            page_w - 2 * margin,
            page_h * 0.45,
        )

    c.setFillColorRGB(0.2, 0.2, 0.3)
    y = page_h * 0.36
    y = draw_text_wrapped(
        c, title, margin, y, page_w - 2 * margin, cjk, 28, 34
    )
    y -= 6
    c.setFont(cjk, 12)
    c.setFillColorRGB(0.5, 0.4, 0.3)
    c.drawString(margin, y, "—— 一本属于你的梦想绘本 ——")
    c.showPage()

    # ---------- Content pages ----------
    for idx, page in enumerate(pages):
        # background
        c.setFillColorRGB(1, 1, 1)
        c.rect(0, 0, page_w, page_h, fill=1, stroke=0)

        img = images[idx] if idx < len(images) else None
        # image occupies top ~70%
        draw_image_fit(
            c,
            img,
            margin,
            page_h * 0.28,
            page_w - 2 * margin,
            page_h * 0.62,
        )

        # story text in bottom band
        c.setFillColorRGB(0.2, 0.2, 0.3)
        text_y = page_h * 0.22
        story_text = page.get("story_text", "")
        text_y = draw_text_wrapped(
            c,
            story_text,
            margin + 4,
            text_y,
            page_w - 2 * margin - 8,
            cjk,
            12,
            18,
        )

        # page number
        c.setFont(cjk, 9)
        c.setFillColorRGB(0.6, 0.6, 0.6)
        c.drawCentredString(page_w / 2, margin, f"— {idx + 1} —")

        c.showPage()

    # ---------- Back cover ----------
    c.setFillColorRGB(0.96, 0.94, 0.88)
    c.rect(0, 0, page_w, page_h, fill=1, stroke=0)
    c.setFillColorRGB(0.4, 0.35, 0.3)
    c.setFont(cjk, 16)
    c.drawCentredString(page_w / 2, page_h / 2 + 10, "梦想，才刚刚开始……")
    c.setFont(cjk, 10)
    c.drawCentredString(page_w / 2, page_h / 2 - 20, "DreamBook · Made with ❤️ on DGX Spark")
    c.showPage()

    c.save()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--story-json", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    story = json.loads(Path(args.story_json).read_text(encoding="utf-8"))
    images: list[Path | None] = [
        Path(p.get("image_path", "")) if p.get("image_path") else None
        for p in story.get("pages", [])
    ]
    out_pdf = Path(args.out)
    out_pdf.parent.mkdir(parents=True, exist_ok=True)
    build_pdf(story, images, out_pdf)
    print(f"PDF written: {out_pdf}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
