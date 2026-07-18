# FAE-v2 开发计划 Checklist

> 本文档是 `ARCHITECTURE.md` 的**执行映射**，把架构设计拆解为可勾选的任务清单。
> 用法：完成一项就打 `[x]`，每条任务都标明所属阶段、依赖、产出物、验收标准。
> 维护原则：阶段边界 = 一次可演示的成果（Demo-Ready），不要跨阶段合并。

---

## 0. 总览：5 个阶段 / 9 周

| 阶段 | 名称 | 周次 | 阶段成果（Demo-Ready 标准） |
|---|---|---|---|
| Phase 1 | MVP | W1–W2 | 浏览器对浏览器语音对话 + Docker 一键起 |
| Phase 2 | 记忆深化 | W3–W4 | 三层记忆 + 记忆浏览器 UI |
| Phase 3 | Skills 体系 | W5–W6 | Markdown skill 自动触发 + 5 个内置 skill |
| Phase 4 | 主动 Loop | W7–W8 | 心跳 + 定时任务 + 主动问候 |
| Phase 5 | 上限扩展 | W9+ | MCP / Subagent / 多端 / 第三方 channel |

---

## Phase 1 · MVP（W1–W2）

> 目标：把"麦克风 → 浏览器听到自己回放"这条最短链路打通，再让 Docker 一键起。

### 1.1 基础设施脚手架

- [x] 初始化仓库结构：`backend/` + `ui/` + `deploy/` + `docs/`（文档在 `doc/`）
- [x] 创建 `backend/pyproject.toml`（fastapi/uvicorn/openai/`pipecat-ai[daily,openai,sentence,silero]`/dashscope；`letta` 后续）
- [x] 创建 `ui/package.json`（Next.js 15 + `@daily-co/daily-js`）
- [x] 创建 `docker-compose.yml`：服务 = `backend` / `ui` / `letta` / `vllm-asr` / `qdrant` / `redis`（ASR/Letta/UI 现为 stub，便于无 GPU 起栈）
- [x] 写 `backend/src/fae/config.py`：基于 `pydantic-settings` 加载 `.env`
- [x] 写 `.env.example`：DashScope / Daily / Letta / vLLM / Qdrant / Redis
- [x] 写 `deploy/scripts/setup.sh` + `start.sh`

> **验收**：`./deploy/scripts/start.sh` 起来后，6 个容器全部 `healthy`。
> （ASR/Letta/UI 使用 stub 镜像；GPU 真模型与正式 Letta 后续替换。）

### 1.2 FastAPI 入口 + 健康检查

- [x] 实现 `backend/src/fae/api/`：暴露 `/health` `/ready` `/api/sessions` + voice/pipeline/chat/ws
- [x] 把 uvicorn 启动命令固化到 `deploy/docker/backend.Dockerfile`
- [x] 写最小 pytest：访问 `/health` 断言 200（全量 coverage ≥ 80%）
- [x] CI：`.github/workflows/ci.yml` 跑 `pytest` + UI lint/build

> **验收**：`curl http://localhost:8000/health` 返回 `{"status":"ok"}`。

### 1.3 Pipecat 最小 Pipeline

- [x] 实现 `backend/src/fae/pipecat/services/qwen3_asr.py`（HTTP，对接 compose ASR stub / 未来 vLLM）
- [x] 实现 `backend/src/fae/pipecat/services/qwen3_tts.py` + `dashscope_tts.py`（有 Key 真实合成，否则静音）
- [x] 实现 `backend/src/fae/pipecat/services/qwen3_llm.py`（复用 `fae.llm` OpenAI 兼容客户端）
- [x] 实现 `backend/src/fae/pipecat/transport.py`（LocalTransport）+ `daily_rooms.py` / `daily_bot.py`（Daily）
- [x] 实现 `backend/src/fae/pipecat/bot.py`：文本模式 `user text → LLM → SentenceAggregator → TTS`
- [x] 接入 VAD：`EnergyVAD` + `SileroVADAnalyzer`（`pipecat-ai[silero]`）
- [x] SmartTurn v3：Daily bot 使用默认 `UserTurnStrategies`（stop = LocalSmartTurnAnalyzerV3）
- [x] 实现打断（Barge-in）：`on_user_speech_during_playback()`；UI「打断」；`/api/voice/barge-in`
- [x] 实现 SentenceAggregator，把流式 token 攒句
- [x] Daily / Pipecat 全链路 bot：STT→LLM→DashScope TTS→Daily out

