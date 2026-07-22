#!/usr/bin/env python3
"""DreamBlueprint Agent Team — Plan B 保底方案（纯 LLM，零图像依赖）

5 个 Agent 协作生成「梦想蓝图手册」PDF：
  ① 梦想解析师：把梦想拆成具体方向
  ② 成长路径师：设计 6 个成长阶段
  ③ 行动导师：每阶段给可执行行动
  ④ 风险顾问：每阶段风险 + 应对
  ⑤ 未来自传作家：以已实现梦想的"未来的你"口吻写信

依赖：Ollama（已验证可用） + reportlab（pip 装）
完全不依赖 FLUX / ComfyUI / 图像模型

Usage:
    python3 dream_blueprint.py --dream "我想成为宇航员"
    python3 dream_blueprint.py --dream "我想成为画家" --name 小明 --age 8
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

import requests

# ---- config ---------------------------------------------------------------
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "nemotron-3-nano:30b")  # NVIDIA 自家模型
HOME = Path.home()
OUTPUT_DIR = HOME / "dream_blueprint_output"

SCRIPT_DIR = Path(__file__).resolve().parent
PDF_SCRIPT = SCRIPT_DIR / "blueprint_pdf.py"


def log(msg: str) -> None:
    print(f"[blueprint] {msg}", file=sys.stderr, flush=True)


# ---- LLM call wrapper -----------------------------------------------------
def ask_llm(
    system_prompt: str,
    user_prompt: str,
    temperature: float = 0.8,
    max_tokens: int = 2000,
    timeout: int = 300,
    retries: int = 2,
) -> str:
    """Call Ollama chat API. Auto-retry on transient errors."""
    last_err = None
    for attempt in range(retries + 1):
        try:
            resp = requests.post(
                f"{OLLAMA_URL}/api/chat",
                json={
                    "model": OLLAMA_MODEL,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    "stream": False,
                    "think": False,  # 关闭 reasoning（workshop 教训）
                    "options": {
                        "temperature": temperature,
                        "num_predict": max_tokens,
                    },
                },
                timeout=timeout,
            )
            resp.raise_for_status()
            return resp.json()["message"]["content"].strip()
        except Exception as e:
            last_err = e
            log(f"LLM call attempt {attempt+1} failed: {e}")
            time.sleep(2)
    raise RuntimeError(f"LLM call failed after {retries+1} attempts: {last_err}")


def ask_json(
    system_prompt: str,
    user_prompt: str,
    max_tokens: int = 2500,
) -> dict:
    """Call LLM and parse JSON from response."""
    raw = ask_llm(system_prompt, user_prompt, temperature=0.7, max_tokens=max_tokens)
    return parse_json(raw)


def parse_json(raw: str) -> dict:
    """Best-effort extract JSON from LLM output."""
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
    if m:
        raw = m.group(1)
    if not raw.strip().startswith("{"):
        start = raw.find("{")
        end = raw.rfind("}")
        if start >= 0 and end > start:
            raw = raw[start : end + 1]
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"LLM did not return valid JSON: {e}\nraw:\n{raw[:500]}")


# ---- 5 Agents -------------------------------------------------------------
def agent_1_dream_parser(dream: str, name: str | None, age: int | None) -> dict:
    """Agent ①: 解析梦想"""
    log("Agent ① 梦想解析师 启动…")
    sys_p = """你是一位梦想解析师。把用户模糊的"我想成为 XXX"梦想，解析成清晰的目标定义。
只输出 JSON，不要任何解释。结构：
{
  "dream_original": "用户原始梦想",
  "dream_clarified": "更精确的梦想描述（一句话）",
  "dream_type": "职业型/兴趣型/品格型/创造型 之一",
  "success_definition": "怎样算实现了这个梦想（具体可观察）",
  "core_abilities": ["实现梦想需要的 3-5 个核心能力"],
  "inspirational_quote": "一句与这个梦想相关的名言（中文）"
}"""
    name_part = f"主角名字：{name}，" if name else ""
    age_part = f"主角年龄：{age}岁，" if age else ""
    user_p = f"{name_part}{age_part}梦想：{dream}\n请解析这个梦想。"
    return ask_json(sys_p, user_p, max_tokens=800)


def agent_2_path_designer(parsed: dict, age: int | None) -> list[dict]:
    """Agent ②: 设计 6 个成长阶段"""
    log("Agent ② 成长路径师 启动…")
    sys_p = """你是一位成长路径设计师。基于梦想解析结果，设计 6 个成长阶段，每个阶段是一个里程碑。
阶段要循序渐进：从现在的起点 → 短期探索 → 中期投入 → 深度积累 → 突破临界 → 梦想实现。
只输出 JSON 数组，不要任何解释。结构：
{
  "stages": [
    {
      "stage": 1,
      "name": "阶段名称（4-8字，朗朗上口）",
      "age_range": "如 8-9岁 或 当下-3个月",
      "milestone": "这个阶段的核心里程碑（一句话）",
      "scene": "想象中这个阶段主角的画面感描述（中文，富有画面感，50-80字，用于占位插图说明）"
    }
  ]
}
注意：必须返回 6 个阶段。"""
    age_part = f"主角当前年龄 {age} 岁，" if age else ""
    user_p = f"{age_part}梦想解析：{json.dumps(parsed, ensure_ascii=False)}\n请设计 6 个成长阶段。"
    data = ask_json(sys_p, user_p, max_tokens=1500)
    stages = data.get("stages", [])
    if len(stages) != 6:
        log(f"warning: expected 6 stages, got {len(stages)}")
    return stages


def agent_3_action_coach(stages: list[dict]) -> list[dict]:
    """Agent ③: 每阶段给具体行动"""
    log("Agent ③ 行动导师 启动…")
    sys_p = """你是行动导师。为每个成长阶段设计 3-5 个具体、可执行、可衡量的行动。
