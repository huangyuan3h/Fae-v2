# FAE-v2 开发计划 Checklist

> 本文档是 `ARCHITECTURE.md` 的**执行映射**，把架构设计拆解为可勾选的任务清单。
> 用法：完成一项就打 `[x]`，每条任务都标明所属阶段、依赖、产出物、验收标准。
> 维护原则：阶段边界 = 一次可演示的成果（Demo-Ready），不要跨阶段合并。

---

## 0. 总览（按当前状态重排）

| 阶段 | 名称 | 状态 | 阶段成果（Demo-Ready 标准） |
|---|---|---|---|
| Phase 1 | MVP | ✅ 完成 | 浏览器语音对话 + Docker 一键起 |
| Phase 2 | 记忆深化 | ✅ 完成 | 三层记忆 + 记忆浏览器 UI |
| Phase 2.6 | Qwen3-TTS 默认播报 | ✅ 首版 | 浏览器 STT + `/ws/chat` + Qwen3-TTS（无 Daily） |
| Phase 3 | Skills 体系 | ✅ 完成（有已知残留） | Markdown skill 自动触发 + 6 内置 + `/skills` |
| Phase 4 | 主动 Loop | 🔜 脚手架就绪 | 心跳 + 定时任务 + 主动问候 |
| Phase 5 | 上限扩展 | 待开始 | MCP / Subagent / 多端 / 第三方 channel |

### 0.1 现状快照（2026-07-19）

**已落地**

- 根目录 `npm run dev`：backend `:8000` + UI（`:3000` / `:3001`）
- Settings → 模型：OpenAI / Ollama 配置 CRUD、测试连接、当前选用（localStorage）
- Settings → 语音：Daily 开关（**可选**；未配 Key 会回退 browser）
- 默认对话路径：浏览器 Web Speech STT + `/ws/chat` + **浏览器 `speechSynthesis` TTS**
- 记忆：embedded / remote Letta、Recall、Archival、Episodic、sleeptime、`/memory` UI
- 回复清洗：剥离 `<think>`；TTS 前去 Markdown；聊天区 Markdown 渲染
- CORS：含 `3000` / `3001`

**已知缺口（驱动 Phase 2.6）**

- 默认 TTS 是系统朗读，不自然；且曾误以为勾选 Daily = 本地 TTS
- Daily 仅为可选 WebRTC；TTS **始终**走本机 `VLLM_TTS_URL`（无云端 TTS）

### 0.2 语音策略修订（相对旧计划）

| 项 | 旧计划 | **现行计划** |
|---|---|---|
| 默认 TTS | 浏览器 `speechSynthesis`；可选 Daily + DashScope | **本地 TTS 服务（OpenAI-compatible HTTP）** |
| Daily | 增强主路径之一 | **可选 / 降级**：仅在需要 WebRTC 全双工时启用 |
| 云端 TTS | Pipecat Daily 默认 DashScope | **已移除**；只保留本机权重 / stub |
| STT（近期） | 浏览器 Web Speech 可接受 | **先保持浏览器 STT**；本地 ASR（vLLM-Omni）并行可选 |
| 传输 | Daily WebRTC 或浏览器 | **默认：HTTP/WS 文本 + 本地 TTS 音频回放**（无 Daily Key） |

**本地 TTS 接口约定（可换引擎）**

```text
POST {VLLM_TTS_URL}/v1/audio/speech
Body: { "model": "...", "input": "...", "voice": "..." }
→ audio/mpeg | audio/wav | audio/pcm
```

- 开发无 GPU：compose / 本地 **TTS stub**（固定短音或静音 + 正确 Content-Type）
- 有 GPU / 本机模型：同一 URL 换成 Qwen3-TTS / CosyVoice / 其它兼容服务
- UI：播 `Audio` / `AudioContext`，**不再默认走 `speechSynthesis`**（失败时可降级）

---