> **冒烟测试**（M1-1）：
> - 浏览器路径：Web Speech STT/TTS + `/ws/chat`（默认）
> - Daily 路径：UI 勾选「优先 Daily」+ 服务端 `DAILY_API_KEY` + `DASHSCOPE_API_KEY`
> **文本冒烟**：`POST /api/pipeline/text`。

### 1.4 最小 UI

- [x] `create-next-app@15` 初始化 `ui/`（App Router + Tailwind 4）
- [x] 视觉体系：自定义 token + Syne/DM Sans（未锁 shadcn，避免模板感）
- [x] 实现 `src/components/voice/VoiceOrb.tsx`：idle / listening / thinking / speaking 动效
- [x] 实现 `src/components/voice/MicButton.tsx`：申请麦克风 / 启动 Web Speech / Daily 通话
- [x] 语音客户端：浏览器 Web Speech + `@daily-co/daily-js` Daily 路径
- [x] 实现 `src/lib/pipecat-client.ts` + `useVoiceSession.ts` + `daily-session.ts`
- [x] 主对话页 `src/app/page.tsx`：VoiceOrb + 文本回退输入框 + Agent 设置

> **冒烟测试**（M1-2）：浏览器完整对话 ≥ 3 轮（语音或文字回退均可）。

### 1.5 部署闭环

- [x] `ui.Dockerfile` 多阶段构建（pnpm install → build → standalone output）
- [x] `backend.Dockerfile` 多阶段构建（uv lock → 精简 runtime）
- [x] `vllm-asr.Dockerfile`：Phase 1 使用 OpenAI-compatible ASR stub（真 GPU 镜像可替换同一接口）
- [x] README 写启动流程：clone → cp .env → setup.sh → start.sh → open :3000

> **Phase 1 收尾验收**：本地 `pnpm dev` + `./start.sh` 可演示；可选 Daily 增强路径；Docker 一键起。 **Phase 1 完成。**

---

## Phase 2 · 记忆深化（W3–W4）

> 目标：让 FAE 真正"记得住"——三层记忆 + 事件日志 + 用户可见的记忆浏览器。

### 准备（Phase 1 收尾已完成）

- [x] `fae.memory` 包 + `FactIn` / `FactOut` / `UserProfile` schema
- [x] `LettaMemoryClient` / `LettaMemoryService` + lifespan 接线
- [x] `app.state.memory` 挂载点 + `VoiceRuntime`（session ↔ barge-in / Daily task）
- [x] 统一 LLM `base_url` 默认含 `/v1`；打断路径接通 `/api/voice/barge-in`

### 2.1 Letta 接入

- [x] Compose 使用官方 `letta/letta:latest`（Postgres 卷 `letta-data`；离线可用 `LETTA_MODE=embedded` SQLite）
- [x] 创建 / 解析 agent：`fae-main`，挂 persona / human / current 三块 core memory
- [x] 实现 `backend/src/fae/memory/letta_client.py`（REST）+ `embedded.py`
- [x] 三个工具表面：`save_fact` / `search` / `update_user`（+ `recall_for_prompt`）
- [x] Pydantic schema：`FactIn` / `FactOut` / `UserProfile`
- [x] `/ws/chat` + `/api/chat`：召回注入 + 回合写入（启发式「我叫X」→ M2-1）

