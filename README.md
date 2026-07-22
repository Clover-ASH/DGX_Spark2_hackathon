# 🦸‍♂️ DGX Spark 本地 Agent — Superhero & DreamBook

> 第二届 NVIDIA DGX Spark 黑客松参赛作品
>
> 在 DGX Spark（GB10 Blackwell）上构建**完全本地**的多模态 Agent：
> LLM（Ollama qwen3.6）创作 + FLUX.1-schnell 出图，全程零外网依赖。

![hero](docs/superhero_images/superhero_20260722_145856.png)

---

## 📌 这是什么

两个本地 Agent 项目，共享同一套本地推理底座：

| 项目 | 一句话 | 输入 → 输出 |
|------|--------|------------|
| **🦸 Superhero** | 超级英雄照片生成器 | 一句话描述 → qwen3.6 扩写 prompt → FLUX 出 1024² 肖像 |
| **📖 DreamBook** | 「我想成为 XXX」梦想绘本 | 一句梦想（+可选照片）→ LLM 写故事 + FLUX 出 6 页 → PDF |

### 核心能力链路

```
用户一句话（任意语言）
        │
        ▼
┌─────────────────────────┐
│ Ollama qwen3.6:35b      │  ← 本地 LLM：扩写 prompt / 创作故事
└───────────┬─────────────┘
            ▼
┌─────────────────────────┐
│ FLUX.1-schnell (bf16)   │  ← 本地文生图：4 步采样，~10s/张
└───────────┬─────────────┘
            ▼
      PNG / PDF 产物
```

---

## ✅ 已验证（实测数据）

在 DGX Spark GB10（sm_121, 统一内存）上端到端跑通：

| 指标 | 数值 |
|------|------|
| 模型加载（一次性） | ~140-160s |
| 单张 1024×1024 出图（4 步 schnell） | **10-12 秒** |
| GPU 显存峰值 | **33.7 GB** |
| 完整 Agent 链路（中文→LLM→FLUX） | ✅ 出图 |

示例图见 [`docs/superhero_images/`](docs/superhero_images/)。

---

## 🏗️ 技术栈

| 组件 | 版本/型号 | 用途 |
|------|----------|------|
| **DGX Spark** | GB10 (sm_121, Blackwell) | 硬件平台 |
| **Ollama** | `qwen3.6:35b-a3b-q4_K_M` (23GB) | 本地 LLM 推理 |
| **FLUX.1-schnell** | bf16, 4 步 | 本地文生图 |
| **diffusers** | 0.39.0 | 图像生成框架 |
| **PyTorch** | 2.9.1+cu130 | 深度学习（Blackwell 兼容）|
| **reportlab** | — | PDF 拼装（DreamBook） |

---

## 📁 项目结构

```
.
├── superhero/              🦸 超级英雄照片生成器（本次完赛核心）
│   ├── SKILL.md              skill 契约（触发词 + MEDIA 协议）
│   ├── run_helper.sh         入口
│   ├── superhero_helper.py   后端：LLM扩写 → FLUX 出图
│   └── README.md             详细文档
│
├── dreambook/              📖 梦想绘本（Plan A：FLUX 出图 + PDF）
│   ├── image_gen.py          FLUX 出图（diffusers 直跑，GB10 适配）
│   ├── dreambook_diffusers.py 主流水线
│   ├── pdf_assembler.py      reportlab 拼装
│   └── styles/               7 个风格（pixar/ghibli/watercolor…）
│
├── dreambook_planb/        📖 梦想蓝图（Plan B：5 Agent 协作 + PDF）
│   ├── dream_blueprint.py    5 Agent 串行流水线
│   └── blueprint_pdf.py      蓝图 PDF 排版
│
├── webapp/                 🌐 FastAPI Web 界面（SSE 实时日志）
│   ├── server.py
│   └── static/index.html
│
├── dreambook_router.py     智能路由（有照片→绘本，无照片→蓝图）
├── PROJECT.md              答辩核心文档
└── docs/                  demo 视频 + 生成的示例图
```

---

## 🚀 快速开始

### 环境要求

- DGX Spark（或任意有 NVIDIA GPU + 足够显存的 Linux 机器）
- 一个装了 `diffusers` + `torch(+CUDA)` 的 Python 环境
- Ollama 服务在跑，且已拉取 `qwen3.6:35b-a3b-q4_K_M`（或同类模型）
- FLUX.1-schnell 模型已下载到本地

### 配置环境变量

```bash
# 指向含 diffusers+torch 的 Python 解释器
export SUPERHERO_PYTHON=/path/to/your/python3
export DREAMBOOK_PYTHON=/path/to/your/python3

# FLUX 模型路径
export FLUX_MODEL_PATH=/path/to/FLUX.1-schnell

# Ollama（默认即本机）
export OLLAMA_URL=http://127.0.0.1:11434
export OLLAMA_MODEL=qwen3.6:35b-a3b-q4_K_M
```

### 跑 Superhero（最简）

```bash
# 演示前确保 GPU 干净（释放可能占显存的进程/模型）
# 默认超级英雄照
./superhero/run_helper.sh --no-llm

# 一句话描述 → LLM 扩写 → 出图（推荐）
./superhero/run_helper.sh --desc "穿着金色铠甲飞行的战士"
```

最后一行输出 `MEDIA:/path/to/superhero_<时间>.png` 即成功。

更多见 [`superhero/README.md`](superhero/README.md)。

---

## 🎯 与官方 Workshop 的关系

官方 workshop notebook《在 DGX Spark 上构建 OpenClaw + ComfyUI 超级英雄照片生成》
设定的技术栈是 `OpenClaw → ComfyUI(HTTP) → FLUX + PuLID`。

本仓库在官方技术栈之外提供了一条**等效落地路径**：当节点没有预装 ComfyUI/PuLID
环境时，用 **diffusers 直跑 FLUX** 实现相同的 Agent 创作闭环（LLM 创作 prompt +
图像模型出图），skill 契约与 `MEDIA:` rich-output 协议保持一致。

| 维度 | 官方 notebook | 本仓库 |
|------|--------------|--------|
| 文生图模型 | FLUX.1-dev (fp8) | FLUX.1-schnell (bf16) |
| 推理引擎 | ComfyUI 节点图 | diffusers 直跑 |
| LLM | qwen3.6:35b | qwen3.6:35b ✅ 一致 |
| Agent 编排 | OpenClaw skill | 等效 skill + 命令行 |
| `MEDIA:` 协议 | ✅ | ✅ 一致 |
| 完全本地、零外网 | ✅ | ✅ 一致 |

> 注：本实现不含 PuLID，不保证人脸身份一致性（生成的是基于文本的超级英雄场景图）。

---

## 🛠️ 技术亮点

1. **GB10 (sm_121) Blackwell 兼容**：torch 2.9.1+cu130 实测可跑，
   bf16 + VAE tiling + attention slicing 三重内存优化。
2. **统一内存调度**：出图前主动卸载 LLM（`keep_alive:0`），避免显存抢占死锁。
3. **Agent 创作一切**：LLM 负责把模糊口语扩写成精确 FLUX prompt，图像模型只负责"画"。
4. **OOM 自动降级**：1024 → 768 → 512 三档分辨率自动回退。
5. **零外网**：FLUX（modelscope 镜像）+ qwen3.6 全在本地。

---

## 📄 License

MIT — 见 [LICENSE](LICENSE)。