## Phase 1 · MVP — ✅ 完成

> 历史记录保留；细节见 git 历史。摘要：脚手架、FastAPI、Pipecat（含 Daily 可选）、Next UI、Docker。

- [x] 基础设施 / FastAPI / Pipecat 最小管线 / 最小 UI / 部署闭环
- [x] 浏览器路径：Web Speech STT/TTS + `/ws/chat`
- [x] Daily 可选路径（WebRTC）— TTS 已统一为本机服务

---

## Phase 2 · 记忆深化 — ✅ 完成

- [x] 2.1 Letta（remote / embedded）
- [x] 2.2 Pipecat / WS 记忆注入与持久化
- [x] 2.3 Recall + Archival + Episodic
- [x] 2.4 sleeptime consolidation
- [x] 2.5 记忆浏览器 UI

> 附带已完成（原计划外，已合入主线）：根目录 `npm run dev`、Settings 模型管理、think/markdown 清洗。

---

## Phase 2.6 · 本地语音栈（下一优先）

> 目标：开发者 **零 Daily Key** 即可听到自然、本地合成的中文语音。  
> 默认路径：`Mic/文字 →（浏览器 STT 可选）→ /ws/chat → 本地 TTS → 浏览器播放`。

### 2.6.1 后端：本机 TTS（无 Daily）— ✅

- [x] 配置：`VLLM_TTS_URL` + `TTS_MODEL` / `TTS_VOICE` / `TTS_LANGUAGE` / `TTS_SAMPLE_RATE`
- [x] `POST /api/tts/speak`：strip think/markdown → 本机 TTS → `audio/wav`
- [x] `GET /api/tts/status`
- [x] 单测：`test_tts_api.py`（不可达 503、WAV 头、speakable）
- [x] **已移除** DashScope / 云端 TTS 路径（避免误选）

> **验收**：`npm run dev`（含 TTS stub）后  
> `curl -X POST localhost:8000/api/tts/speak -H 'Content-Type: application/json' -d '{"text":"你好"}' --output /tmp/a.wav`

### 2.6.2 UI：默认播 Qwen3-TTS — ✅ 首版

- [x] `ui/src/lib/qwen-tts.ts`：请求 `/api/tts/speak` + `Audio` 播放 / 打断
- [x] `useVoiceSession`：优先 Qwen3-TTS，失败降级浏览器朗读
- [x] Settings → 语音：Qwen3-TTS 状态；Daily 收进高级
- [x] 首页状态：`Qwen3-TTS` / `浏览器朗读` / `Daily`

> **冒烟测试**（M2.6-1）：不设 `DAILY_API_KEY`，文字聊 3 轮听到 Qwen 音色；打断立即停。

### 2.6.3 本机 TTS（权重自推理）— ✅ 适配层

- [x] `VLLM_TTS_URL` OpenAI-compatible 客户端（唯一 TTS 后端）
- [x] TTS stub **内嵌** backend（`TTS_EMBED_STUB=true`）；`npm run dev` = backend+UI
- [x] 云端 TTS 已删除；真模型：`TTS_EMBED_STUB=false` + 外部 URL（`doc/LOCAL_TTS.md`）
- [ ] 流式首包优化
- [ ] 同步 `ARCHITECTURE.md` 默认路径说明
- [ ] 仓库内一键拉起真实 Qwen3-TTS 权重（GPU Dockerfile，后续）

---

## Phase 3 · Skills 体系 — ✅ 完成

> Skill = Markdown 剧本，按需加载。6 个内置 skill + `/skills` 编辑器。

### 3.1 Skill 格式 & 加载器

- [x] `SkillMetadata` / `Skill`（`fae.agent.skills_schema`）
- [x] `SkillsLoader`：YAML frontmatter + `backend/src/skills/*.md` + mtime 缓存
- [x] 加载策略：`always_on` / `trigger_based` / `manual` / `lazy`
- [x] 触发匹配：关键词 + token Jaccard（无重型 embedding）

