# FAE-v2 开发计划 Checklist

> 本文档是 `ARCHITECTURE.md` 的**执行映射**，把架构设计拆解为可勾选的任务清单。
> 维护原则：阶段边界 = 一次可演示的成果（Demo-Ready），不要跨阶段合并。

---

## 0. 当前重心：先跑起来

> 整个项目的大路线图依然按 `ARCHITECTURE.md` 的 5 个 Phase 推进（W1–W9+）。
> **但本轮迭代只关注 Phase 0 · 最小可跑通**——把"配置 API Key → 说话 → 出文字 + 出语音"这条最短链路打通。
> Phase 1+ 的内容保留在文档底部作为长期参考，**当前不要动**。

### Phase 0 · Demo-Ready 目标

**当下面向用户的一句话定义**：

> 打开 `http://localhost:3000`，在设置页填入一个能跑 Qwen3 的 API Key 和 URL，按住麦克风说话，松开后能同时看到文字回复和听到语音。

**验收标准**（满足才算 Phase 0 完成）：
- [ ] 启动命令 ≤ 1 条（`./start.sh` 或 `docker compose up`）
- [ ] 首次访问自动跳转到设置页，填入 Key + URL 后能保存
- [ ] 进入对话页后，按住说话 → 松开后 ≤ 2.5s 看到文字 + 听到语音
- [ ] 至少能稳定跑通 5 轮对话不掉线
- [ ] 端到端延迟 P50 < 2.5s（ASR + LLM + TTS）

---

## Phase 0 · 最小可跑通（当前 Sprint）

> 砍掉一切非必需：不要记忆、不要工具、不要 Skills、不要主动 Loop、不要多用户。
> 只留 4 件事：**设置 Key** + **采集麦克风** + **流式 ASR/LLM/TTS** + **显示 + 播放**。

### 0.1 仓库骨架 & 启动脚本

- [ ] 目录结构：`backend/`（Python · FastAPI）+ `ui/`（Next.js 15）
- [ ] `backend/pyproject.toml`：依赖 `fastapi` / `uvicorn` / `pipecat-ai` / `dashscope` / `pydantic-settings` / `python-dotenv`
- [ ] `ui/package.json`：依赖 `next@15` / `react@19` / `tailwindcss@4` / `zustand` / `framer-motion` / `zod`
- [ ] 根目录 `start.sh`：一行 `docker compose up` 或并行 `pnpm dev` + `uv run uvicorn`
- [ ] 根目录 `.env.example`：留空，让用户在 UI 里填，**不要**让用户改文件

> **设计取舍**：本阶段**不引入 Docker**，先 `start.sh` 并行起两个进程，足够 demo。Docker 化放到 Phase 1 末尾或 Phase 2。

### 0.2 设置页：填 API Key 和 URL

- [ ] 路由 `ui/src/app/settings/page.tsx`
- [ ] 表单字段：
  - [ ] **Provider**（下拉）：`dashscope`（默认）/ `openai-compatible`（自部署 vLLM 等）
  - [ ] **Base URL**（文本框，默认 `https://dashscope.aliyuncs.com/compatible-mode`）
  - [ ] **API Key**（密码框，mask 显示）
  - [ ] **Model**（文本框，默认 `qwen3-max`）
  - [ ] **TTS Voice**（下拉，默认 `Cherry` / `Ethan`）
- [ ] "测试连接"按钮：调一个最小 LLM 请求（`/api/test-connection`），通过才允许保存
- [ ] 保存到 `localStorage`（key: `fae.config`），用 `zod` 校验 schema
- [ ] 没填过的用户首次访问自动重定向到 `/settings`

> **后端配合**：
- [ ] `POST /api/test-connection`：接收 `{baseUrl, apiKey, model}`，发起一次最小 LLM 调用验证
- [ ] **不**在服务器持久化 Key——服务器只是一个"代理 + 验证"角色，真正的 Key 存在浏览器
- [ ] 服务器从 `Authorization` header 读取 Key（每次请求带）

### 0.3 后端：Pipecat Pipeline（最小版）

