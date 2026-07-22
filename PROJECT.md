# 📖 梦想成真 DreamBook — 「我想成为 XXX」

> **第二届 NVIDIA DGX Spark 黑客松参赛作品**
>
> 一张照片（或一句梦想）→ 一本属于你的梦想绘本 / 蓝图手册
>
> 完全本地推理，跑在 DGX Spark 上：Ollama + FLUX + 5 Agent 协作

---

## 🎯 项目缘起

小时候我们都说过"我想成为宇航员 / 消防员 / 画家"——但都只是嘴上说说。

DreamBook 让这些梦想**真正被看见**：
- 有照片 → 用 FLUX 把孩子画进梦想里的 6 个成长瞬间（**绘本**）
- 没照片 → 5 个 Agent 协作生成完整的成长地图（**蓝图**）

让 Agent 创作一切，让每个梦想都被认真对待。

---

## 🏗️ 技术架构（全程本地推理，零外网依赖）

```
用户输入："我想成为宇航员" + [可选]孩子照片
                    │
                    ▼
        ┌───────────────────────┐
        │  dreambook_router.py  │  ← 智能路由
        └───────────┬───────────┘
            ┌───────┴───────┐
            ▼               ▼
    [有照片]           [无照片]
            │               │
            ▼               ▼
    ┌──────────────┐  ┌──────────────────┐
    │  Plan A 绘本 │  │  Plan B 蓝图     │
    │              │  │                  │
    │ ① Ollama     │  │ 5 Agent 协作：    │
    │   生成6页故事│  │ ① 梦想解析师     │
    │ ② FLUX schnell│  │ ② 成长路径师     │
    │   出6张图    │  │ ③ 行动导师       │
    │ ③ PDF 拼装   │  │ ④ 风险顾问       │
    │              │  │ ⑤ 未来自传作家   │
    └──────┬───────┘  └────────┬─────────┘
           │                   │
           ▼                   ▼
    6页绘本 PDF         梦想蓝图 PDF
    （含插图）         （含未来之信）
```

---

## 🔧 技术栈

| 组件 | 版本/型号 | 用途 |
|------|----------|------|
| **DGX Spark** | GB10 (sm_121, Blackwell) | 硬件平台 |
| **Ollama** | `nemotron-3-nano:30b` (24GB) | LLM 推理（NVIDIA 自家模型，加分项）|
| **FLUX.1-schnell** | bf16, 4 步 | 文生图（10秒/张）|
| **diffusers** | 0.39.0 | 图像生成框架 |
| **PyTorch** | 2.9.1+cu130 | 深度学习（Blackwell 兼容）|
| **reportlab** | 5.0.0 | PDF 排版 |

---

## ✨ 关键技术亮点（答辩卖点）

### 1. FLUX 在 Blackwell (GB10 sm_121) 上跑通
- 节点出厂 PyTorch 不支持 sm_121（卡了 1 小时定位）
- 找到 `cu130` 环境的 reid venv，**手动验证 Blackwell 兼容性**
- bf16 + VAE tiling + attention slicing 三重内存优化
- **实测：33.7GB 显存 / 10秒一张 1024×1024 / 6 页共 1 分钟**

### 2. 全程本地，零外网依赖
- HuggingFace 不通 → 用 modelscope 镜像下 FLUX
- modelscope 自带断点续传，3 次中断后自动恢复
- 所有模型（LLM + FLUX）都在 DGX Spark 本地，**隐私 + 速度**

### 3. Agent 创作一切（契合主题）
**Plan A**：LLM 创作故事 → 图像模型负责"画"（Agent 编排）
**Plan B**：**5 个 Agent 串行协作**，纯 LLM 创作完整作品
- 梦想解析师 → 成长路径师 → 行动导师 → 风险顾问 → 未来自传作家
- 每个 Agent 输出结构化 JSON，下一个 Agent 消费
- 这是「让 Agent 创作一切」主题的纯粹体现