> **冒烟测试**（M2-1）：说"我叫小明"，关掉浏览器，重开，问"我叫什么" → 答"小明"。
> 本地最快：`.env` 设 `LETTA_MODE=embedded`，或 `docker compose up letta` + `LETTA_MODE=remote`。

### 2.2 Pipecat Memory Service

- [x] `LettaMemoryService`（浏览器 WS / HTTP + Daily 已接）
- [x] 接到 Daily：`seed_daily_memory` + `MemoryTurnProcessor`（同一 `recall_context` / `persist_turn`）
- [x] 每次 LLM 调用前注入相关记忆（含 `[recent_turns]` + facts；top-k=10）
- [x] 每轮结束 `append_recall` + 启发式身份事实（按 `session_id` 分桶；话题靠 recent_turns）
- [x] 自动归档：Recall 超过 N 轮时移到 Archival（Qdrant / stub）— 见 2.3

> **冒烟测试**（M2-2）：连续聊多个话题后问"我刚才提到 Python 那个项目怎么样"。
> `LETTA_MODE=embedded` 即可本地验收。

### 2.3 三层记忆 + Episodic 扩展

- [x] Core Memory：persona / human / current；`GET /api/memory/stats` + current 字数预算
- [x] Recall Memory：共享 SQLite `RecallStore` + session 分桶（hot window）
- [x] Archival Memory：Qdrant 集合 `fae_archival`（不可用时 stub）；超 N 轮 compact
- [x] **Episodic Memory 扩展**：实现 `backend/src/fae/memory/episodic.py`
  - [x] 关键事件检测（启发式："搬家"/"换了工作"等；LLM 标记后续可选）
  - [x] 事件 ↔ 记忆的双向链接（fact / archival）+ `GET /api/memory/events`
  - [x] 6 个月未访问的 archival 记忆自动降权（`ARCHIVAL_DECAY_DAYS`）

### 2.4 sleeptime 整理

- [x] 实现 `backend/src/fae/memory/consolidation.py`（启发式摘要；LLM 摘要后续可选）
- [x] 触发时机：每日定点小时 + 闲时（`SLEEPTIME_IDLE_SECONDS`，默认 5min）+ `POST /api/memory/consolidate`
- [x] 工作流：归纳 Recall → 摘要写入 Core `current` / 偏好事实 → 可选 Archival + compact
- [x] rate limit：单次最长 `SLEEPTIME_MAX_RUNTIME_S`（默认 30s）+ 会话最小间隔

### 2.5 记忆浏览器 UI

- [x] 路由 `ui/src/app/memory/page.tsx`：按时间线展示（Recharts）
- [x] 路由 `ui/src/app/memory/facts/page.tsx`：结构化事实列表 + 增删改
- [x] 路由 `ui/src/app/memory/search/page.tsx`：语义搜索框 + 命中高亮
- [x] 组件 `MemoryTimeline.tsx` + `MemorySearch.tsx`
- [x] 数据请求：TanStack Query + 乐观更新（facts CRUD）
- [x] Backend：`/api/memory/facts` CRUD、`/api/memory/search`、`/api/memory/timeline`

> **Phase 2 收尾验收**：演示"跨天记忆"——昨天告诉 FAE 喜欢的咖啡，今天它主动提起；可在 `/memory` 浏览事实与时间线。

---

## Phase 3 · Skills 体系（W5–W6）

> 目标：Skill = Markdown，按需加载。落地 5+ 内置 skill + 编辑器。

### 3.1 Skill 格式 & 加载器

- [ ] 定义 `SkillMetadata` Pydantic schema（见架构 3.4）
- [ ] 实现 `backend/src/fae/agent/skills.py`
  - [ ] YAML frontmatter 解析（用 `pyyaml`）
  - [ ] 目录扫描 `backend/src/skills/`
  - [ ] 元数据缓存（避免每次重读文件）
- [ ] 实现加载策略枚举：`ALWAYS_ON` / `TRIGGER_BASED` / `MANUAL` / `LAZY`
- [ ] 触发器匹配：关键词 + 简单 embedding 余弦（不引重型模型）

