# FAE-v2

> **F**ully **A**utonomous **E**cho · v2  
> 有长期记忆、能主动 loop、可本地部署的语音 Agent。

## 文档

- [doc/ARCHITECTURE.md](./doc/ARCHITECTURE.md) — 架构真相源（默认语音路径 / Daily 可选 / LiveKit 未实现 / MCP 暂缓）
- [doc/DEVELOPMENT_PLAN.md](./doc/DEVELOPMENT_PLAN.md) — 阶段状态与验收
- [doc/LOCAL_TTS.md](./doc/LOCAL_TTS.md) — 本机 TTS
- [evals/README.md](./evals/README.md) — 最小评测集（Phase Q.5）

## 质量状态（Phase Q 首版）

| 里程碑 | 状态 |
|---|---|
| Q.0 人设可配置 | ✅ |
| Q.1 语音可用（浏览器 STT · 本机 TTS · 可打断） | ✅ MQ-1 |
| Q.2 Skills 契约与触发 | ✅ MQ-2 |
| Q.3 记忆真有用（session=`default` · human 事实） | ✅ MQ-3 |
| Q.4 Loop 真主动（服务端 LLM · 持久化 idle） | ✅ MQ-4 |
| Q.5 横切（文档 + 最小 evals） | ✅ |
| **下一主线** | **Phase 5.1 多端 & channel** |

MCP / LiveKit：**暂缓 / 未实现**。详见 DEVELOPMENT_PLAN。

## 能力一览

| 能力 | 状态 |
|---|---|
| 浏览器语音（Web Speech + `/ws/chat` + 本机 TTS） | ✅ **默认** |
| Daily + Pipecat 全双工 | ✅ 可选（需 `DAILY_API_KEY`） |
| 本机 TTS（Qwen3-TTS / CosyVoice / stub） | ✅ `VLLM_TTS_URL` |
| 长期记忆（Letta remote / embedded） | ✅ |
| Skills（Markdown · 自动触发 · `/skills`） | ✅ |
| 主动 Loop + `/schedules` + 通知 | ✅ |
| Docker Compose / CI | ✅ |

## 快速开始

```bash
git clone https://github.com/huangyuan3h/Fae-v2.git
cd Fae-v2
cp .env.example .env
# 推荐：.env → LETTA_MODE=embedded
# 主动 Loop：DASHSCOPE_API_KEY 或 PROACTIVE_LLM_API_KEY
# Daily（可选）：DAILY_API_KEY

npm run setup        # root npm + backend (uv) + ui (pnpm)
npm run dev          # backend :8000 + UI :3000（+ TTS :8880）
open http://localhost:3000
```

### 演示

1. **Settings → 模型**：添加 OpenAI / Ollama 并设为当前使用（Key 在浏览器 localStorage）  
2. **Settings → 人设**：改语气 → 下一轮对话生效  
3. 首次本机 TTS：`npm run setup:tts`；之后 `npm run dev` 会起 `:8880`  
4. **默认路径**：说话或打字 → 流式回复 + **本机 TTS**（不依赖 Daily）  
5. **记忆**：说「我叫小明，住上海，忌香菜」→ 刷新后仍能答对  
6. **Skills**：贴 Traceback → 首页显示分数；或 `/skills` 三场景 preset  
7. **日程**：`/schedules` → 解析 → 确认创建 → 到点进 Settings → 通知收件箱  
8. **主动 Loop**：服务端配置 `DASHSCOPE_API_KEY` / `PROACTIVE_LLM_*`，可调短 `OUTREACH_IDLE_HOURS`  
9. **Daily（可选）**：Settings → 语音 → 高级 → 勾选 Daily  

### 环境变量（常用）

| 变量 | 用途 |
|---|---|
| `VLLM_TTS_URL` | 本机 TTS（默认 `:8880`） |
| `DASHSCOPE_API_KEY` | LLM / 主动 Loop 回退 Key |
| `PROACTIVE_LLM_*` | 主动 Loop 专用服务端模型 |
| `LETTA_MODE` | `embedded` / `remote` / `off` |
| `SCHEDULER_ENABLED` | 主动调度（默认示例见 `.env.example`） |
| `DAILY_API_KEY` | 可选 Daily 全双工 |

## 测试

```bash
cd backend && uv run pytest          # 含 evals runners：tests/test_evals_*.py
cd ui && pnpm lint && pnpm build
```

评测 case 数据在 [`evals/`](./evals/)；由 backend pytest 加载，不依赖 Daily / 真云端 TTS。

## 许可证

Apache 2.0