- [ ] `backend/src/fae/api.py`：FastAPI + WebSocket 端点 `/ws/voice`
- [ ] WebSocket 协议（自定义，简单优先）：
  - 客户端 → 服务端：`{type: "config", baseUrl, apiKey, model, ttsVoice}`、`{type: "audio", pcm: base64}`、`{type: "stop"}`
  - 服务端 → 客户端：`{type: "asr_partial", text}`、`{type: "asr_final", text}`、`{type: "llm_token", text}`、`{type: "tts_audio", pcm: base64}`、`{type: "done"}`
- [ ] `backend/src/fae/pipecat/bot.py`：组装 pipeline
  - 音频入 → Silero VAD → Qwen3-ASR (DashScope) → Context Aggregator → Qwen3-Max (OpenAI 兼容) → Sentence Aggregator → Qwen3-TTS (DashScope Realtime) → 音频出
- [ ] `backend/src/fae/pipecat/services/qwen3_asr.py`：流式调用 DashScope 语音识别
- [ ] `backend/src/fae/pipecat/services/qwen3_tts.py`：流式调用 DashScope Realtime TTS
- [ ] `backend/src/fae/pipecat/services/qwen3_llm.py`：OpenAI 兼容客户端，Base URL/Key 来自每条 WebSocket 连接
- [ ] 打断（Barge-in）简化版：客户端发 `stop` 服务端立刻停 TTS 流

> **技术决策**：
- **不**用 Daily / LiveKit（避免第三方账号），直接 WebSocket + PCM/Opus
- **不**起 vLLM-Omni（避免先装模型权重），全部走 DashScope API
- **不**用 Letta（Phase 2 才上）
- VAD 用 Silero（轻量本地）

### 0.4 前端：对话页

- [ ] 路由 `ui/src/app/page.tsx`（主对话页）
- [ ] 组件 `VoiceOrb.tsx`（Framer Motion 动效：呼吸/旋转/脉冲 3 状态）
- [ ] 组件 `MicButton.tsx`：长按说话（pointerdown 开始采集，pointerup 发送）
- [ ] 组件 `ChatPanel.tsx`：流式追加 LLM token + 完整气泡
- [ ] 组件 `MessageBubble.tsx`：用户/助手气泡区分
- [ ] Hook `useVoiceSession.ts`：
  - [ ] 申请 `getUserMedia({audio: true})`
  - [ ] 用 `AudioContext` 采集 PCM（16kHz / mono）
  - [ ] 通过 WebSocket 发送音频帧
  - [ ] 接收 TTS 音频用 `AudioContext.decodeAudioData` 排队播放
- [ ] Hook `useConfig.ts`：封装 localStorage 的读写
- [ ] 顶部条显示当前 Provider + Model，右上角"⚙️"跳转设置

### 0.5 错误处理 & 体验

- [ ] 麦克风权限被拒 → 显示"请在浏览器设置中允许麦克风" + 文字输入 fallback
- [ ] API Key 无效 → 设置页显示具体错误（"401 Unauthorized"）
- [ ] 网络断连 → 对话页显示"连接已断开，正在重连..."
- [ ] TTS 失败 → 不阻塞，只显示文字回复
- [ ] ASR 失败 → 重试一次，仍失败则提示用户重新说话

> **冒烟测试**（Phase 0 收尾）：
1. 全新克隆仓库 → `./start.sh` → 浏览器打开 → 自动跳设置页
2. 填入 DashScope Key → 测试连接通过 → 进入对话页
3. 按住麦克风说"你好，请用一句话介绍你自己"
4. ≤ 2.5s 看到文字回复 + 听到语音
5. 连续 5 轮对话无掉线

---

## Phase 1+ · 长期路线图（参考，暂不动）

> 下面的 Phase 1–5 来自 `ARCHITECTURE.md` 的 Roadmap。
> 等 Phase 0 跑通并经你确认 demo OK 后，再决定从哪一项切入。
> 每项都标了**前置依赖**，按顺序展开。