### 3.2 内置 Skills（W6 累计 ≥ 5 个）

- [ ] `daily_check_in.md`：每日问候 + 行程确认
- [ ] `technical_debugging.md`：stack trace 解析 + 排查
- [ ] `travel_planning.md`：行程规划（结合记忆）
- [ ] `reading_companion.md`：一起读文章 / 总结
- [ ] `writing_assistant.md`：写作助手
- [ ] `proactive_outreach.md`：主动发起话题（Phase 4 会深度用）

> 每个 skill 都要写：触发条件、依赖工具、边界（不做什么）、冷却时间。

### 3.3 自动触发 + 优先级

- [ ] 实现 trigger matcher：同时匹配多个 skill 时按 `priority` 选
- [ ] 注入到 LLM 的 system prompt：`<active_skills>...</active_skills>`
- [ ] LLM 主动 `request_skill(name)` 工具（LAZY 模式）
- [ ] 冷却机制：`cooldown_seconds` 内同一 skill 不重复触发

> **冒烟测试**（M3-1）：贴一段 stack trace → 10s 内看到 `technical_debugging` 被加载。

### 3.4 Skill 编辑器 UI

- [ ] 路由 `src/app/skills/page.tsx`
- [ ] 列表：所有 skill、状态（enabled/disabled）、最近触发时间
- [ ] 编辑：Monaco Editor 写 markdown，实时校验 frontmatter
- [ ] 启用/停用 + `requires_approval` 开关
- [ ] "测试触发"按钮：输入一句话看哪些 skill 会被加载

> **Phase 3 收尾验收**：演示 3 个 skill 场景各 1 分钟。

---

## Phase 4 · 主动 Loop（W7–W8）

> 目标：让 FAE 主动起来——心跳、定时任务、主动问候、桌面通知。

### 4.1 APScheduler + Heartbeat

- [ ] 实现 `backend/src/fae/scheduler/heartbeat.py`：每 30s 检查
- [ ] 实现 `backend/src/fae/scheduler/jobs.py`：注册 job 的统一入口
- [ ] 实现 `backend/src/fae/scheduler/proactive.py`
  - [ ] 用户超过 6h 未交互 + 有未回应话题 → 主动发起
  - [ ] `outreach_cooldown = 12h`，每天最多 1 次主动问候
  - [ ] "待办到期"检测：扫 Episodic Memory
- [ ] 与 LLM 的桥接：心跳触发时不走 TTS，走"桌面通知 + 文字"通道

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
- [ ] 设置页 `src/app/settings/privacy/page.tsx`：通知开关 + 勿扰时段

> **Phase 4 收尾验收**：演示 24h 无人值守，FAE 主动发起 1 次合理问候。

---

## Phase 5 · 上限扩展（W9+）

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
- [ ] Slack bot 适配器
- [ ] Telegram bot 适配器

### 5.4 多用户 / 多角色

- [ ] Letta agent 池化（每用户独立 agent_id）
- [ ] NextAuth.js 接入（OAuth + Email magic link）
- [ ] 数据隔离：每个用户独立 SQLite 文件 / Qdrant collection

---

## 跨阶段横切关注（Continuous）

> 这些不是"阶段"，但每个 PR 都要 review。

### 安全 / 隐私

- [ ] 工具权限分级实现（Safe / Caution / Sensitive / Dangerous）
- [ ] UI 确认弹窗：每次 Sensitive / Dangerous 工具执行前
- [ ] 5s 倒计时：Dangerous 工具二次确认
- [ ] "一键遗忘"：清空所有记忆 + 重置 Letta agent
- [ ] 数据导出：`src/app/settings/privacy/page.tsx` 下载 JSONL

### 可观测性

