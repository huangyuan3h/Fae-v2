# FAE-v2

> **F**ully **A**utonomous **E**cho · v2 · **stable 0.6.0**  
> 有长期记忆、以轻量主对话协调可恢复后台工作的个人 AI 助手。
> 变更摘要见 [CHANGELOG.md](./CHANGELOG.md)。

## 文档

- [doc/TODO.md](./doc/TODO.md) — **唯一未完成功能清单（当前焦点）**
- [doc/architect/ARCHITECTURE.md](./doc/architect/ARCHITECTURE.md) — 架构文档
- [doc/architect/MODULES.md](./doc/architect/MODULES.md) — 模块索引
- [doc/design/CONTEXT_ENGINEERING.md](./doc/design/CONTEXT_ENGINEERING.md) — Context Engineering 设计与现状
- [doc/operations/DEPLOY.md](./doc/operations/DEPLOY.md) — **常驻 Core 部署**（compose slim / Tailscale / `/ready`）
- [doc/operations/LOCAL_TTS.md](./doc/operations/LOCAL_TTS.md) — 本机 TTS
- [doc/archive/](./doc/archive/) — 已完成计划与历史研究
- [sdk/typescript](./sdk/typescript) — 薄 Client SDK（`@fae/client`）
- [evals/README.md](./evals/README.md) — 最小评测集
- [CHANGELOG.md](./CHANGELOG.md) — 版本摘要

## 质量状态（stable 0.6.0）

| 里程碑 | 状态 |
|---|---|
| Phase 1～4 骨架 + Phase Q 质量 | ✅ |
| 5.1 多端 & Telegram | ✅ M5-1 |
| 5.2 Subagents | ✅ M5-2 |
| P6 Core 常驻 & 快速部署 | ✅ M6 |
| P7 Client 契约 & 壳化 | ✅ M7 |
| **下一主线** | **前台 / 后台 Token 归因 → 持久后台工作平面 → 个人助手 Golden Path** |

MCP / LiveKit / Slack：**暂缓 / 未实现**。详见 [`doc/TODO.md`](./doc/TODO.md)。

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

**常驻 Agent Core（推荐生产 / Telegram）** — 见 [doc/operations/DEPLOY.md](./doc/operations/DEPLOY.md)：

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

### 前端运行时基线

UI 已升级到 Next.js 16，开发、CI 和 Docker 构建统一使用以下版本边界：

- Node.js `24.4.1` 以上且小于 `25`
- pnpm `10.28.2`
- Next.js `16.2.11` + React `19.2.8`
- TypeScript `5.9.3` + ESLint `9.39.5`

在 `ui/` 目录执行 `pnpm install --frozen-lockfile` 可复现依赖安装。`@fae/client` 是 source-only SDK，生产构建会生成 standalone 产物。


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
cd ui && pnpm typecheck && pnpm lint && pnpm build
```

评测 case 数据在 [`evals/`](./evals/)；由 backend pytest 加载，不依赖 Daily / 真云端 TTS。

## 许可证

Apache 2.0
