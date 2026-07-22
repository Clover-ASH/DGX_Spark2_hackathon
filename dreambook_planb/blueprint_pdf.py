#!/usr/bin/env python3
"""DreamBlueprint PDF 生成器 — 纯文字但视觉精美

布局：
  - 封面：梦想宣言（大字号 + 渐变背景 + 名言）
  - 目录页
  - 6 个阶段页（每个阶段 = 里程碑 + 行动清单 + 风险应对 + 画面占位框）
  - 未来之信页（书信体排版）
  - 封底

视觉技巧（纯文字怎么好看）：
  1. 配色：温暖渐变（米黄/橙/蓝）
  2. 字体层级：标题/副标题/正文/引言明显区分
  3. 留白：大量留白 = 高级感
  4. 装饰线 + emoji + 引用块
  5. 阶段编号用大号数字
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.lib.colors import HexColor, white, black
    from reportlab.pdfgen import canvas
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
except ImportError as e:
    print(f"ERROR: {e}. Run: pip install reportlab", file=sys.stderr)
    sys.exit(2)


# ---- color palette --------------------------------------------------------
COL_BG_WARM = HexColor("#FFF8F0")       # 米黄背景
COL_BG_COOL = HexColor("#F0F4F8")       # 冷调背景
COL_PRIMARY = HexColor("#2C3E50")       # 深蓝灰
COL_ACCENT = HexColor("#E67E22")        # 橙色强调
COL_ACCENT2 = HexColor("#3498DB")       # 蓝色辅助
COL_MUTED = HexColor("#7F8C8D")         # 灰色文字
COL_LIGHT = HexColor("#BDC3C7")         # 浅灰
COL_LETTER_BG = HexColor("#FDF6E3")     # 信纸黄

PALETTE = [COL_ACCENT, COL_ACCENT2, HexColor("#9B59B6"),
           HexColor("#1ABC9C"), HexColor("#F39C12"), HexColor("#E74C3C")]


# ---- font -----------------------------------------------------------------
def find_cjk_font() -> str:
    candidates = [
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
        "/usr/share/fonts/droid-fallback/DroidSansFallbackFull.ttf",
    ]
    for p in candidates:
        if Path(p).exists():
            try:
                pdfmetrics.registerFont(TTFont("CJK", p))
                return "CJK"
            except Exception:
                continue
    print("WARNING: no CJK font found", file=sys.stderr)
    return "Helvetica"


def draw_text_wrapped(
    c: canvas.Canvas, text: str, x: float, y: float,
    max_width: float, font: str, size: float, leading: float,
    color=COL_PRIMARY, indent_first: float = 0,
) -> float:
    """Draw wrapped text. Returns new y."""
    c.setFont(font, size)
    c.setFillColor(color)
    y_cur = y
    line = ""
    first_line = True
    for ch in text:
        if ch == "\n":
            c.drawString(x + (indent_first if first_line else 0), y_cur, line)
            y_cur -= leading
            line = ""
            first_line = False
            continue
        trial = line + ch
        indent = indent_first if first_line else 0
        if pdfmetrics.stringWidth(trial, font, size) > max_width - indent:
            c.drawString(x + indent, y_cur, line)
            y_cur -= leading
            line = ch
            first_line = False
        else:
            line = trial
    if line:
        indent = indent_first if first_line else 0
        c.drawString(x + indent, y_cur, line)
        y_cur -= leading
    return y_cur


def draw_paragraph(
    c: canvas.Canvas, text: str, x: float, y: float,
    max_width: float, font: str, size: float, leading: float,
    color=COL_PRIMARY, indent: float = 20,
) -> float:
    """Draw a paragraph with first-line indent (Chinese essay style)."""
    return draw_text_wrapped(c, text, x, y, max_width, font, size, leading, color, indent)


# ---- page builders --------------------------------------------------------
def draw_cover(c, page_w, page_h, data: dict, font: str):
    """封面：大梦想 + 名言"""
    c.setFillColor(COL_BG_WARM)
    c.rect(0, 0, page_w, page_h, fill=1, stroke=0)

    # 顶部装饰带
    c.setFillColor(COL_ACCENT)
    c.rect(0, page_h - 8 * mm, page_w, 8 * mm, fill=1, stroke=0)

    parsed = data.get("parsed", {})
    dream = parsed.get("dream_clarified", data.get("dream", ""))
    name = data.get("name", "")
    age = data.get("age")

    # 主标题
    c.setFillColor(COL_PRIMARY)
    c.setFont(font, 14)
    c.drawCentredString(page_w / 2, page_h - 50 * mm, "—— 梦想蓝图手册 ——")

    # 梦想大字
    c.setFont(font, 32)
    c.setFillColor(COL_ACCENT)
    # 梦想可能很长，做简单换行
    dream_display = dream if len(dream) <= 12 else dream[:12] + "\n" + dream[12:]
    y = page_h - 90 * mm
    for line in dream_display.split("\n"):
        c.drawCentredString(page_w / 2, y, line)
        y -= 12 * mm

    # 副标题
    c.setFont(font, 12)
    c.setFillColor(COL_MUTED)
    sub = "一份为你定制的成长地图"
    if name:
        sub = f"专属于 {name} 的成长地图"
    if age:
        sub += f"  ·  {age}岁启程"
    c.drawCentredString(page_w / 2, y - 5 * mm, sub)

    # 名言（中下部）
    quote = parsed.get("inspirational_quote", "梦想不是用来想的，是用来走的。")
    c.setFont(font, 11)
    c.setFillColor(COL_PRIMARY)
    y_quote = 90 * mm
    y_quote = draw_text_wrapped(
        c, f"「{quote}」", 30 * mm, y_quote,
        page_w - 60 * mm, font, 11, 18, COL_PRIMARY,
    )

    # 底部装饰
    c.setFillColor(COL_ACCENT2)
    c.rect(0, 0, page_w, 5 * mm, fill=1, stroke=0)
    c.setFont(font, 9)
    c.setFillColor(COL_MUTED)
    c.drawCentredString(
        page_w / 2, 15 * mm,
        "DreamBlueprint · 由 5 位 AI Agent 协作生成  ·  Made on DGX Spark"
    )
    c.showPage()


def draw_toc(c, page_w, page_h, data: dict, font: str):
    """目录页"""
    c.setFillColor(white)
    c.rect(0, 0, page_w, page_h, fill=1, stroke=0)

    c.setFillColor(COL_PRIMARY)
    c.setFont(font, 22)
    c.drawString(25 * mm, page_h - 30 * mm, "目  录")

    c.setStrokeColor(COL_ACCENT)
    c.setLineWidth(1)
    c.line(25 * mm, page_h - 33 * mm, 50 * mm, page_h - 33 * mm)

    parsed = data.get("parsed", {})
    items = [
        ("01", "梦想定义", "什么是真正的「" + parsed.get("dream_clarified", "?")[:15] + "」"),
        ("02", "成长阶段", "6 个里程碑，循序渐进"),
        ("03", "行动地图", "每阶段可立即开始的具体行动"),
        ("04", "风险与应对", "诚实面对可能的阻碍"),
        ("05", "来自未来的一封信", "梦想成真的你，写给现在的你"),
    ]

    y = page_h - 55 * mm
    for num, title, sub in items:
        c.setFont(font, 18)
        c.setFillColor(COL_ACCENT)
        c.drawString(25 * mm, y, num)

        c.setFont(font, 13)
        c.setFillColor(COL_PRIMARY)
        c.drawString(45 * mm, y + 3, title)

        c.setFont(font, 9)
        c.setFillColor(COL_MUTED)
        c.drawString(45 * mm, y - 8, sub)

        y -= 22 * mm

    c.showPage()


def draw_dream_definition(c, page_w, page_h, data: dict, font: str):
    """章节 1：梦想定义"""
    c.setFillColor(COL_BG_WARM)
    c.rect(0, 0, page_w, page_h, fill=1, stroke=0)

    parsed = data.get("parsed", {})

    # 章节标识
    c.setFont(font, 9)
    c.setFillColor(COL_MUTED)
    c.drawString(25 * mm, page_h - 20 * mm, "CHAPTER 01")

    c.setFont(font, 24)
    c.setFillColor(COL_PRIMARY)
    c.drawString(25 * mm, page_h - 32 * mm, "梦想定义")

    c.setStrokeColor(COL_ACCENT)
    c.setLineWidth(2)
    c.line(25 * mm, page_h - 35 * mm, 60 * mm, page_h - 35 * mm)

    y = page_h - 50 * mm

    # 梦想类型
    dream_type = parsed.get("dream_type", "")
    if dream_type:
        c.setFont(font, 10)
        c.setFillColor(white)
        # 画个标签底色
        type_text = f"  {dream_type}  "
        tw = pdfmetrics.stringWidth(type_text, font, 10)
        c.setFillColor(COL_ACCENT)
        c.rect(25 * mm, y - 2, tw, 16, fill=1, stroke=0)
        c.setFillColor(white)
        c.drawString(25 * mm, y + 2, type_text)
        y -= 12 * mm

    # 原始梦想
    c.setFont(font, 10)
    c.setFillColor(COL_MUTED)
    c.drawString(25 * mm, y, "你说：")
    y = draw_text_wrapped(
        c, f"「{parsed.get('dream_original', data.get('dream',''))}」",
        25 * mm, y - 14, page_w - 50 * mm, font, 12, 20, COL_PRIMARY,
    )
    y -= 8

    # 精确化
    c.setFont(font, 10)
    c.setFillColor(COL_MUTED)
    c.drawString(25 * mm, y, "我们把它精确为：")
    y = draw_text_wrapped(
        c, parsed.get("dream_clarified", ""),
        25 * mm, y - 14, page_w - 50 * mm, font, 12, 20, COL_PRIMARY,
    )
    y -= 12

    # 成功定义
    c.setFillColor(COL_BG_COOL)
    c.rect(22 * mm, y - 95, page_w - 44 * mm, 90, fill=1, stroke=0)
    c.setFont(font, 10)
    c.setFillColor(COL_ACCENT2)
    c.drawString(25 * mm, y - 14, "▎ 怎样算实现了这个梦想？")
    y = draw_text_wrapped(
        c, parsed.get("success_definition", ""),
        25 * mm, y - 30, page_w - 50 * mm, font, 11, 18, COL_PRIMARY,
    )
    y -= 18

    # 核心能力
    c.setFont(font, 11)
    c.setFillColor(COL_PRIMARY)
    c.drawString(25 * mm, y, "▎ 实现梦想需要的核心能力")
    y -= 18
    for ability in parsed.get("core_abilities", []):
        c.setFillColor(COL_ACCENT)
        c.circle(28 * mm, y + 3, 2, fill=1, stroke=0)
        c.setFont(font, 11)
        c.setFillColor(COL_PRIMARY)
        c.drawString(33 * mm, y, ability)
        y -= 16

    c.showPage()


def draw_stages_intro(c, page_w, page_h, stages: list, font: str):
    """章节 2：成长阶段概览"""
    c.setFillColor(white)
    c.rect(0, 0, page_w, page_h, fill=1, stroke=0)

    c.setFont(font, 9)
    c.setFillColor(COL_MUTED)
    c.drawString(25 * mm, page_h - 20 * mm, "CHAPTER 02")

    c.setFont(font, 24)
    c.setFillColor(COL_PRIMARY)
    c.drawString(25 * mm, page_h - 32 * mm, "成长阶段")

    c.setStrokeColor(COL_ACCENT)
    c.setLineWidth(2)
    c.line(25 * mm, page_h - 35 * mm, 60 * mm, page_h - 35 * mm)

    c.setFont(font, 11)
    c.setFillColor(COL_MUTED)
    c.drawString(25 * mm, page_h - 45 * mm, "从现在到梦想成真，6 个里程碑，循序渐进")

    # 6 个阶段卡片
    y = page_h - 60 * mm
    for i, stage in enumerate(stages):
        color = PALETTE[i % len(PALETTE)]
        # 大数字
        c.setFont(font, 36)
        c.setFillColor(color)
        c.drawString(25 * mm, y - 4, f"{stage.get('stage', i+1):02d}")

        # 阶段名
        c.setFont(font, 13)
        c.setFillColor(COL_PRIMARY)
        c.drawString(50 * mm, y + 4, stage.get("name", f"阶段 {i+1}"))

        # 年龄范围
        c.setFont(font, 9)
        c.setFillColor(COL_MUTED)
        age_r = stage.get("age_range", "")
        if age_r:
            c.drawString(50 * mm, y - 8, f"⏱ {age_r}")

        # 里程碑
        c.setFont(font, 10)
        c.setFillColor(COL_PRIMARY)
        ms = stage.get("milestone", "")
        # 截断长文本
        if len(ms) > 35:
            ms = ms[:35] + "…"
        c.drawString(50 * mm, y - 20, ms)

        # 分隔线
        if i < len(stages) - 1:
            c.setStrokeColor(COL_LIGHT)
            c.setLineWidth(0.3)
            c.line(25 * mm, y - 28, page_w - 25 * mm, y - 28)

        y -= 38 * mm

    c.showPage()


def draw_stage_detail(c, page_w, page_h, stage: dict, actions: list, risks: list, font: str):
    """每个阶段一页详情（含行动 + 风险）"""
    c.setFillColor(COL_BG_WARM)
    c.rect(0, 0, page_w, page_h, fill=1, stroke=0)

    idx = stage.get("stage", 1)
    color = PALETTE[(idx - 1) % len(PALETTE)]

    # 顶部彩色带
    c.setFillColor(color)
    c.rect(0, page_h - 15 * mm, page_w, 15 * mm, fill=1, stroke=0)
    c.setFont(font, 10)
    c.setFillColor(white)
    c.drawString(25 * mm, page_h - 10 * mm, f"STAGE {idx:02d}  ·  {stage.get('age_range','')}")

    y = page_h - 30 * mm

    # 阶段名 + 大数字
    c.setFont(font, 40)
    c.setFillColor(color)
    c.drawString(25 * mm, y - 8, f"{idx:02d}")

    c.setFont(font, 18)
    c.setFillColor(COL_PRIMARY)
    c.drawString(55 * mm, y, stage.get("name", ""))

    y -= 20

    # 里程碑
    c.setFont(font, 10)
    c.setFillColor(COL_MUTED)
    c.drawString(55 * mm, y, "里程碑")
    y = draw_text_wrapped(
        c, stage.get("milestone", ""),
        55 * mm, y - 14, page_w - 80 * mm, font, 11, 17, COL_PRIMARY,
    )
    y -= 12

    # 画面感描述（用作"想象"框）
    scene = stage.get("scene", "")
    if scene:
        c.setFillColor(COL_BG_COOL)
        c.rect(22 * mm, y - 60, page_w - 44 * mm, 55, fill=1, stroke=0)
        c.setFont(font, 9)
        c.setFillColor(COL_ACCENT2)
        c.drawString(25 * mm, y - 12, "🖼  画面感")
        draw_text_wrapped(
            c, scene,
            25 * mm, y - 26, page_w - 50 * mm, font, 10, 15, COL_PRIMARY,
        )
        y -= 70

    # 行动清单
    stage_actions = next((a for a in actions if a.get("stage") == idx), {})
    action_items = stage_actions.get("items", [])

    if action_items:
        c.setFont(font, 11)
        c.setFillColor(COL_ACCENT)
        c.drawString(25 * mm, y, "✦ 立即行动")
        y -= 16

        for item in action_items:
            act = item.get("action", "")
            freq = item.get("frequency", "")
            why = item.get("why", "")

            # 圆点
            c.setFillColor(COL_ACCENT)
            c.circle(28 * mm, y + 3, 2, fill=1, stroke=0)

            # 行动 + 频率
            c.setFont(font, 11)
            c.setFillColor(COL_PRIMARY)
            c.drawString(33 * mm, y, act)
            if freq:
                c.setFont(font, 8)
                c.setFillColor(COL_MUTED)
                c.drawRightString(page_w - 25 * mm, y, f"[{freq}]")

            y -= 14
            if why:
                c.setFont(font, 9)
                c.setFillColor(COL_MUTED)
                y = draw_text_wrapped(
                    c, f"—— {why}", 33 * mm, y,
                    page_w - 58 * mm, font, 9, 13, COL_MUTED,
                )
                y -= 4

    y -= 10

    # 风险应对
    stage_risks = next((r for r in risks if r.get("stage") == idx), {})
    risk_items = stage_risks.get("items", [])

    if risk_items:
        c.setFont(font, 11)
        c.setFillColor(HexColor("#E74C3C"))
        c.drawString(25 * mm, y, "⚠ 可能的阻碍")
        y -= 16

        for item in risk_items:
            risk = item.get("risk", "")
            solution = item.get("solution", "")
            enc = item.get("encouragement", "")

            c.setFillColor(HexColor("#E74C3C"))
            c.circle(28 * mm, y + 3, 2, fill=1, stroke=0)

            y = draw_text_wrapped(
                c, risk, 33 * mm, y,
                page_w - 58 * mm, font, 10, 15, COL_PRIMARY,
            )
            if solution:
                y = draw_text_wrapped(
                    c, f"→ {solution}", 33 * mm, y,
                    page_w - 58 * mm, font, 9, 13, COL_ACCENT2,
                )
            if enc:
                c.setFont(font, 9)
                c.setFillColor(COL_ACCENT)
                c.drawString(33 * mm, y, f"💬 {enc}")
                y -= 14
            y -= 6

    # 页脚
    c.setFont(font, 8)
    c.setFillColor(COL_MUTED)
    c.drawCentredString(page_w / 2, 12 * mm, f"— 阶段 {idx} / 6 —")

    c.showPage()


def draw_letter(c, page_w, page_h, data: dict, font: str):
    """章节 5：未来之信"""
    c.setFillColor(COL_LETTER_BG)
    c.rect(0, 0, page_w, page_h, fill=1, stroke=0)

    c.setFont(font, 9)
    c.setFillColor(COL_MUTED)
    c.drawString(25 * mm, page_h - 20 * mm, "CHAPTER 05")

    c.setFont(font, 22)
    c.setFillColor(COL_PRIMARY)
    c.drawString(25 * mm, page_h - 32 * mm, "来自未来的一封信")

    c.setStrokeColor(COL_ACCENT)
    c.setLineWidth(2)
    c.line(25 * mm, page_h - 35 * mm, 85 * mm, page_h - 35 * mm)

    c.setFont(font, 10)
    c.setFillColor(COL_MUTED)
    c.drawString(25 * mm, page_h - 42 * mm, "—— 当你读到这封信时，梦想已经成真")

    # 信件正文
    letter = data.get("letter", "")
    name = data.get("name", "")

    y = page_h - 55 * mm
    # 称呼
    c.setFont(font, 12)
    c.setFillColor(COL_PRIMARY)
    salutation = f"亲爱的{name}：" if name else "亲爱的自己："
    c.drawString(25 * mm, y, salutation)
    y -= 22

    # 正文段落
    y = draw_paragraph(
        c, letter, 25 * mm, y,
        page_w - 50 * mm, font, 11, 19, COL_PRIMARY, indent=22,
    )

    # 落款
    y -= 10
    c.setFont(font, 10)
    c.setFillColor(COL_MUTED)
    c.drawRightString(page_w - 25 * mm, y, "未来的你")
    y -= 14
    c.drawRightString(page_w - 25 * mm, y, "写于梦想成真那天")

    # 底部装饰
    c.setFillColor(COL_ACCENT)
    c.rect(0, 0, page_w, 3 * mm, fill=1, stroke=0)

    c.showPage()


def draw_back_cover(c, page_w, page_h, data: dict, font: str):
    c.setFillColor(COL_BG_WARM)
    c.rect(0, 0, page_w, page_h, fill=1, stroke=0)

    c.setFont(font, 16)
    c.setFillColor(COL_ACCENT)
    c.drawCentredString(page_w / 2, page_h / 2 + 20 * mm, "梦想这条路，")

    c.setFont(font, 16)
    c.setFillColor(COL_PRIMARY)
    c.drawCentredString(page_w / 2, page_h / 2 + 5 * mm, "一旦开始走，就已经在实现。")

    c.setFont(font, 10)
    c.setFillColor(COL_MUTED)
    c.drawCentredString(page_w / 2, page_h / 2 - 20 * mm, "—— DreamBlueprint ——")
    c.drawCentredString(
        page_w / 2, page_h / 2 - 32 * mm,
        "5 位 AI Agent 协作生成  ·  Powered by NVIDIA DGX Spark + Nemotron"
    )
    c.showPage()


# ---- main builder ---------------------------------------------------------
def build_pdf(data: dict, out_pdf: Path) -> None:
    font = find_cjk_font()
    page_w, page_h = A4
    c = canvas.Canvas(str(out_pdf), pagesize=A4)

    stages = data.get("stages", [])
    actions = data.get("actions", [])
    risks = data.get("risks", [])

    draw_cover(c, page_w, page_h, data, font)
    draw_toc(c, page_w, page_h, data, font)
    draw_dream_definition(c, page_w, page_h, data, font)
    if stages:
        draw_stages_intro(c, page_w, page_h, stages, font)
        for stage in stages:
            draw_stage_detail(c, page_w, page_h, stage, actions, risks, font)
    draw_letter(c, page_w, page_h, data, font)
    draw_back_cover(c, page_w, page_h, data, font)

    c.save()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-json", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    data = json.loads(Path(args.data_json).read_text(encoding="utf-8"))
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    build_pdf(data, out)
    print(f"PDF written: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
