# 完赛报告书 · DGX Spark 本地 Agent 项目

> 第二届 NVIDIA DGX Spark 黑客松 · 参赛作品完赛报告
>
> 项目：Superhero 超级英雄照片生成器 & DreamBook 梦想绘本
>
> 仓库：https://github.com/Clover-ASH/DGX_Spark2_hackathon

---

## 一、项目概述

### 1.1 一句话定位

在 NVIDIA DGX Spark（GB10 Blackwell）上，构建**完全本地、零外网依赖**的多模态
Agent：用本地 LLM（Ollama qwen3.6）创作文本、用本地 FLUX.1-schnell 生成图像，
实现"让 Agent 创作一切"的完整闭环。

### 1.2 解决的问题

黑客松主题是"让 Agent 创作一切"。我们将这个主题落地为两个面向真实用户的场景：

| 项目 | 场景 | 价值 |
|------|------|------|
| **Superhero** | 用户一句话描述 → Agent 生成超级英雄肖像 | 娱乐 / 个性化定制 |
| **DreamBook** | 「我想成为 XXX」→ Agent 创作绘本 PDF | 教育 / 情感共鸣（C 端付费场景清晰）|

核心主张：**用户只需要一句自然语言输入，LLM 负责理解与创作（扩写 prompt、写故事、
规划成长路径），图像模型只负责"画"。** 全链路在本地完成，隐私可控、响应快、可离线。

### 1.3 完赛状态

✅ **已端到端验证通过并出图**，两条链路均实测：

| 链路 | 输入 | 耗时 | 结果 |
|------|------|------|------|
| 默认 prompt 出图 | 无 | 加载 160s + 出图 10s | ✅ PNG |
| 完整 Agent 链路 | 中文"金色铠甲闪电侠" | LLM 10s + 加载 140s + 出图 12s | ✅ PNG |

---

## 二、技术架构

### 2.1 整体架构

```
用户一句话（任意语言）
        │
        ▼
┌─────────────────────────────┐
│  Ollama qwen3.6:35b         │  本地 LLM
│  · 扩写 FLUX prompt          │  · 跨语言理解
│  · 创作故事 / 规划路径        │  · 结构化 JSON 输出
└──────────────┬──────────────┘
               ▼
┌─────────────────────────────┐
│  FLUX.1-schnell (bf16)      │  本地文生图
│  · 4 步采样                  │  · 1024×1024
│  · VAE tiling + attn slicing │  · ~10s/张
└──────────────┬──────────────┘
               ▼
         PNG / PDF 产物
```

### 2.2 技术栈

| 层 | 选型 | 说明 |
|----|------|------|
| 硬件 | DGX Spark GB10 (sm_121, Blackwell) | 统一内存架构 |
| LLM 推理 | Ollama + `qwen3.6:35b-a3b-q4_K_M` (23GB) | NVIDIA 自家 / 通义千问 |
| 文生图 | FLUX.1-schnell (bf16, 4 步) | Black Forest Labs 开源 |
| 图像框架 | diffusers 0.39.0 | 节点式扩散模型推理 |
| 深度学习 | PyTorch 2.9.1+cu130 | Blackwell (sm_121) 兼容 |
| PDF 排版 | reportlab | DreamBook 绘本 / 蓝图 |
| Web 服务 | FastAPI + SSE | 实时日志推送（webapp）|

### 2.3 Agent 编排设计

**Superhero（单 Agent + 工具协作）**：
```
用户中文输入 → [qwen3.6 扩写 prompt] → [FLUX 出图] → MEDIA: 输出
```
LLM 作为"创作 Agent"，FLUX 作为"绘图工具"，Agent 编排两者的协作。

**DreamBook Plan B（多 Agent 串行协作）**：
```
梦想解析师 → 成长路径师 → 行动导师 → 风险顾问 → 未来自传作家
```
5 个角色化 Agent 串行协作，每个输出结构化 JSON 供下一个消费，最终拼成梦想蓝图 PDF。

---

## 三、关键技术实现

### 3.1 GB10 (sm_121) Blackwell 兼容性

