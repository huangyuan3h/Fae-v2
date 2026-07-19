# FAE-v2

> **F**ully **A**utonomous **E**cho · v2  
> 有长期记忆、能主动 loop、可本地部署的语音 Agent。

## 文档

- [ARCHITECTURE.md](./ARCHITECTURE.md)
- [doc/DEVELOPMENT_PLAN.md](./doc/DEVELOPMENT_PLAN.md)

## Phase 1（完整）· Phase 2.1（记忆 M2-1）

| 能力 | 状态 |
|---|---|
| Docker Compose 6 服务 | ✅（ASR stub；Letta 官方镜像） |
| FastAPI + sessions + CI | ✅ |
| 文本 pipeline + barge-in + SentenceAggregator | ✅ |
| Silero VAD + SmartTurn v3（Daily bot） | ✅ |
| Next.js UI（VoiceOrb / Mic / 文字回退） | ✅ |
| 浏览器语音（Web Speech + `/ws/chat`） | ✅ 默认 |
| Daily + Pipecat 全链路（可选） | ✅ 需 `DAILY_API_KEY` |
| DashScope Qwen3-TTS | ✅ 需 `DASHSCOPE_API_KEY` |
| 长期记忆（Letta remote / embedded SQLite） | ✅ Phase 2.1 · M2-1 |
| 会话 Recall + Daily 记忆注入 | ✅ Phase 2.2 · M2-2 |
| 统一 Recall + Archival 压缩 | ✅ Phase 2.3（超 N 轮 → Qdrant/`fae_archival`；`GET /api/memory/stats`） |
| sleeptime 闲时整理 | ✅ Phase 2.4（idle/daily + `POST /api/memory/consolidate`） |
| Episodic 事件 + archival 降权 | ✅ Phase 2.3b（`GET /api/memory/events`；180 天未访问降权） |
| 记忆浏览器 UI | ✅ Phase 2.5（`/memory` 时间线 · 事实 CRUD · 搜索） |

## 快速开始

```bash
git clone https://github.com/huangyuan3h/Fae-v2.git
cd Fae-v2
cp .env.example .env
# 推荐：.env → LETTA_MODE=embedded
# TTS / Daily 再填 DASHSCOPE_API_KEY、DAILY_API_KEY

# 首次安装依赖
npm install          # 根目录：concurrently
npm run setup        # backend (uv) + ui (pnpm)

# 一条命令同时起 backend(:8000) + UI(:3000)
npm run dev
open http://localhost:3000

# 或 Docker（官方 Letta + Postgres 卷）
./deploy/scripts/setup.sh
./deploy/scripts/start.sh
```

### 演示

1. 打开 http://localhost:3000 → **Settings → 模型**，添加 OpenAI / Ollama 配置并设为当前使用  
2. 根目录 `.env` 设置 `DASHSCOPE_API_KEY`（**Qwen3-TTS**，不需要 Daily）并重启后端  
3. **默认路径**：说话或打字 → 流式回复 + **Qwen3-TTS** 播报（失败才降级浏览器朗读）  
4. **Daily（可选）**：Settings → 语音 → 高级 → 勾选 Daily（需 `DAILY_API_KEY`）  
5. **M2-1 记忆**：说「我叫小明」→ 关掉页面重开 → 问「我叫什么」→ 应答「小明」  
6. **M2-2 回忆**：聊「Python 项目」等几个话题 → 问「刚才 Python 那个项目」→ 回复能沾边

LLM API Key / Base URL / Model 保存在浏览器 localStorage（Settings），不必写进根目录 `.env`。

### 环境变量

| 变量 | 用途 |
|---|---|
| `DASHSCOPE_API_KEY` | 服务端 TTS（及未走 UI 配置时的默认 LLM） |
| `LETTA_MODE` | `remote`（Compose Letta）/ `embedded`（本地 SQLite）/ `off` |
| `LETTA_SERVER_URL` | remote 时的 Letta 地址（默认 `http://localhost:8283`） |
| `LETTA_AGENT_NAME` | 默认 `fae-main` |
| `DAILY_API_KEY` | 可选，启用 Pipecat Daily 路径 |
| `VLLM_ASR_URL` | OpenAI-compatible STT（compose stub 默认 `:8001`） |
| `CORS_ORIGINS` | UI 源 |

## 测试

```bash
cd backend && UV_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple uv sync --group dev && uv run pytest
cd ui && pnpm lint && pnpm build
```

## 许可证

Apache 2.0
