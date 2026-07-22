---
name: superhero
description: "Generate a 1024x1024 superhero-style portrait via local FLUX.1-schnell. Use when: user asks 帮我生成超级英雄照片, 超级英雄, 超人, 变装, superhero photo, hero look, or describes a hero they want visualized."
metadata: { "openclaw": { "emoji": "🦸", "requires": { "bins": ["python3", "bash"] } } }
---

# Superhero Photo Generator

用本地 FLUX.1-schnell（diffusers 直跑，DGX Spark GB10）生成超级英雄风格肖像。
可选接入 Ollama qwen3.6：用户给一句话描述 → LLM 扩写成 FLUX prompt。

## Run

**默认超级英雄照**（推荐，最稳）：

```bash
"$SKILL_HOME/run_helper.sh"
```

**带一句话描述**（LLM 扩写为 FLUX prompt，更有针对性）：

```bash
"$SKILL_HOME/run_helper.sh" --desc "穿着金色铠甲飞行的战士"
```

**直接给英文 prompt**（跳过 LLM，最快）：

```bash
"$SKILL_HOME/run_helper.sh" --prompt "a superhero in red suit over a night city, cinematic"
```

`$SKILL_HOME` 是本 skill 所在目录的绝对路径。

## Output

helper 在 stdout 最后一行打印：

```
MEDIA:<absolute_path_to_png>
```

把这一整行原样复制到回复里：

```
你的超级英雄照片来啦！
MEDIA:<helper 真正打印的那条路径>
```

## Rules

- 直接执行，不要先说"正在生成"。
- 单次约 2-3 分钟（含模型加载，模型常驻后约 10 秒/张）。
- 命令失败只回复"生成失败，请稍后重试"。
- 不要展示 stderr/路径等中间输出，只保留 `MEDIA:` 行 + 一句话寒暄。

## 参数

| 参数 | 说明 |
|------|------|
| `--desc` | 口语描述（任意语言），LLM 扩写为 prompt |
| `--prompt` | 直接给 FLUX 英文 prompt（跳过 LLM）|
| `--steps` | 采样步数，默认 4（schnell 推荐）|
| `--seed` | 固定种子（复现）|
| `--out` | 输出路径，默认 `~/superhero_output/superhero_<时间>.png` |

## 环境变量

| 变量 | 默认 |
|------|------|
| `SUPERHERO_PYTHON` | `python3`（含 diffusers+torch）|
| `FLUX_MODEL_PATH` | `~/ms_cache/models/AI-ModelScope--FLUX.1-schnell/snapshots/master` |
| `OLLAMA_URL` | `http://127.0.0.1:11434` |
| `OLLAMA_MODEL` | `qwen3.6:35b-a3b-q4_K_M` |