**问题**：DGX Spark 出厂自带的 PyTorch 官方支持范围是 sm 8.0–12.0，而 GB10 是
**sm_121（12.1）**，超出官方声明范围，直接用会报 capability 不匹配。

**解决**：使用基于 **CUDA 13.0 (cu130)** 构建的 PyTorch 2.9.1，配合 FLUX 的
**bf16 精度**，实测可在 GB10 上稳定运行。这是"在 Blackwell 新架构上跑通 FLUX"
的工程验证。

**三重内存优化**（针对统一内存）：
- `vae.enable_tiling()` — VAE 解码分块，降低峰值显存
- `enable_attention_slicing()` — 注意力计算分片
- bf16 精度 — 相比 fp32 减半显存占用

### 3.2 统一内存调度（DGX Spark 核心挑战）

**问题**：DGX Spark 是统一内存架构，LLM（~33GB）与图像模型 VAE 共享同一块内存。
若两者同时驻留，VAE 解码会因显存不足而死锁。

**解决**：出图前主动卸载 LLM——向 Ollama 发送 `keep_alive: 0`，强制释放 GPU
显存给 FLUX 使用。实测发现，**残留的 GPU 进程（如长期运行的 Web 服务）会污染
CUDA context**，导致后续 `to("cuda")` 报 OOM。演示前必须清理这类残留进程。

### 3.3 LLM + 文生图协作（"让 Agent 创作一切"）

用户只需一句自然语言（如"金色铠甲闪电侠"），qwen3.6 负责将其**扩写成精确的英文
FLUX prompt**（如 *"A photorealistic action shot of the Golden Armored Flash,
clad in gleaming gold armor, sprinting with intense speed..."*），图像模型据此生成。
LLM 承担"理解 + 创意表达"，图像模型承担"视觉实现"——这正是主题的纯粹体现。

### 3.4 鲁棒性设计

- **OOM 自动降级**：1024 → 768 → 512 三档分辨率自动回退，单张失败不中断整批
- **CUDA 脏状态自愈**：检测到 context 损坏时自动重启推理引擎重试
- **qwen3.6 thinking 模式处理**：该模型默认把答案塞进 `thinking` 字段而 `content`
  为空，通过 `think: false` 参数关闭，确保拿到实际回答

### 3.5 零外网依赖

所有模型（qwen3.6、FLUX.1-schnell）均在 DGX Spark 本地：
- FLUX 通过 modelscope 国内镜像下载，自带断点续传
- 全程不依赖 HuggingFace / OpenAI 等外部 API
- 收益：**隐私可控 + 响应快 + 可离线**

---

## 四、验证数据（实测）

### 4.1 性能指标

| 指标 | 实测值 |
|------|--------|
| FLUX 模型加载（一次性） | 140–160 秒 |
| 单张 1024×1024 出图（4 步 schnell） | **10–12 秒** |
| GPU 显存峰值 | **33.7 GB**（统一内存）|
| LLM 扩写 prompt | ~10 秒 |

### 4.2 端到端验证记录

**链路 1：默认 prompt 出图**
```
$ ~/superhero/run_helper.sh --no-llm --seed 42
[superhero] ✅ model loaded in 159.9s (GPU 33.7GB allocated)
[superhero] ✅ saved superhero_20260722_144329.png (10.4s)
MEDIA:/home/$USER/superhero_output/superhero_20260722_144329.png
```

**链路 2：完整 Agent 链路（中文 → LLM → FLUX）**
```
$ ~/superhero/run_helper.sh --desc "金色铠甲闪电侠" --seed 7
[superhero] LLM prompt: A photorealistic action shot of the Golden Armored Flash,
              a superhero clad in intricate, gleaming gold armor, sprinting...
[superhero] ✅ model loaded in 140.1s (GPU 33.7GB allocated)
[superhero] ✅ saved superhero_20260722_145856.png (11.9s)
MEDIA:/home/$USER/superhero_output/superhero_20260722_145856.png
```

### 4.3 示例产出

见仓库 [`docs/examples/`](docs/examples/)：
- `superhero_default.png` — 默认超级英雄 prompt 出图
- `superhero_golden_flash.png` — "金色铠甲闪电侠" Agent 链路出图

