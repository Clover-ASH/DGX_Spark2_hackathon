# 📖 DreamBook — 「我想成为 XXX」童年梦想绘本 Agent

> 一张孩子照片 + 一句梦想 → 6 页绘本（PDF），孩子在里面成为梦想中的样子。
> 完全本地：DGX Spark 上跑 Ollama + ComfyUI + OpenClaw，不依赖外网。

---

## 这是什么

每个孩子小时候都说"我想成为宇航员 / 消防员 / 画家"，但都只是嘴上说。
DreamBook 让这个梦想**变成一本属于他的绘本**：上传一张孩子照片 + 一句梦想，
Agent 用本地 LLM 创作 6 页成长故事，每页用 FLUX + PuLID 生成保持人物身份的插图，
最后拼成可打印 PDF。

## 技术栈（全部本地，全部 DGX Spark）

```
用户照片 + "我想成为宇航员"
        │
        ▼
┌─────────────────────────────────────────────────┐
│ ① Ollama Qwen3.6 35B                            │  ← 创作 6 页故事
│   输出 JSON: {title, pages:[{scene, story}]}    │
└──────────────────────┬──────────────────────────┘
                       ▼
┌─────────────────────────────────────────────────┐
│ ② ComfyUI + FLUX + PuLID (循环 6 次)             │  ← 出图，身份一致
│   每页 = 孩子脸(PuLID) + 场景描述(FLUX) + 风格    │
└──────────────────────┬──────────────────────────┘
                       ▼
┌─────────────────────────────────────────────────┐
│ ③ reportlab 拼装 PDF                             │  ← 封面 + 6 页 + 封底
└──────────────────────┬──────────────────────────┘
                       ▼
              OpenClaw Web UI 内联预览
```

## 风格系统（5 预设 + 2 自定义）

| Style | 说明 | 适合 |
|---|---|---|
| `pixar` | 皮克斯 3D 动画 | 活泼、流行 |
| `ghibli` | 吉卜力水彩 | 温暖、治愈 |
| `watercolor` | 经典童书水彩 | 柔和、文艺 |
| `oil_painting` | 古典油画 | 厚重、史诗 |
| `comic` | 美漫英雄 | 动感、热血 |
| `custom_1` | 用户自定义槽位 1 | 首次用 `--custom-prompt "..."` 注入提示词 |
| `custom_2` | 用户自定义槽位 2 | 同上 |

任何风格的提示词都可以手动编辑 `styles/<name>.json` 微调。

## 部署（一键）

在 DGX Spark 节点上：

```bash
# 假设 workshop 已经跑过，环境就绪（comfyui-app/、ollama、openclaw 都装好了）
cd ~/build_a_claw_workshop-bundle   # 或你的 WORKSHOP_DIR

# 复制 dreambook skill 到 OpenClaw skills 目录
SKILL_DIR="$PWD/openclaw-home/.openclaw/skills/dreambook"
mkdir -p "$SKILL_DIR"
cp -r /path/to/dreambook/* "$SKILL_DIR/"
chmod +x "$SKILL_DIR/run_helper.sh"

# 重启 OpenClaw 让它扫描新 skill
bash scripts/openclaw-ctl.sh restart
./openclaw skills list   # 应该看到 dreambook: ready
```

或直接用项目自带脚本：`bash deploy.sh`

## 用法

### 命令行直接测试（绕过 LLM/Agent）

```bash
SKILL="$OPENCLAW_HOME/.openclaw/skills/dreambook"

# 自动从 inbound 取最新上传的照片
"$SKILL/run_helper.sh" --dream "我想成为宇航员" --style pixar

# 显式传照片
"$SKILL/run_helper.sh" \
    --face /path/to/child.jpg \
    --dream "我想成为消防员" \
    --style ghibli \
    --title "小明的消防梦"

# 自定义风格
"$SKILL/run_helper.sh" \
    --dream "我想成为科学家" \
    --style custom_1 \
    --custom-prompt "studio portrait, 1990s retro anime style, pastel color, dreamy lighting"
```

### OpenClaw 对话

1. 浏览器打开 OpenClaw Web UI（`http://<spark-ip>:3030/#token=...`）
2. 上传一张孩子正面照 📎
3. 发文字：「给我做一本绘本，梦想是我想成为宇航员，用吉卜力风格」
4. Agent 调用 dreambook skill，约 6-8 分钟出 PDF（6 页图，每页 ~1 分钟）

## 文件结构

```
dreambook/
├── SKILL.md                  # 给 OpenClaw Agent 看的契约（触发词、用法）
├── run_helper.sh             # 入口（激活 venv，调 helper）
├── dreambook_helper.py       # 主流水线：故事→出图→PDF
├── pdf_assembler.py          # reportlab 拼装 PDF
├── book_workflow.json        # ComfyUI 工作流模板（PuLID + FLUX）
├── styles/                   # 风格 JSON（prompt 前缀 + 采样参数）
│   ├── pixar.json
│   ├── ghibli.json
│   ├── watercolor.json
│   ├── oil_painting.json
│   ├── comic.json
│   ├── custom_1.json         # 用户自定义槽位（首次用时注入）
│   └── custom_2.json
└── README.md
```

## 关键技术点（写答辩/PPT 可用）

1. **身份一致性（PuLID）**：6 页都是同一个孩子脸，这是绘本可信度的核心。
   PuLID 把人脸压成 identity token 注入 FLUX，比 IP-Adapter 更稳。
2. **统一内存调度**：DGX Spark 是统一内存，LLM (33GB) 和 ComfyUI VAE 不能同时占满。
   helper 在出图前主动 `unload_ollama_models()`，出完图再 reload。
3. **LLM + 文生图协作（Agent 创作一切）**：故事大纲、分镜描述、配文全部由 LLM 生成，
   图像模型只负责"画"。这正是比赛主题"让 Agent 创作一切"的落地。
4. **可扩展风格系统**：5 预设 + 2 自定义槽位，用户既能一键用预设，也能通过
   `--custom-prompt` 或直接编辑 JSON 完全掌控风格提示词。
5. **零外网依赖**：所有模型（Qwen3.6、FLUX、PuLID、InsightFace、EVA-CLIP）都在
   DGX Spark 本地，隐私 + 速度 + 可离线。

## 评分维度对照

| 评委维度 | DreamBook 的回答 |
|---|---|
| 主题契合 | 「让 Agent 创作一切」= LLM 写故事 + FLUX 出图 + Agent 编排，全链路创作 |
| 技术深度 | Ollama + ComfyUI + PuLID + OpenClaw 全栈本地推理 |
| 创意 | 「童年梦想绘本」= 每个人都有的情感钩子，远比"超级英雄照"有温度 |
| 实用 | C 端付费场景清晰（定制绘本 29-99 元/本），家长/教育评委一眼共鸣 |
| Demo 效果 | 6-8 分钟出 6 页绘本 PDF，对比 baseline 的"1 张照片"碾压级 |

## 已知限制 / 后续可做

- 出图耗时：每页 ~1 分钟，6 页约 6-8 分钟。可优化为多页并行（需注意显存）。
- 身份一致性偶有漂移：复杂动作场景 PuLID 可能掉身份，可用 ControlNet pose 约束。
- 故事多样性：Qwen3.6 中文创作能力 OK，但偶有重复，可换更大模型或加 few-shot。
- 视频化：DGX Spark 跑视频生成难度大，先做绘本版，未来可加 CogVideoX 出短视频。