行动要接地气，普通人能立刻开始做。
只输出 JSON，结构：
{
  "actions": [
    {
      "stage": 1,
      "items": [
        {"action": "具体行动（动词开头）", "frequency": "每天/每周/每月", "why": "这个行动为什么重要（一句话）"}
      ]
    }
  ]
}
为每个 stage 都生成。"""
    user_p = f"成长阶段：{json.dumps(stages, ensure_ascii=False)}\n请为每个阶段设计具体行动。"
    data = ask_json(sys_p, user_p, max_tokens=2000)
    return data.get("actions", [])


def agent_4_risk_advisor(stages: list[dict]) -> list[dict]:
    """Agent ④: 每阶段风险 + 应对"""
    log("Agent ④ 风险顾问 启动…")
    sys_p = """你是风险顾问。为每个成长阶段识别 1-2 个最可能出现的阻碍，给出具体应对策略。
要诚实、温暖、有建设性，不要鸡汤。
只输出 JSON：
{
  "risks": [
    {
      "stage": 1,
      "items": [
        {"risk": "风险描述", "solution": "具体应对方法", "encouragement": "一句鼓励的话"}
      ]
    }
  ]
}"""
    user_p = f"成长阶段：{json.dumps(stages, ensure_ascii=False)}\n请识别每个阶段的风险与应对。"
    data = ask_json(sys_p, user_p, max_tokens=2000)
    return data.get("risks", [])


def agent_5_future_biographer(parsed: dict, name: str | None) -> str:
    """Agent ⑤: 未来自传作家"""
    log("Agent ⑤ 未来自传作家 启动…")
    sys_p = """你是未来自传作家。请以"已经实现梦想的未来的主角"的口吻，给"现在的主角"写一封信。
要求：
- 1000-1500 字
- 第一人称（"我"是未来的主角）
- 温暖、真诚、有细节，不要空话
- 回顾追梦路上最关键的 2-3 个转折点
- 给现在的自己一个最重要的建议
- 落款是 "未来的你，写于梦想成真那天"
直接输出信件正文，不要 JSON，不要标题。"""
    name_part = f"（主角名字：{name}）" if name else ""
    user_p = f"梦想：{parsed.get('dream_clarified', parsed.get('dream_original',''))}{name_part}\n请写这封信。"
    return ask_llm(sys_p, user_p, temperature=0.9, max_tokens=2000)


# ---- orchestrator ---------------------------------------------------------
def run(dream: str, name: str | None, age: int | None) -> Path:
    log(f"启动 DreamBlueprint Agent Team")
    log(f"梦想: {dream}")
    log(f"名字: {name or '(未指定)'}, 年龄: {age or '(未指定)'}")

    # run 5 agents in sequence (each one builds on previous)
    parsed = agent_1_dream_parser(dream, name, age)
    log(f"① 完成: {parsed.get('dream_clarified', '?')[:50]}")

    stages = agent_2_path_designer(parsed, age)
    log(f"② 完成: {len(stages)} 个阶段")

    actions = agent_3_action_coach(stages)
    log(f"③ 完成: {sum(len(a.get('items',[])) for a in actions)} 条行动")

    risks = agent_4_risk_advisor(stages)
    log(f"④ 完成: {sum(len(r.get('items',[])) for r in risks)} 条风险应对")

    letter = agent_5_future_biographer(parsed, name)
    log(f"⑤ 完成: 未来之信 {len(letter)} 字")

    # assemble final data
    ts = time.strftime("%Y%m%d_%H%M%S")
    run_dir = OUTPUT_DIR / f"blueprint_{ts}"
    run_dir.mkdir(parents=True, exist_ok=True)

    data = {
        "dream": dream,
        "name": name,
        "age": age,
        "parsed": parsed,
        "stages": stages,
        "actions": actions,
        "risks": risks,
        "letter": letter,
        "generated_at": ts,
    }

    # save raw JSON for debugging
    (run_dir / "data.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    log(f"data saved: {run_dir / 'data.json'}")

    # build PDF
    pdf_path = run_dir / f"梦想蓝图_{parsed.get('dream_clarified', dream)[:10]}.pdf"
    log(f"assembling PDF → {pdf_path}")
    rc = build_pdf(data, pdf_path)
    if rc == 0 and pdf_path.exists():
        log(f"DONE: {pdf_path}")
        return pdf_path
    else:
        log("PDF 失败，但 data.json 已保存")
        return run_dir / "data.json"


def build_pdf(data: dict, out_pdf: Path) -> int:
    """Call blueprint_pdf.py as subprocess."""
    import subprocess

    if not PDF_SCRIPT.exists():
        log(f"blueprint_pdf.py not found, skipping PDF")
        return 1

    data_json = out_pdf.parent / "data.json"
    cmd = [
        sys.executable,
        str(PDF_SCRIPT),
        "--data-json", str(data_json),
        "--out", str(out_pdf),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        log(f"blueprint_pdf stderr: {proc.stderr[-800:]}")
    else:
        log(f"blueprint_pdf: {proc.stdout.strip()}")
    return proc.returncode


def main() -> int:
    ap = argparse.ArgumentParser(description="DreamBlueprint Agent Team (Plan B)")
    ap.add_argument("--dream", required=True, help='e.g. "我想成为宇航员"')
    ap.add_argument("--name", help="主角名字（可选）")
    ap.add_argument("--age", type=int, help="主角年龄（可选）")
    args = ap.parse_args()

    pdf = run(args.dream, args.name, args.age)
    print(f"MEDIA:{pdf}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