---

## 五、与官方 Workshop 的关系

官方 workshop notebook 设定的技术栈为 `OpenClaw → ComfyUI(HTTP) → FLUX + PuLID`，
依赖"IT 预装 bundle（ComfyUI + FLUX-dev + PuLID + comfyui-env）"。

本作品在节点**未预装该 bundle**（无 ComfyUI、无 PuLID、无相关 venv）的约束下，
提供了一条**等效落地路径**：用 **diffusers 直跑 FLUX** 实现相同的 Agent 创作闭环。

| 维度 | 官方 notebook | 本作品 |
|------|--------------|--------|
| 文生图模型 | FLUX.1-dev (fp8) | FLUX.1-schnell (bf16) |
| 推理引擎 | ComfyUI 节点图 | diffusers 直跑 |
| LLM | qwen3.6:35b | qwen3.6:35b ✅ 一致 |
| Agent 编排 | OpenClaw skill | 等效 skill + 命令行 / Web |
| `MEDIA:` rich-output 协议 | ✅ | ✅ 一致 |
| 完全本地、零外网 | ✅ | ✅ 一致 |
| 人脸身份一致性 | PuLID | 无（已知限制）|

skill 契约（`SKILL.md`）与 `MEDIA:` 输出协议完全对齐官方设计，保证了与 OpenClaw
生态的兼容性。

---

## 六、项目结构

```
.
├── superhero/              🦸 超级英雄照片生成器（完赛核心）
│   ├── SKILL.md              skill 契约
│   ├── run_helper.sh         入口
│   ├── superhero_helper.py   后端：LLM扩写 → FLUX 出图
│   └── README.md
├── dreambook/              📖 梦想绘本 Plan A（FLUX 6 页 + PDF）
├── dreambook_planb/        📖 梦想蓝图 Plan B（5 Agent 协作）
├── webapp/                 🌐 FastAPI Web 界面（SSE 实时日志）
├── dreambook_router.py     智能路由（有照片→绘本，无照片→蓝图）
├── docs/examples/          示例输出图
├── PROJECT.md              答辩核心文档
├── REPORT.md               本报告
└── README.md
```

---

## 七、答辩要点

1. **主题契合**：「让 Agent 创作一切」= LLM 写 prompt/故事 + FLUX 出图 + Agent 编排，
   全链路创作闭环，Superhero 体现"单 Agent + 工具"，DreamBook Plan B 体现"5 Agent 串行协作"。

2. **技术深度**：在 GB10 (sm_121) 这种 PyTorch 官方尚未声明支持的新架构上，
   验证了 FLUX 的本地推理可行性（bf16 + cu130），并解决了统一内存调度的核心难题。

3. **工程鲁棒性**：OOM 自动降级、CUDA 脏状态自愈、thinking 模式处理等，保证演示稳定。

4. **创意与场景**：「童年梦想绘本」是每个人都有的情感钩子，比"超级英雄照"更有温度；
   C 端付费场景清晰（定制绘本 29–99 元/本），家长 / 教育评委一眼共鸣。

5. **完全本地**：零外网依赖，隐私 + 速度 + 可离线，契合 DGX Spark"本地超算"的产品定位。

---

## 八、已知限制与后续工作

| 项 | 说明 | 后续 |
|----|------|------|
| 人脸身份一致性 | 当前无 PuLID，不保证脸像本人 | 可集成 PuLID-Flux |
| 模型加载耗时 | 首次 140–160s | 可做常驻服务，加载一次后秒级响应 |
| 单语言优化 | LLM 扩写对中文输入效果好 | 可加多语言 few-shot |
| 视频化 | DGX Spark 跑视频生成耗时长 | 可探索 CogVideoX 短片 |

---

## 九、致谢

- NVIDIA DGX Spark 团队的硬件支持
- Black Forest Labs 的 FLUX.1-schnell 开源
- ModelScope 提供国内镜像
- Ollama 让本地 LLM 推理变简单
- 阿里通义实验室的 qwen3.6 模型

---

*本报告对应代码已开源：https://github.com/Clover-ASH/DGX_Spark2_hackathon*