### 3.2 内置 Skills（6 个）

- [x] `daily_check_in.md` / `technical_debugging.md` / `travel_planning.md`
- [x] `reading_companion.md` / `writing_assistant.md` / `proactive_outreach.md`（lazy）

### 3.3 自动触发 + 优先级

- [x] `SkillRuntime`：priority + cooldown（按 session）
- [x] 注入 `<active_skills>`（记忆 system 之后）
- [x] LAZY：`request_skill` 一轮 tool（`fae.agent.llm_turn`）
- [x] WS 事件 `{"type":"skills","active":[...]}`；接 `/api/chat` + Daily seed

> **冒烟**（M3-1）：贴 Traceback → 首页「已加载：technical_debugging」或 `POST /api/skills/test-trigger`。

### 3.4 Skill 编辑器 UI

- [x] `/skills`：列表、启停、Monaco 编辑、测试触发
- [x] REST：`GET/PUT/PATCH /api/skills` + `POST /api/skills/test-trigger`

> **Phase 3 收尾验收**：stack trace / 旅行 / 写作 三场景可演示。

### 3.5 Phase 3 审计残留（不阻塞 Phase 4）

| 项 | 状态 | 说明 |
|---|---|---|
| Schema / Loader / Matcher / 6 skills / `/skills` UI / REST | ✅ | `test_skills.py` 覆盖主路径 |
| WS + `/api/chat` skills 注入 | ✅ | lazy 后会重发 `skills` 事件 |
| `SkillRuntime.activate()` | ✅ | Phase 4 cron / proactive 强制注入 |
| Daily 路径按轮 match | ⚠ 弱 | seed 用空文本；全双工路径后续对齐 |
| `max_context_tokens` / `requires_tools` / approval UI | ⚠ 未接 | metadata 预留，非 Phase 4 阻塞 |
| `proactive_outreach` 剧本 | ✅ | 调度强制加载用 `activate()`，勿赌 LLM `request_skill` |

---

## Phase 4 · 主动 Loop

> 目标：心跳、定时任务、主动问候、桌面通知。  
> 主动触达默认 **通知 + 文字**；若用户在线且本地 TTS 可用，可再播一句短语音（不依赖 Daily）。

### 4.0 开工前置（脚手架）— ✅ 2026-07-19

- [x] `fae/scheduler/`：`activity` / `heartbeat` / `proactive` / `jobs`（规则 + builtin specs）
- [x] 边界约定：`SleeptimeScheduler`（记忆整理）≠ `fae.scheduler`（主动 Loop）
- [x] `ActivityTracker` 接入 lifespan `on_persist`（与 sleeptime.touch 并列）
- [x] `SkillRuntime.activate` / `prepare_activated_request` 供 cron 强制加载 skill
- [x] `apscheduler` 写入 `pyproject.toml`；`SCHEDULER_ENABLED=false` 默认
- [x] `.env.example`：heartbeat / outreach / VAPID 占位
- [x] UI：`AppNav`（含「日程」占位）+ Settings「通知」tab 槽位
- [x] `api/memory.py` 从 `api/__init__.py` 抽出（为 `api/schedules.py` 腾位置）
- [ ] `api/schedules.py` + APScheduler 真正 start/stop（4.1）
- [ ] `/schedules` 页面（4.3）

### 4.1 APScheduler + Heartbeat

- [x] 脚手架 `backend/src/fae/scheduler/heartbeat.py`（`HeartbeatLoop.evaluate/tick`）
- [x] 脚手架 `backend/src/fae/scheduler/jobs.py`：builtin job specs
- [x] 脚手架 `backend/src/fae/scheduler/proactive.py`：`should_outreach` 规则
  - [x] 规则常量：6h idle / 12h cooldown / max 1/day
  - [ ] 接 lifespan：`SCHEDULER_ENABLED` 时启动 `AsyncIOScheduler`
  - [ ] "待办到期"检测：扫 Episodic Memory
