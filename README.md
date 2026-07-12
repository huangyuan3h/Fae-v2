# FAE-v2

> **F**ully **A**utonomous **E**cho · v2
> 一个有长期记忆、能主动 loop、可本地部署的语音 Agent。

## 文档

- 📐 **[ARCHITECTURE.md](./ARCHITECTURE.md)** — 完整架构文档（必读）
- 即将推出：`docs/design/`、`docs/api/`、`examples/`

## 核心能力

- 🎙️ **实时语音对话**（Qwen3-ASR + Qwen3-TTS，Apache 2.0）
- 🧠 **长期记忆**（Letta + 多层记忆架构）
- 🎯 **主动 loop**（APScheduler + 心跳）
- 🛠️ **Skills / Tools**（Markdown 编写，参考 Vercel Eve 风格）
- 🎨 **美观 UI**（Next.js 15 + shadcn/ui）

## 快速开始（Checkpoint 1：后端骨架）

> 当前阶段：后端 FastAPI 骨架已就绪，前端 / 语音管道 / 长期记忆在后续 Checkpoint 接入。
> 详见 [`doc/DEVELOPMENT_PLAN.md`](./doc/DEVELOPMENT_PLAN.md)。

```bash
# 1. 克隆仓库
git clone https://github.com/huangyuan3h/Fae-v2.git
cd FAE-v2

# 2. 安装 uv（如果还没装）
# macOS / Linux:  curl -LsSf https://astral.sh/uv/install.sh | sh
# Homebrew:      brew install uv

# 3. 复制环境变量模板（先不用改，Checkpoint 1 还用不到 Key）
cp .env.example .env

# 4. 启动后端
./start.sh
# → Uvicorn running on http://localhost:8000

# 5. 验证
curl http://localhost:8000/health
# → {"status":"ok"}

# 6. 跑测试
cd backend && uv run pytest
# → 2 passed
```

> ⚠️ 项目仍在早期阶段，详见 [ARCHITECTURE.md](./ARCHITECTURE.md) 和 [`doc/DEVELOPMENT_PLAN.md`](./doc/DEVELOPMENT_PLAN.md)。

## 许可证

Apache 2.0