### 4. 智能路由覆盖所有场景
- 有照片 → 视觉冲击的绘本（适合家长/儿童）
- 没照片 → 深度内容的蓝图（适合任何追梦人）
- 一个入口，两类作品，技术叙事完整

---

## 📂 项目结构

```
DGX/
├── dreambook_router.py         ⭐ 智能路由入口（A+B 合体）
│
├── dreambook/                  📚 Plan A: 梦想绘本
│   ├── dreambook_diffusers.py    主流水线：Ollama + FLUX + PDF
│   ├── image_gen.py              FLUX 出图（diffusers 直跑）
│   ├── pdf_assembler.py          PDF 拼装（reportlab）
│   └── styles/                   7 个风格（5 预设 + 2 自定义）
│       ├── pixar.json
│       ├── ghibli.json
│       ├── watercolor.json
│       ├── oil_painting.json
│       ├── comic.json
│       ├── custom_1.json         ⭐ 用户自定义槽位 1
│       └── custom_2.json         ⭐ 用户自定义槽位 2
│
├── dreambook_planb/             📖 Plan B: 梦想蓝图
│   ├── dream_blueprint.py        5 Agent 协作主流水线
│   └── blueprint_pdf.py          蓝图 PDF 排版（精美版式）
│
├── test_flux.py                 FLUX 单图测试
├── download_flux.py             FLUX 下载脚本
├── upload_and_deploy.sh         scp 上传脚本
└── PROJECT.md                   本文件（答辩核心）
```

---

## 🚀 快速使用

### 一键跑（节点上）

```bash
# Plan A：梦想绘本（需要照片）
python3 dreambook_router.py \
    --dream "我想成为宇航员" \
    --style pixar \
    --face /path/to/child.jpg

# Plan B：梦想蓝图（无需照片）
python3 dreambook_router.py \
    --dream "我想成为宇航员" \
    --name 小明 \
    --age 8

# 自动路由（推荐）
python3 dreambook_router.py --dream "我想成为画家"  # 自动走 B
```

### 风格系统（Plan A）

| Style | 说明 |
|---|---|
| `pixar` | 皮克斯 3D 动画 |
| `ghibli` | 吉卜力水彩 |
| `watercolor` | 经典童书水彩 |
| `oil_painting` | 古典油画 |
| `comic` | 美漫英雄 |
| `custom_1/2` | 用户自定义（首次用 `--custom-prompt` 注入）|

---

## 📊 性能数据（实测）

| 指标 | 数值 |
|------|------|
| FLUX 模型加载 | 159 秒（一次性）|
| 单张图生成（4 步 schnell）| **10 秒** |
| 6 页绘本总耗时（含 LLM 故事）| **~2 分钟** |
| Plan B（5 Agent 协作）| **~3 分钟** |
| GPU 显存峰值 | 33.7 GB / 128 GB |
| 模型磁盘占用 | ~24 GB |

---

## 🎬 Demo 故事线（推荐录屏流程）

1. 开场：**「小时候你想成为什么？」**（情感钩子）
2. 演示 Plan A：上传孩子照片 + "我想成为宇航员"
   - 实时展示：Ollama 写故事 → FLUX 出图（快到震撼）
   - 出 6 页绘本 PDF
3. 演示 Plan B：输入"我想成为画家"
   - 实时展示：5 个 Agent 串行协作的日志
   - 出含「未来之信」的蓝图 PDF
4. 收尾：**「梦想这条路，一旦开始走，就已经在实现」**

---

## 🛣️ 后续可做（未完成的优化）

- [ ] 加 PuLID-Flux（6 页身份一致性，目前是简化版）
- [ ] OpenClaw Skill 集成（目前是命令行，可包装成聊天 Agent）
- [ ] 多语言支持
- [ ] 视频化（CogVideoX 生成 5 秒短片，DGX Spark 能跑但耗时长）

---

## 🙏 致谢

- NVIDIA DGX Spark 团队的硬件支持
- Black Forest Labs 的 FLUX.1-schnell 开源
- ModelScope 提供国内镜像
- Ollama 让本地 LLM 推理变简单