- [ ] 结构化日志（loguru / structlog）：每次 tool call 持久化
- [ ] "现在在做什么"面板：UI 透明显示 `FAE 正在调用 memory_search...`
- [ ] Token 用量统计（Recharts 折线图）
- [ ] 工具调用历史页 `src/app/tools/page.tsx`

### 性能

- [ ] 端到端延迟埋点：每个阶段打点（VAD / ASR / LLM / TTS）
- [ ] P50 / P95 仪表盘
- [ ] ASR 准确率评测（librispeech + common-voice-zh）
- [ ] TTS 自然度评测（seed-tts）
- [ ] 端到端对话评测（`evals/e2e/`）

### 评测（Evals）

- [ ] `evals/asr/`：librispeech-test.jsonl / common-voice-zh.jsonl / noisy-mixed.jsonl
- [ ] `evals/tts/`：seed-tts-test.jsonl / voice-clone-test.jsonl
- [ ] `evals/agent/`：tool-calling / memory-recall / multi-turn / proactive-loop
- [ ] `evals/e2e/`：daily-checkin / technical-debug / travel-planning
- [ ] CI 集成：每次 PR 跑核心 eval，回归报警

### 文档

- [ ] `docs/design/memory-design.md`：记忆系统设计细节
- [ ] `docs/design/skills-format.md`：Skill 格式规范
- [ ] `docs/design/ui-mockups.md`：UI 草图
- [ ] `docs/api/api-reference.md`：REST API 文档（OpenAPI 自动生成 + 人工注释）
- [ ] README：项目介绍 + Quick Start + 截图 + 演示视频链接

---

## 关键里程碑（Milestones）

| ID | 时间 | 验收标准 |
|---|---|---|
| M0 | W0 末 | 仓库脚手架 + Docker 5 服务全绿 |
| M1-1 | W1 末 | 浏览器听到自己声音回放 |
| M1-2 | W2 末 | 端到端对话 ≥ 3 轮，录 30s 视频 |
| M2-1 | W3 末 | 跨会话记忆冒烟通过 |
| M2-2 | W4 末 | 记忆浏览器 UI 可用 |
| M3-1 | W5 末 | skill 自动触发可用 |
| M3-2 | W6 末 | 5+ 内置 skill + 编辑器 |
| M4-1 | W7 末 | 定时任务 + 通知通道 |
| M4-2 | W8 末 | 24h 主动 loop 演示 |
| M5+ | W9+ | 按需取用 MCP / Subagent / 多端 |

---

## 风险登记（Risk Register）

| 风险 | 概率 | 影响 | 缓解 |
|---|---|---|---|
| Qwen3-TTS Realtime 商用授权变化 | 低 | 高 | 锁定版本号 + 备选 Fish Audio S2 Pro |
| Letta 0.50 API 变动 | 中 | 中 | 固定 `letta==0.50.*`，加 client 抽象层 |
| vLLM-Omni 不支持 Qwen3-ASR | 中 | 中 | 先打 HTTP 协议，必要时切 `transformers` 直跑 |
| WebRTC 在国内网络不稳定 | 中 | 中 | 增加 WebSocket 音频 fallback |
| 端到端延迟突破 2.5s | 中 | 高 | 各阶段埋点 + 按阶段优化（先用云端 LLM 跑通） |
| 主动 loop 误触 | 中 | 中 | 严格 cooldown + 用户勿扰时段 + 灰度发布 |

---

## 完成度跟踪

> 每个 Phase 收尾时更新本节，给团队一目了然的进度。

- [x] Phase 1 完成（M1-2 通过；浏览器默认 + Daily 增强可选）
- [x] Phase 2 完成（M2-1/M2-2 + 记忆浏览器 UI）
- [ ] Phase 3 完成（M3-2 通过）
- [ ] Phase 4 完成（M4-2 通过）
- [ ] Phase 5 持续推进

---

**最后更新**：2026-07-19（Phase 2 stable · hardening pass）
**关联文档**：[`ARCHITECTURE.md`](./ARCHITECTURE.md)
**反馈**：GitHub Issues / PR