- [ ] 与 LLM 的桥接：心跳默认走「桌面通知 + 文字」；可选本地 TTS 短播报
- [ ] 主动触达调用 `skills.activate(["proactive_outreach"], …)` + 投递通知

### 4.2 内置 cron 任务

- [ ] `daily_checkin`：每天 08:00，检索昨日记忆 → 加载 `daily_check_in` skill
- [ ] `weekly_recap`：每周日 20:00，生成周报 + 整理记忆
- [ ] 自定义 cron 工具：`schedule_create_job` / `list_jobs` / `cancel_job`

### 4.3 定时任务 UI

- [ ] 路由 `src/app/schedules/page.tsx`
- [ ] 列表：所有 job（内置 + 用户自定义）、下次执行时间、状态
- [ ] 创建表单：自然语言输入（"明天下午 3 点提醒我开会"）→ 解析为 cron
- [ ] 编辑 / 删除 / 暂停 / 立即触发

> **冒烟测试**（M4-1）：创建"明早 8 点提醒吃维生素" → 准点收到桌面通知 + 浏览器弹窗。

### 4.4 通知通道

- [ ] Web Push（VAPID）：用户首次访问时订阅
- [ ] 浏览器 Notification API：心跳事件触达
- [ ] 可选：macOS `terminal-notifier` / Linux `notify-send`
- [ ] 设置页通知开关 + 勿扰时段（可挂在现有 `/settings`）

> **Phase 4 收尾验收**：演示 24h 无人值守，FAE 主动发起 1 次合理问候。

---

## Phase 5 · 上限扩展

> 进入"无上限"阶段，按需取用，不强排期。

### 5.1 MCP 集成

- [ ] 实现 MCP client：stdio + SSE 两种 transport
- [ ] 工具注册表自动合并 MCP server 暴露的 tools
- [ ] 权限分级复用现有 4 级
- [ ] 内置连接示例：filesystem / github / postgres

### 5.2 Subagents

- [ ] 设计 subagent 接口：`run_subagent(name, task, context)`
- [ ] 内置 3 个：researcher / coder / reviewer
- [ ] 主 agent 可委派任务，结果回灌

### 5.3 多端 & 第三方 channel

- [ ] PWA 化（manifest.json + service worker，离线可用）
- [ ] 移动端响应式适配
- [ ] Slack / Telegram bot 适配器

### 5.4 多用户 / 多角色

- [ ] Letta agent 池化（每用户独立 agent_id）
- [ ] NextAuth.js 接入（OAuth + Email magic link）
- [ ] 数据隔离：每用户独立存储

### 5.5 本地 ASR（可选增强）

- [ ] 浏览器 STT → 可选切换本地 Qwen3-ASR（`VLLM_ASR_URL`，接口已部分存在）
- [ ] Settings 增加 STT 来源：browser / local

### 5.6 Daily / LiveKit（可选增强）

- [ ] 仅当需要低延迟全双工 WebRTC 时启用
- [x] Daily bot TTS 已接同一套本机 `LocalTTSService`

---

## 跨阶段横切关注（Continuous）

### 安全 / 隐私

- [ ] 工具权限分级（Safe / Caution / Sensitive / Dangerous）
- [ ] UI 确认弹窗：Sensitive / Dangerous 执行前
- [ ] 「一键遗忘」：清空记忆 + 重置 agent
- [ ] 数据导出 JSONL（Settings）
- [x] LLM API Key 仅存浏览器；服务端不落盘 UI Key
- [ ] 本地 TTS / ASR：**音频默认不离开本机**（文档写清）

### 可观测性

- [ ] 结构化日志：tool call / TTS 后端选择
- [ ] 「现在在做什么」面板
- [ ] Token / TTS 延迟统计

### 性能

