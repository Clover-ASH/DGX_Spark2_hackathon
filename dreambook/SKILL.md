---
name: dreambook
description: "Create a 6-page personalized children's picture book titled 'I want to be a XXX' (我想成为XXX) from a child's face photo. Use when: user says 我想成为, 梦想绘本, 童年梦想, 给孩子做绘本, dreambook, I want to be, or uploads a face photo asking to make a children's book."
metadata: { "openclaw": { "emoji": "📖", "requires": { "bins": ["python3", "bash"] } } }
---

# DreamBook — 「我想成为 XXX」童年梦想绘本生成器

用户上传一张孩子（或任何人）的正面照片 + 一句梦想主题（"我想成为宇航员" / "我想成为消防员" / "I want to be a scientist"），本 skill 用本地 LLM (Ollama Qwen3.6) 创作 6 页成长故事，每页用 ComfyUI (FLUX + PuLID) 生成保持人物身份的插图，最后拼成可打印 PDF。

## 用法

### 方式 1：最简单（推荐）—— Agent 自动拿上传图片

```bash
"$OPENCLAW_HOME/.openclaw/skills/dreambook/run_helper.sh" --dream "我想成为宇航员" --style pixar
```

helper 会自动从 OpenClaw inbound 目录拿用户最新上传的人脸图。

### 方式 2：显式传人脸路径 + 完整参数

```bash
"$OPENCLAW_HOME/.openclaw/skills/dreambook/run_helper.sh" \
    --face /path/to/child.jpg \
    --dream "我想成为消防员" \
    --style ghibli \
    --pages 6 \
    --title "小明的宇航梦"
```

### 参数说明

| 参数 | 必填 | 说明 |
|------|------|------|
| `--dream` | ✅ | 梦想主题，如"我想成为宇航员" |
| `--style` | ✅ | 风格名：`pixar` / `ghibli` / `watercolor` / `oil_painting` / `comic` / `custom_1` / `custom_2` |
| `--face` | ❌ | 人脸图绝对路径；不传则从 OpenClaw inbound 自动取最新 |
| `--pages` | ❌ | 页数，默认 6 |
| `--title` | ❌ | 绘本主标题；不传则用 dream 自动生成 |
| `--custom-prompt` | ❌ | 当 style=custom_1/custom_2 时，把这段提示词写入对应风格文件（一次性，下次复用） |

## 风格系统

- 5 个预设：pixar / ghibli / watercolor / oil_painting / comic，每个背后是一段 FLUX 提示词前缀（见 `styles/*.json`）。
- 2 个自定义槽位：custom_1 / custom_2，用户首次用时通过 `--custom-prompt` 注入提示词，写入文件后下次直接 `--style custom_1` 复用。
- 用户也可以手动编辑 `styles/*.json` 微调任意风格的提示词。

## 输出

- 6 张 1024×1024 PNG 插图（保存到 `$OPENCLAW_HOME/.openclaw/workspace/outputs/dreambook_<timestamp>/`）
- 1 个 PDF 绘本（同样目录）
- 最后一行打印 `MEDIA:<pdf绝对路径>` 让 OpenClaw Web UI 内联预览