### Phase 1 · MVP（W1–W2，原计划）
**前置**：Phase 0 跑通
- [ ] Docker Compose 一键起所有服务
- [ ] 接 Daily / LiveKit 替代自建 WebSocket（更稳的 NAT 穿透）
- [ ] 接入 vLLM-Omni 本地 ASR（可选，给有 GPU 的用户）
- [ ] 完整 UI：VoiceOrb + ChatPanel + MicButton 完工

### Phase 2 · 记忆深化（W3–W4）
**前置**：Phase 1
- [ ] Letta server 接入 + SQLite 持久化
- [ ] 三层记忆（core/recall/archival）+ Qdrant
- [ ] Episodic Memory 扩展
- [ ] sleeptime 整理任务
- [ ] 记忆浏览器 UI

### Phase 3 · Skills 体系（W5–W6）
**前置**：Phase 2
- [ ] Markdown skill 格式规范 + 加载器
- [ ] 5+ 内置 skill（daily_check_in / tech_debug / travel / reading / writing）
- [ ] Skill 自动触发 + 优先级调度
- [ ] Skill 编辑器 UI

### Phase 4 · 主动 Loop（W7–W8）
**前置**：Phase 3
- [ ] APScheduler + Heartbeat
- [ ] 定时任务 UI
- [ ] Proactive outreach
- [ ] 通知通道（Web Push / 桌面通知）

### Phase 5 · 上限扩展（W9+）
**前置**：Phase 4
- [ ] MCP 集成
- [ ] Subagents
- [ ] 多用户 / 多角色
- [ ] 移动端 PWA
- [ ] 第三方 channel（Slack / Telegram）

---

## 跨阶段横切关注（Continuous）

> 不挂在某个阶段下，每个 PR 都要 review。

### 安全 / 隐私
- [ ] API Key 只存浏览器 localStorage，**后端不持久化**
- [ ] 服务器只是个代理 + 验证，看到的 Key 不写日志
- [ ] "一键清除"按钮：清 localStorage + 清服务器临时缓存

### 可观测性
- [ ] 每个 WebSocket 连接打 log：连接 ID、Provider、延迟分阶段
- [ ] 浏览器开发者面板能看到每个阶段的耗时

### 文档
- [ ] README 写"30 秒跑起来"步骤
- [ ] 录 30s 演示视频
- [ ] `docs/api/api-reference.md`：WebSocket 协议

---

## 关键里程碑（Milestones）

| ID | 时间 | 验收标准 |
|---|---|---|
| **M0** | **当前 Sprint** | **Phase 0 全部勾完，能 demo 5 轮对话** |
| M1-1 | Phase 1 末 | Docker 一键起 |
| M1-2 | Phase 1 末 | 端到端对话 ≥ 3 轮，录 30s 视频 |
| M2-1 | Phase 2 末 | 跨会话记忆冒烟通过 |
| M3-1 | Phase 3 末 | 5+ 内置 skill 自动触发 |
| M4-1 | Phase 4 末 | 24h 主动 loop 演示 |
| M5+ | Phase 5+ | 按需取用 MCP / Subagent / 多端 |

---

## 风险登记（Risk Register）

| 风险 | 概率 | 影响 | 缓解 |
|---|---|---|---|
| DashScope API 速率限制 | 中 | 中 | 加指数退避 + 用户提示 |
| WebSocket 跨代理断连 | 中 | 中 | 心跳 ping/pong + 断线重连 |
| 端到端延迟突破 2.5s | 中 | 高 | 先用云端 LLM 跑通；后续再优化本地推理 |
| 浏览器麦克风权限被用户拒 | 中 | 低 | 文字输入 fallback |
| DashScope TTS Realtime 流式不稳定 | 中 | 中 | 加 chunk buffer；失败时退到一次性合成 |

---

## 完成度跟踪

- [ ] **Phase 0 完成（M0 通过）** ← 当前目标
- [ ] Phase 1 完成
- [ ] Phase 2 完成
- [ ] Phase 3 完成
- [ ] Phase 4 完成
- [ ] Phase 5 持续推进

---

**最后更新**：2026-07-12
**关联文档**：[`ARCHITECTURE.md`](./ARCHITECTURE.md)
**反馈**：GitHub Issues / PR