- [ ] 端到端延迟埋点：STT / LLM / **本地 TTS**
- [ ] P50 / P95 仪表盘
- [ ] TTS 自然度主观评测（对比 browser vs local）

### 评测（Evals）

- [ ] `evals/tts/`：本地 stub + 真模型样本
- [ ] `evals/agent/`：memory-recall / multi-turn
- [ ] `evals/e2e/`：本地语音回合（无 Daily）

### 文档

- [ ] 同步 `ARCHITECTURE.md` 语音默认路径为本地 TTS
- [ ] `docs/design/local-tts.md`：接口、换引擎、VRAM 建议
- [x] README Quick Start：`npm run setup` + `npm run dev`
- [ ] README：本地 TTS 与（可选）Daily 的区别说明

---

## 关键里程碑（修订）

| ID | 验收标准 | 状态 |
|---|---|---|
| M0 | 仓库脚手架 + Compose 可起 | ✅ |
| M1-1 / M1-2 | 浏览器对话 ≥ 3 轮 | ✅ |
| M2-1 / M2-2 | 跨会话记忆 + `/memory` | ✅ |
| **M2.6-1** | **无 Daily Key，本地 TTS stub 播报 3 轮** | 🔜 |
| **M2.6-2** | **真本地模型 TTS，主观明显好于系统朗读** | 🔜 |
| M3-1 / M3-2 | skill 触发 + 编辑器 | ✅ |
| M4-1 / M4-2 | 定时任务 + 主动 loop | 待 |
| M5+ | MCP / Subagent / 本地 ASR / 可选 WebRTC | 按需 |

---

## 风险登记（修订）

| 风险 | 概率 | 影响 | 缓解 |
|---|---|---|---|
| 本地 TTS VRAM / 机型不够 | 中 | 高 | stub 保开发；文档写清最低配置；可换小模型 |
| 本地 TTS 首包慢于云端 | 高 | 中 | 句子级合成 + 可接受延迟；流式后续 |
| 误把 Daily 当本地 TTS | — | — | **产品文案 + Settings 状态已规划改正（2.6.3/2.6.5）** |
| Daily 授权或网络（可选） | 低 | 低 | 默认不依赖 Daily |
| Letta API 变动 | 中 | 中 | embedded 模式 + client 抽象 |
| 主动 loop 误触 | 中 | 中 | cooldown + 勿扰 |

---

## 完成度跟踪

- [x] Phase 1 完成
- [x] Phase 2 完成
- [x] Phase 2.6 首版（本地 TTS `/api/tts/speak`；真·本机模型后续）
- [x] Phase 3 完成（M3-1 / M3-2；见 3.5 残留）
- [ ] **Phase 4 完成** ← **下一主线**（4.0 脚手架已就绪）
- [ ] Phase 5 持续推进

---

## 近期执行顺序（建议）

1. **Phase 4.1**：`AsyncIOScheduler` 接入 lifespan + `HeartbeatLoop` 真跑
2. **Phase 4.2–4.3**：builtin cron + `/schedules` UI + `api/schedules.py`
3. **Phase 4.4**：Web Push / Notification + Settings 通知面板
4. Phase 2.6.3+：流式首包；补齐 `ARCHITECTURE` 语音默认路径细节

### Phase 4 建议落地顺序（实现时）

```text
1. api/schedules.py (CRUD stub) + include_router
2. lifespan: if settings.scheduler_enabled → AsyncIOScheduler + HeartbeatLoop
3. outreach handler: activate(proactive_outreach) → notify channel
4. ui/app/schedules + schedules-api.ts
5. Web Push subscribe + NotificationsPanel
```

---

**最后更新**：2026-07-19（Phase 3 审计 + Phase 4 脚手架）  
**关联文档**：[`ARCHITECTURE.md`](./ARCHITECTURE.md) · [`LOCAL_TTS.md`](./LOCAL_TTS.md)  
**反馈**：GitHub Issues / PR
