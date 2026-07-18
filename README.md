# FAE-v2

> **F**ully **A**utonomous **E**cho · v2  
> 有长期记忆、能主动 loop、可本地部署的语音 Agent。

## 文档

- [ARCHITECTURE.md](./ARCHITECTURE.md)
- [doc/DEVELOPMENT_PLAN.md](./doc/DEVELOPMENT_PLAN.md)

## Phase 1（完整）· Phase 2（脚手架就绪）

| 能力 | 状态 |
|---|---|
| Docker Compose 6 服务 | ✅（ASR/Letta stub 可无 GPU） |
| FastAPI + sessions + CI | ✅ |
| 文本 pipeline + barge-in + SentenceAggregator | ✅ |
| Silero VAD + SmartTurn v3（Daily bot） | ✅ |
| Next.js UI（VoiceOrb / Mic / 文字回退） | ✅ |
| 浏览器语音（Web Speech + `/ws/chat`） | ✅ 默认 |
| Daily + Pipecat 全链路（可选） | ✅ 需 `DAILY_API_KEY` |
| DashScope Qwen3-TTS | ✅ 需 `DASHSCOPE_API_KEY` |
| `fae.memory` + Letta client 脚手架 | ✅ Phase 2 起点 |

## 快速开始

```bash
git clone https://github.com/huangyuan3h/Fae-v2.git
cd Fae-v2
cp .env.example .env
# 至少填 DASHSCOPE_API_KEY；Daily 增强再填 DAILY_API_KEY

# 开发
./start.sh
cd ui && pnpm install && pnpm dev
open http://localhost:3000

# 或 Docker
./deploy/scripts/setup.sh
./deploy/scripts/start.sh
```

### 演示

1. 打开 http://localhost:3000，在 Agent 设置填 API Key  
2. **默认路径**：点「开始说话」（Chrome）或文字输入 → 流式回复 + 浏览器播报  
3. **Daily 增强**：勾选「优先 Daily / Pipecat」→ 点开始 → 加入 WebRTC 房间（服务端跑 Silero + SmartTurn + LLM + DashScope TTS）  

### 环境变量

| 变量 | 用途 |
|---|---|
| `DASHSCOPE_API_KEY` | LLM / TTS |
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
