# FAE-v2

> **F**ully **A**utonomous **E**cho · v2 · **stable 0.4.0**  
> 有长期记忆、能主动 loop、可本地部署的语音 Agent。  
> 变更摘要见 [CHANGELOG.md](./CHANGELOG.md)。

## 文档

- [doc/ARCHITECTURE.md](./doc/ARCHITECTURE.md) — 架构真相源
- [doc/DEPLOY.md](./doc/DEPLOY.md) — **常驻 Core 部署**（compose slim / Tailscale / `/ready`）
- [doc/DEVELOPMENT_PLAN.md](./doc/DEVELOPMENT_PLAN.md) — **Personal Assistant 计划（P8 起下一主线）**
- [sdk/typescript](./sdk/typescript) — 薄 Client SDK（`@fae/client`）
- [doc/archive/DEVELOPMENT_PLAN_through_v0.2.md](./doc/archive/DEVELOPMENT_PLAN_through_v0.2.md) — 已完成至 v0.2.0 的旧清单归档
- [doc/LOCAL_TTS.md](./doc/LOCAL_TTS.md) — 本机 TTS
- [evals/README.md](./evals/README.md) — 最小评测集
- [CHANGELOG.md](./CHANGELOG.md) — 版本摘要

## 质量状态（stable 0.4.0）

| 里程碑 | 状态 |
|---|---|
| Phase 1～4 骨架 + Phase Q 质量 | ✅ |
| 5.1 多端 & Telegram | ✅ M5-1 |
| 5.2 Subagents | ✅ M5-2 |
| P6 Core 常驻 & 快速部署 | ✅ M6 |
| P7 Client 契约 & 壳化 | ✅ M7 |
| **下一主线** | **P8 · Tool Runtime & 连接器** |

MCP / LiveKit / Slack：**暂缓 / 未实现**。详见 DEVELOPMENT_PLAN。

## 能力一览

| 能力 | 状态 |
|---|---|
| 浏览器语音（Web Speech + `/ws/chat` + 本机 TTS） | ✅ **默认** |
| 手机 PWA 壳（manifest + 窄屏对话） | ✅ 首版 |
| Telegram channel（long polling · 共享 `default` 记忆） | ✅ 可选 |
| Subagents（工具委派 · 摘要回灌 archival） | ✅ 首版 |
| Daily + Pipecat 全双工 | ✅ 可选（需 `DAILY_API_KEY`） |
| 本机 TTS（Qwen3-TTS / CosyVoice / stub） | ✅ `VLLM_TTS_URL` |
| 长期记忆（Letta remote / embedded） | ✅ |
| Skills（Markdown · 自动触发 · `/skills`） | ✅ |
| 主动 Loop + `/schedules` + 通知 | ✅ |
| Docker Compose / CI | ✅ |

## 快速开始

**常驻 Agent Core（推荐生产 / Telegram）** — 见 [doc/DEPLOY.md](./doc/DEPLOY.md)：

```bash
cp .env.example .env   # 填 Always-on Core 块（含可选 FAE_CLIENT_TOKEN）
./deploy/scripts/start-core.sh
curl -s http://127.0.0.1:8000/ready | jq
curl -s http://127.0.0.1:8000/api/capabilities | jq
# 浏览器可不填 Key；对话用服务端 DASHSCOPE / PROACTIVE_LLM_*
```

**本机开发（UI + 热重载）**：

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
9. **手机**：Chrome/Safari「添加到主屏幕」；窄屏可打字对话；未读角标在 Settings  
10. **Telegram（可选）**：`.env` 设 `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID`（需服务端 LLM Key）→ 私聊回一句写入同一记忆；主动通知会推到该 chat  
11. **Daily（可选）**：Settings → 语音 → 高级 → 勾选 Daily  

### 环境变量（常用）

| 变量 | 用途 |
|---|---|
| `VLLM_TTS_URL` | 本机 TTS（默认 `:8880`） |
| `DASHSCOPE_API_KEY` | LLM / 主动 Loop / Telegram 回退 Key |
| `PROACTIVE_LLM_*` | 主动 Loop / Telegram 服务端模型 |
| `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` | 可选 Telegram long-polling channel |
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
