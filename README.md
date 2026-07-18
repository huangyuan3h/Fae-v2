# FAE-v2

> **F**ully **A**utonomous **E**cho · v2  
> 有长期记忆、能主动 loop、可本地部署的语音 Agent。

## 文档

- [ARCHITECTURE.md](./ARCHITECTURE.md) — 架构
- [doc/DEVELOPMENT_PLAN.md](./doc/DEVELOPMENT_PLAN.md) — 分阶段 checklist

## Phase 1 状态

| 项 | 状态 |
|---|---|
| Docker Compose 6 服务 | ✅（ASR/Letta 仍为 stub，可无 GPU 起栈） |
| FastAPI + sessions + CI | ✅ |
| 文本 pipeline + barge-in + Energy VAD | ✅ |
| Next.js UI（VoiceOrb / Mic / 文字回退） | ✅ |
| 浏览器语音对话（Web Speech STT/TTS + `/ws/chat`） | ✅ |
| Daily / Silero / 真 ASR GPU | 预留接口，需 Key / GPU 后替换 |

## 快速开始

```bash
git clone https://github.com/huangyuan3h/Fae-v2.git
cd Fae-v2
cp .env.example .env
# 填入 DASHSCOPE_API_KEY（或在 UI「Agent 设置」里填 API Key）

# 方式 A：本地开发
./start.sh                  # backend :8000
cd ui && pnpm install && pnpm dev   # UI :3000

# 方式 B：Docker 一键起
./deploy/scripts/setup.sh
./deploy/scripts/start.sh
open http://localhost:3000
```

### 演示路径（M1）

1. 打开 http://localhost:3000  
2. 在「Agent 设置」填入 OpenAI-compatible `base_url` / `api_key` / `model`（如 DashScope）  
3. 点击「开始说话」（Chrome）或使用文字输入  
4. 听到 / 看到流式回复；可点「打断」做 barge-in  

### 常用端点

| Method | Path | 说明 |
|---|---|---|
| GET | `/health` | 存活 |
| POST | `/api/sessions` | 会话 |
| POST | `/api/voice/session` | 语音会话 bootstrap |
| POST | `/api/chat` | 同步 chat |
| WS | `/ws/chat` | 流式 token |
| POST | `/api/pipeline/text` | 文本管道冒烟 |

## 测试

```bash
cd backend && uv run pytest
cd ui && pnpm lint && pnpm build
```

## 许可证

Apache 2.0
