# 🦸 Superhero Photo Generator — DGX Spark 完赛实现

> 基于 NVIDIA DGX Spark（GB10 Blackwell）的**完全本地**超级英雄照片生成 Agent。
> LLM（Ollama qwen3.6）创作 prompt → FLUX.1-schnell 出图，全程零外网。

---

## ✅ 完赛状态：已验证通过

两条链路均已端到端跑通并出图：

| 链路 | 输入 | 过程 | 实测耗时 | 结果 |
|------|------|------|---------|------|
| 默认 prompt | 无 | FLUX 内置超级英雄 prompt → 出图 | 加载 160s + 出图 10s | ✅ `superhero_20260722_144329.png` |
| **完整 Agent 链路** | 中文一句话"金色铠甲闪电侠" | qwen3.6 扩写英文 prompt → FLUX 出图 | LLM ~10s + 加载 140s + 出图 12s | ✅ `superhero_20260722_145856.png` |

**性能数据（实测）**：
- 模型加载：140-160s（一次性，FLUX.1-schnell bf16）
- 单张出图：**10-12 秒**（1024×1024，4 步 schnell）
- GPU 显存峰值：**33.7 GB**（GB10 统一内存）

---

## 🎯 与官方 Workshop 的关系

官方 notebook《在 DGX Spark 上构建 OpenClaw + ComfyUI 超级英雄照片生成 Workshop》
设定的技术栈是 `OpenClaw → ComfyUI(HTTP) → FLUX + PuLID`，并明确依赖"IT 已预装
bundle（ComfyUI + FLUX-dev + PuLID + comfyui-env venv）"。

**本节点实际情况**：该预装 bundle 不存在（无 ComfyUI、无 PuLID、无 comfyui-env、
无 sudo 免密）。但节点上有**等效可用的本地资产**：

| 资产 | 状态 |
|------|------|
| FLUX.1-schnell 模型 | ✅ 完整 32GB（`~/ms_cache/models/AI-ModelScope--FLUX.1-schnell/`）|
| diffusers + torch 环境 | ✅ reid conda env（diffusers 0.39 + torch 2.9.1+cu130，GB10 已验证）|
| Ollama + qwen3.6 | ✅ 在跑（`qwen3.6:35b-a3b-q4_K_M`，:11434）|

因此采用**等效完赛路径**：后端从 ComfyUI HTTP API 换成 **diffusers 直跑 FLUX**，
skill 契约（`SKILL.md` + `MEDIA:` rich-output 协议）完全保留。

| 维度 | 官方 notebook | 本实现 |
|------|--------------|--------|
| 文生图模型 | FLUX.1-dev (fp8) | FLUX.1-schnell (bf16) |
| 推理引擎 | ComfyUI 节点图 | diffusers 直跑 |
| LLM | qwen3.6:35b | qwen3.6:35b-a3b-q4_K_M ✅ 一致 |
| 人脸身份一致性 | PuLID | ❌ 无（不要求脸一致）|
| Agent 编排 | OpenClaw skill | 等效 skill + 命令行 |
| `MEDIA:` 输出协议 | ✅ | ✅ 一致 |
| 完全本地、零外网 | ✅ | ✅ 一致 |

---

## 📁 文件结构

```
~/superhero/
├── SKILL.md              # skill 契约：触发词 + 调用规范 + MEDIA 协议
├── run_helper.sh         # 入口：用 reid env 的 python 跑 helper
└── superhero_helper.py   # 后端：LLM扩写(可选) → FLUX diffusers 出图 → MEDIA:
```

---

## 🚀 使用方法

### 0. 演示前必做（避免 OOM）

```bash
# 杀掉占用 GPU 的旧进程（DreamBook 的 webapp/server.py 是 OOM 元凶）
pkill -f "webapp/server.py" 2>/dev/null
pkill -f "superhero_helper" 2>/dev/null
# 让 ollama 释放显存
curl -s http://127.0.0.1:11434/api/generate \
    -d '{"model":"qwen3.6:35b-a3b-q4_K_M","keep_alive":0}' >/dev/null
```

### 1. 默认超级英雄照（最稳）

```bash
~/superhero/run_helper.sh --no-llm
# → MEDIA:/home/$USER/superhero_output/superhero_<时间>.png
```

### 2. 一句话描述 → LLM 扩写 → 出图（推荐演示，体现 Agent 创作）

```bash
~/superhero/run_helper.sh --desc "穿着金色铠甲飞行的战士"
# qwen3.6 把中文扩写成英文 FLUX prompt，再出图
```

### 3. 直接给英文 prompt（跳过 LLM，最快）

```bash
~/superhero/run_helper.sh --prompt "a superhero in red suit over a night city, cinematic"
```

### 参数

| 参数 | 说明 |
|------|------|
| `--desc` | 口语描述（任意语言），LLM 扩写为 prompt |
| `--prompt` | 直接给 FLUX 英文 prompt（跳过 LLM）|
| `--no-llm` | 用内置默认超级英雄 prompt |
| `--steps` | 采样步数，默认 4（schnell 推荐）|
| `--seed` | 固定种子（复现）|
| `--out` | 输出路径，默认 `~/superhero_output/superhero_<时间>.png` |

输出图都在 `~/superhero_output/`。

---

## 🛠️ 技术要点（答辩可用）

1. **GB10 (sm_121) Blackwell 兼容性**：节点出厂 PyTorch 官方支持范围是
   sm 8.0-12.0，GB10 是 12.1。用 cu130 构建的 torch 2.9.1 实测可跑，
   bf16 精度 + VAE tiling + attention slicing 三重内存优化，33.7GB 稳定运行。

2. **统一内存调度**：DGX Spark 是统一内存架构，必须保证出图前 GPU 干净。
   - 演示前杀掉 `webapp/server.py`（它会残留 CUDA context 导致 OOM）
   - 出图前 unload ollama 模型（`keep_alive:0`）

3. **Agent 创作一切**（契合主题）：用户只给一句中文，qwen3.6 负责把模糊描述
   扩写成精确的英文 FLUX prompt，图像模型只负责"画"。LLM + 文生图协作的完整闭环。

4. **OOM 自动降级**：1024 → 768 → 512 三档分辨率自动回退，单张失败不中断。

5. **零外网依赖**：FLUX.1-schnell（modelscope 镜像下载）+ qwen3.6 全在本地，
   隐私 + 速度 + 可离线。

---

## ⚠️ 已知限制

- **无人脸身份一致性**：本实现无 PuLID，图是 FLUX 凭文本生成的超级英雄场景，
  不会复刻上传者本人的脸。要实现需另装 PuLID-Flux（节点当前未安装）。
- **首次加载慢**：模型加载 140-160s（一次性），之后常驻约 10s/张。
  演示时建议提前 warm up 一次。
- **`webapp/server.py` 冲突**：DreamBook 的 web 服务会占脏 GPU context，
  演示前务必杀掉（见"演示前必做"）。

---

## 🔁 复现命令（验证记录）

```bash
# 链路1：默认 prompt
~/superhero/run_helper.sh --no-llm --seed 42
# → MEDIA:/home/$USER/superhero_output/superhero_20260722_144329.png (10.4s)

# 链路2：完整 Agent
~/superhero/run_helper.sh --desc "金色铠甲闪电侠" --seed 7
# qwen3.6 扩写 → "A photorealistic action shot of the Golden Armored Flash..."
# → MEDIA:/home/$USER/superhero_output/superhero_20260722_145856.png (11.9s)
```
