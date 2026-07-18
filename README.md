# FAE-v2

> **F**ully **A**utonomous **E**cho · v2
> 一个有长期记忆、能主动 loop、可本地部署的语音 Agent。

## 文档

- 📐 **[ARCHITECTURE.md](./ARCHITECTURE.md)** — 完整架构文档（必读）
- ✅ **[doc/DEVELOPMENT_PLAN.md](./doc/DEVELOPMENT_PLAN.md)** — 分阶段 checklist

## 当前进度

| 阶段 | 状态 |
|---|---|
| 1.1 基础设施 + Compose | 脚手架就绪（ASR/Letta/UI 为 stub） |
| 1.2 FastAPI + sessions + CI | 就绪 |
| 1.3 文本 pipeline 最小尝试 | 就绪（非浏览器语音） |
| 1.4 Minimal UI / VoiceOrb | 未开始 |
| 1.5 真模型一键演示 | 未开始 |

## 快速开始

### A. 本地后端开发（uv）

```bash
git clone https://github.com/huangyuan3h/Fae-v2.git
cd Fae-v2
cp .env.example .env
./start.sh
# → http://localhost:8000

curl http://localhost:8000/health
cd backend && uv run pytest
```

### B. Docker 全栈（6 服务）

```bash
./deploy/scripts/setup.sh
./deploy/scripts/start.sh
# UI:      http://localhost:3000
# Backend: http://localhost:8000
```

### 关键端点

| Method | Path | 说明 |
|---|---|---|
| GET | `/health` | 存活 |
| GET | `/ready` | 就绪 |
| POST | `/api/sessions` | 创建会话 |
| POST | `/api/chat` | 同步文本 chat |
| WS | `/ws/chat` | 流式 token |
| POST | `/api/pipeline/text` | 1.3 文本管道冒烟（LLM→句子→TTS stub） |

## 许可证

Apache 2.0
