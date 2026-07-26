# FAE 模块手册（开发者向 · 代码现状索引）

> 本文档是 **代码现状** 的"模块索引"，目标是让新加入的开发者 10 分钟内掌握仓库结构、关键调用链、每个模块用到的包与逻辑，并与 `doc/architect/ARCHITECTURE.md` / `doc/operations/LOCAL_TTS.md` 的表述差异做校正。
>
> 架构文档见 [`doc/architect/ARCHITECTURE.md`](ARCHITECTURE.md)；部署步骤见 [`doc/operations/DEPLOY.md`](../operations/DEPLOY.md)；本机 TTS 配置见 [`doc/operations/LOCAL_TTS.md`](../operations/LOCAL_TTS.md)；未完成功能统一见 [`doc/TODO.md`](../TODO.md)。

---

## 1. 项目地图

仓库是 monorepo，分 5 个产品块：

- `backend/` — Python 后端；FastAPI 入口在 [`backend/src/fae/__init__.py`](../../backend/src/fae/__init__.py)；所有代码在 `backend/src/fae/`。
- `ui/` — Next.js 16 App Router；代码在 `ui/src/`；启动 `pnpm dev`。
- `sdk/typescript/` — 浏览器/Node 客户端（`@fae/client`），被 UI 通过 `file:../sdk/typescript` 直接 link。
- `scripts/tts/` — 本机 Qwen3-TTS 拉取、安装、启动脚本（`.deps/qwen3-tts/` 是运行期下载目录，不入库）。
- `deploy/` — Docker Compose（`docker-compose.yml` 全栈 / `docker-compose.core.yml` slim Core）。

辅助目录：`doc/`、`evals/`（离线回归，README 在 [`evals/README.md`](../../evals/README.md)）、`.github/`。

根 [`package.json`](../../package.json) `npm run dev` 用 `concurrently` 同时启 `backend` / `ui` / `tts`；`npm run setup` 跑 `uv sync --group dev`、`pnpm install`。

---

## 2. 后端模块 — `backend/src/fae/`

每个子域一段；"状态"列区分 实现 / stub / 仅规划。

### 2.1 `api/` — HTTP / WebSocket 入口（实现）

- [`backend/src/fae/api/__init__.py`](../../backend/src/fae/api/__init__.py) FastAPI 工厂 `create_app()`、`lifespan` 启动 memory / skills / scheduler / telegram；CORS + 客户端 token 中间件。
- 注册路由（按文件）：
  - `ws.py` — `WS /ws/chat`（流式 chat、cancel、skills/subagent/notification 中继）。
  - `chat`（在 `__init__.py`）— `POST /api/chat` 单轮文本。
  - `capabilities.py` — `GET /api/capabilities` 自描述能力。
  - `tts.py` — `/api/tts/{status,voices,speak}` 代理本机 TTS。
  - `voice.py` — `/api/voice/{status,session,…/barge-in}`。
  - `pipeline.py` — `POST /api/pipeline/text`（文本管线 smoke；调用 `pipecat/bot.py:TextPipelineBot`）。
  - `memory.py` — `/api/memory/{persona,profile,facts,events,stats,search,timeline,consolidate}`。
  - `skills.py` — `/api/skills` 列表 + `/{name}` `GET/PUT/PATCH` + `/test-trigger`。
  - `schedules.py` — `/api/schedules` CRUD + `/parse` + `/{id}/trigger`；`/api/scheduler/status`（由 `status_router` 提供）。
  - `notifications.py` — `/api/notifications`、`/read`、`/prefs`、`/vapid-public-key`、`/subscribe`。
  - `/health`、`/ready`、`/api/test-connection`。
- 鉴权 [`backend/src/fae/api/auth.py`](../../backend/src/fae/api/auth.py) — `client_token_required` / `require_client_token_http` / `ensure_ws_client_token`；白名单 `public_paths`。
- 依赖注入 [`backend/src/fae/api/deps.py`](../../backend/src/fae/api/deps.py) — `get_llm_client`、`get_memory_service`。
- 用到的关键包：`fastapi`（HTTP/WS 框架）、`uvicorn[standard]`（ASGI 入口）、`httpx`（少数内部调用）、`pydantic`（DTO 校验）。
- 验证：默认 client token 在 `Settings.client_token` 空时全部放行；只需在 `Settings.client_token` 非空时强制校验。

### 2.2 `agent/` — 单轮聊天 + Skills + Subagents（实现）

- [`backend/src/fae/agent/prepare.py`](../../backend/src/fae/agent/prepare.py) `prepare_chat_request()`：将 Core blocks、recall 上下文与激活技能注入到 `system` 消息。
- [`backend/src/fae/agent/llm_turn.py`](../../backend/src/fae/agent/llm_turn.py) `stream_assistant_turn()` + `apply_lazy_skill_tool()`：单回合主循环，含工具分发、token 流推送、cancel。
- 已注册工具（[`backend/src/fae/agent/known_tools.py`](../../backend/src/fae/agent/known_tools.py)）：`get_weather`、`schedule_create_job` / `list_jobs` / `cancel_job`、`request_skill`、`run_subagent`。
- Skills 子系统：
  - `skills_schema.py` — `LoadStrategy`（`ALWAYS_ON` / `TRIGGER_BASED` / `LAZY` / `MANUAL`）+ `Skill` / `SkillMetadata`。
  - `skills_loader.py` — Markdown + YAML frontmatter；默认目录 `backend/src/skills/`。
  - `skills_matcher.py` — 关键词 + Jaccard 近似（无外部 NLP）。
  - `skills_state.py` — JSON 持久化每个技能的 `enabled/approval/cooldown/last_triggered`。
  - `skills_runtime.py` — 选激活技能、构造 `<active_skills>` 与 `<available_skills>`、管理冷却；`SkillActivationInfo` 返回给上层。
- Subagents（`agent/subagents/`）：
  - `builtins.py` — `researcher` / `coder` / `reviewer` 三类无工具系统提示。
  - `runtime.py` — `run_subagent()`：执行一次子 agent turn，summary 持久化到 archival。
  - `tools.py` — `RUN_SUBAGENT_TOOL` schema + `dispatch_run_subagent()`。
- 用包：`openai`（LLM 复用，见 §2.3）、`pyyaml`（frontmatter）、`httpx`（外部 LLM HTTP）。

### 2.3 `llm/` — 大模型抽象（实现）

- [`backend/src/fae/llm/provider.py`](../../backend/src/fae/llm/provider.py) — `OpenAICompatibleProvider`（基于 `openai.AsyncOpenAI`，与 DashScope `compatible-mode` / Qwen3 / DeepSeek / vLLM 互通）+ `FakeProvider`（测试桩）。
- [`backend/src/fae/llm/client.py`](../../backend/src/fae/llm/client.py) — `LLMClient` 薄壳，统一日志与错误。
- [`backend/src/fae/llm/types.py`](../../backend/src/fae/llm/types.py) — `LLMConfig` / `ChatMessage` / `ChatRequest` / `ChatResponse` / `ToolCall`。
- 默认 `model=qwen3-max`、`base_url=https://dashscope.aliyuncs.com/compatible-mode/v1`，由 `Settings` 与 `channels/bridge.merge_llm_config` 提供回退。
- 用包：`openai`（Qwen3 / DeepSeek 通用 OpenAI 兼容客户端）、`pydantic`（DTO）。

### 2.4 `memory/` — 记忆栈（实现，部分 stub）

- [`backend/src/fae/memory/factory.py`](../../backend/src/fae/memory/factory.py) `create_memory_stack()` / `build_memory_stack()`：依 `Settings.letta_mode`（`off` / `embedded` / `remote`）组装六件套：`(client, recall, archival, compactor, episodic, embedder)`。
- Letta 远程：[`backend/src/fae/memory/letta_client.py`](../../backend/src/fae/memory/letta_client.py) `LettaMemoryClient`（HTTP，agent core blocks / facts / profile / archival）。
- 内嵌离线：[`backend/src/fae/memory/embedded.py`](../../backend/src/fae/memory/embedded.py) `EmbeddedMemoryClient`（SQLite 等价实现）。
- 热窗口 [`backend/src/fae/memory/recall_store.py`](../../backend/src/fae/memory/recall_store.py) `RecallStore`：每会话 SQLite 暂存最近 N 轮。
- Archival [`backend/src/fae/memory/archival.py`](../../backend/src/fae/memory/archival.py) `QdrantArchival`（实现，可选） / `StubArchival`（内存，tests 默认）；可配 OpenAI 兼容 embedder [`backend/src/fae/memory/embeddings.py`](../../backend/src/fae/memory/embeddings.py)。
- 事件 [`backend/src/fae/memory/episodic.py`](../../backend/src/fae/memory/episodic.py) `EpisodicStore`：生活事件 SQLite + 启发式检测。
- 事实抽取 [`backend/src/fae/memory/fact_extract.py`](../../backend/src/fae/memory/fact_extract.py)（正则启发式：姓名 / 城市 / 时区 / 饮食） + [`backend/src/fae/memory/profile_block.py`](../../backend/src/fae/memory/profile_block.py) 解析 `[human]` 块。
- 压缩 [`backend/src/fae/memory/compaction.py`](../../backend/src/fae/memory/compaction.py) `MemoryCompactor`（recall → archival） + [`backend/src/fae/memory/consolidation.py`](../../backend/src/fae/memory/consolidation.py) `MemoryConsolidator` / `SleeptimeScheduler`（汇总成 `current` block）。
- 用包：标准库 `sqlite3`、`httpx`（Letta HTTP / Qdrant REST / Telegram / Open-Meteo）、`pydantic`。
- 状态：`LettaMemoryClient` 完整实现但需远程 Letta；`EmbeddedMemoryClient` 实现完整；`QdrantArchival` 实现，默认未启用（`archival_prefer_stub=True` 在 tests）；`memory_tool_stubs / MEMORY_TOOLS` 仅占位、`tests/test_voice_runtime.py` 仅作存在性断言。

### 2.5 `tts/` — 本机 TTS（实现 + stub）

- [`backend/src/fae/tts/local_client.py`](../../backend/src/fae/tts/local_client.py) `LocalTTSClient`：通过 `httpx(trust_env=False)` 打 `POST {VLLM_TTS_URL}/v1/audio/speech`（OpenAI 兼容）；支持 PCM→WAV 包装；内置兜底 voice 列表（Vivian / Ryan / Serena / Dylan / Eric / Aiden / Uncle_Fu / Ono_Anna / Sohee）。
- [`backend/src/fae/tts/stub_server.py`](../../backend/src/fae/tts/stub_server.py) — FastAPI 桩服务（生成 440 Hz 蜂鸣音 WAV），`Settings.tts_embed_stub=True` 时挂到主应用；独立启动 `python -m fae.tts.stub_server`（:8003）。
- [`backend/src/fae/tts/wav.py`](../../backend/src/fae/tts/wav.py) — PCM16 mono ↔ WAV 头。
- [`backend/src/fae/tts/speakable.py`](../../backend/src/fae/tts/speakable.py) — 剥离 markdown / emoji / 围栏，给 TTS 干净文本。
- 用包：`httpx`（TTS HTTP）、`fastapi` / `uvicorn`（stub server）、`pydantic`。

### 2.6 `pipecat/` — 实时语音管线（部分实现 / 部分适配器占位）

- [`backend/src/fae/pipecat/daily_bot.py`](../../backend/src/fae/pipecat/daily_bot.py) `run_daily_bot()` — 完整 Daily WebRTC pipeline：OpenAI-STT（`VLLM_ASR_URL`，model `whisper-1`）→ OpenAI-LLM（DashScope compatible-mode）→ 本地 TTS（`LocalTTSService`）→ Daily → BargeIn。
- [`backend/src/fae/pipecat/bot.py`](../../backend/src/fae/pipecat/bot.py) `TextPipelineBot` — 文本路径（`/api/pipeline/text` smoke）。
- [`backend/src/fae/pipecat/services/`](../../backend/src/fae/pipecat/services/)：
  - `qwen3_llm.py` — Pipecat 适配层（实际调 `fae.llm.LLMClient`）。
  - `qwen3_tts.py` / `local_tts_service.py` — Pipecat TTSService 包装 `LocalTTSClient`；无 `base_url` 时返回静音 PCM。
  - `qwen3_asr.py` — `Qwen3ASRService`（仅 HTTP 适配器，**未被默认 Daily pipeline 使用**）。
  - `letta_memory.py` — `LettaMemoryService` 把记忆栈挂到 Pipecat frame 流程。
- [`backend/src/fae/pipecat/vad.py`](../../backend/src/fae/pipecat/vad.py) — `EnergyVAD`（实现）+ `SileroVADAnalyzer`（按需 import）。
- [`backend/src/fae/pipecat/transport.py`](../../backend/src/fae/pipecat/transport.py) — `LocalTransport`（实现）+ `DailyTransportConfig`（仅占位）。
- 用包：`pipecat-ai[daily,silero,soundfile]`（必需）、`httpx`、`soundfile`、可选 `torch`（VAD）。

### 2.7 `scheduler/` — 心跳 / 调度 / 主动触达（实现）

- [`backend/src/fae/scheduler/loop.py`](../../backend/src/fae/scheduler/loop.py) `ProactiveLoop` — `APScheduler` 编排 heartbeat、内置 job（`daily_checkin` / `weekly_recap`）、自定义 job；与 `ActivityTracker`、`NotificationDelivery`、`SkillRuntime`、`MemoryService` 集成。
- [`backend/src/fae/scheduler/store.py`](../../backend/src/fae/scheduler/store.py) `ScheduleStore` — SQLite 持久化 jobs / prefs / inbox / push 订阅 / 活动时间戳 / 外呼状态。
- [`backend/src/fae/scheduler/heartbeat.py`](../../backend/src/fae/scheduler/heartbeat.py) `HeartbeatLoop` — 周期评估每个 session 是否触达。
- [`backend/src/fae/scheduler/proactive.py`](../../backend/src/fae/scheduler/proactive.py) `OutreachPolicy` / `should_outreach`（节流）。
- [`backend/src/fae/scheduler/delivery.py`](../../backend/src/fae/scheduler/delivery.py) `NotificationDelivery` — 五通道：inbox / WS / Web Push / Desktop / Telegram。
- [`backend/src/fae/scheduler/hub.py`](../../backend/src/fae/scheduler/hub.py) `ConnectionHub` — `WebSocket` 广播；被 `/ws/chat` 注册。
- [`backend/src/fae/scheduler/parse_nl.py`](../../backend/src/fae/scheduler/parse_nl.py) — 自然语言 → cron / run_at（中文 + 英文）。
- [`backend/src/fae/scheduler/tools.py`](../../backend/src/fae/scheduler/tools.py) — `schedule_*` 工具 schema + dispatch（被 `agent.llm_turn` 复用）。
- [`backend/src/fae/scheduler/activity.py`](../../backend/src/fae/scheduler/activity.py) `ActivityTracker` — 共享 idle 时钟。
- 用包：`apscheduler`（cron / interval / date）、`httpx`（Telegram Bot API）、`sqlite3`、可选 `pywebpush`。

### 2.8 `channels/` — 外部文本入口（实现）

- [`backend/src/fae/channels/bridge.py`](../../backend/src/fae/channels/bridge.py) — 合并客户端 LLM 配置与服务端 `PROACTIVE_LLM_*` / `DASHSCOPE_API_KEY`；把外部文本并入 `prepare_chat_request()` + `apply_lazy_skill_tool()`。
- [`backend/src/fae/channels/telegram.py`](../../backend/src/fae/channels/telegram.py) — `TelegramClient`（`getUpdates` 长轮询 / `sendMessage`）；`telegram_poll_loop()` 由 `api/__init__.py::lifespan` 在 token + chat_id 齐备时启动。
- 用包：`httpx`。

### 2.9 `notifications/` — Web Push / Desktop（实现，best-effort）

- [`backend/src/fae/notifications/webpush.py`](../../backend/src/fae/notifications/webpush.py) `send_web_push()`（`pywebpush`，可缺）。
- [`backend/src/fae/notifications/desktop.py`](../../backend/src/fae/notifications/desktop.py) `send_desktop_notification()`（`osascript` / `notify-send`）。
- 被 `scheduler.delivery.NotificationDelivery` 调用。

### 2.10 `tools/` — 工具实现（实现）

- [`backend/src/fae/tools/weather.py`](../../backend/src/fae/tools/weather.py) `get_weather()`：Open-Meteo 地理编码 + 当前天气 + 高低温 + 降雨概率。
- [`backend/src/fae/tools/context.py`](../../backend/src/fae/tools/context.py) `build_runtime_context()`：在系统提示注入本地时间、家乡城市 / 时区。

### 2.11 顶层 — `config.py` / `sessions.py` / `voice_runtime.py`

- [`backend/src/fae/config.py`](../../backend/src/fae/config.py) `Settings`（Pydantic-Settings，读取根 `.env`）+ `get_settings()`（`lru_cache`）。
- [`backend/src/fae/sessions.py`](../../backend/src/fae/sessions.py) `SessionStore` — 进程内 session 注册（不含 turn 持久化，那是 `RecallStore`）。
- [`backend/src/fae/voice_runtime.py`](../../backend/src/fae/voice_runtime.py) `VoiceRuntime` — voice session 注册中心 + Daily 任务托管 + `interrupt_pipeline()` 回调。

---

## 3. 前端 — `ui/src/`

### 3.1 路由与页面（[`ui/src/app/`](../../ui/src/app/)）

| 路由 | 文件 | 行为 |
|---|---|---|
| `/` | `page.tsx` | 聊天主页；`HomeContent` 用 `Suspense` 读 `useSearchParams`，渲染 `VoiceOrb` / `MicButton` / `ChatTranscript` |
| `/memory` | `memory/page.tsx` | 时间线 + 折线图（`recharts`） |
| `/memory/facts` | `memory/facts/page.tsx` | 事实增删改查（乐观更新 + 回滚） |
| `/memory/search` | `memory/search/page.tsx` | 输入框 → `searchMemory(q)` → facts/archival/events 三类合并渲染 |
| `/skills` | `skills/page.tsx` | 列表 + Monaco 编辑器 + 测试触发 |
| `/schedules` | `schedules/page.tsx` | 自然语言解析 → 确认草稿 → 创建；`JobRow` 子组件支持启用/禁用/触发/删除 |
| `/settings` | `settings/page.tsx` | 5 个 tab 用 `?tab=persona\|profile\|models\|voice\|notifications` 切换 |

布局 [`ui/src/app/layout.tsx`](../../ui/src/app/layout.tsx) — `QueryProvider` + Syne/DM Sans 字体；`<html lang="zh-CN">`。

### 3.2 共享组件（[`ui/src/components/`](../../ui/src/components/)）

- `AppNav.tsx` — 顶部 5 链接；轮询 `["scheduler-status"]`（30s）拿 `unread_inbox`，未读红点指向 `?tab=notifications`。
- `voice/VoiceOrb.tsx` — `framer-motion` 圆环，按 `idle/listening/thinking/speaking` 切关键帧。
- `voice/MicButton.tsx` / `voice/ChatTranscript.tsx` — 单按钮 + Markdown 流式渲染；`isThinkingStreaming` 时显示"思考中…"。
- `memory/{MemoryNav,MemoryTimeline,MemorySearch}.tsx` — 导航 + 时间线 + 搜索。
- `settings/{PersonaPanel,ProfilePanel,ModelsPanel,VoicePanel,NotificationsPanel}.tsx` — 5 个 tab 的面板实现；`VoicePanel` 含 TTS 试听 + 高级折叠区里的"Daily WebRTC（可选）"开关。

### 3.3 lib / hooks（[`ui/src/lib/`](../../ui/src/lib/)）

- `config.ts` — `AgentConfig`（`baseUrl`、`model`、`apiKey`、`thinking`）+ `loadConfig` / `saveConfig` + `backendHttpBase/WsBase` + `clientAccessToken()`。
- `models.ts` — `ModelProfile[]`（持久化在 `fae.modelProfiles`）+ `setActiveModel`；通过 `fae:config-changed` 事件通知其它组件。
- `speech.ts` — `BrowserSTT`（封装 `webkitSpeechRecognition`）；`speechSupported()`；`lang` 自动从 `TtsPrefs.language` 映射（zh-CN/en-US/ja-JP/ko-KR）。
- `qwen-tts.ts` — `fetchSpeakBlob` / `speakWithLocalTts` / `TtsPlayQueue`（`maxInflight=2`、`minStartReady=1`）+ `fetchTtsStatus/Voices`。
- `sentence-agg.ts` — `SpeechChunkAggregator`：先硬切 `HARD_END=/(?<=[。！？.!?…\n])/`、再软切 ≥28 字、最后长度截断 `TTS_CHUNK_CHARS=40`，空闲 250 ms 软刷。
- `speakable.ts` — TTS 前清洗（与 [`backend/src/fae/tts/speakable.py`](../../backend/src/fae/tts/speakable.py) 镜像）：去 markdown / emoji / filler / `lmao+|lol+|x[dD]` 等。
- `strip-thinking.ts` — 剥 `…` 与 ```` ```thinking ```` 围栏；判断 `isThinkingStreaming`。
- `ws-chat.ts` — UI 端 WS 客户端（薄壳，转发到 `@fae/client.WsChatClient`）。
- `pipecat-client.ts` — `createVoiceSession()`：仅是 `POST /api/voice/session` 的 fetch 封装，**不依赖任何 Pipecat 客户端 SDK**。
- `daily-session.ts` — `joinDailyRoom()` / `leaveDailyRoom()`（`@daily-co/daily-js`）；只起 mic 进 Daily room，不订阅远端音频。
- `*-api.ts`（`memory-api.ts` / `skills-api.ts` / `schedules-api.ts` / `notifications-api.ts`） — 各面板对应后端端点的封装。
- `network-error.ts` — 把 `Failed to fetch` 等翻成中文"无法连接后端"。
- `tts-prefs.ts` / `voice-prefs.ts` / `client-identity.ts` — `fae.ttsPrefs` / `fae.preferDaily` / `fae.memorySessionId` localStorage 仓库。

### 3.4 hooks

- [`ui/src/hooks/useVoiceSession.ts`](../../ui/src/hooks/useVoiceSession.ts) 唯一业务 hook，集中管理 STT/WS/TTS/Daily：
  - `runAssistant()` 主路径：取消旧流 → `wsRef.chat()` → 累积 `assistantBuf` → `toSpeakableText` → `SpeechChunkAggregator.push` → `TtsPlayQueue.enqueue`。
  - `interrupt()` 复位聚合器、`ttsQueue.stop()`、`wsRef.cancel()`、`stt.stop()`；Daily 模式额外 `POST /api/voice/barge-in`。
  - `TurnMetrics`（`sttFinalAt / llmFirstTokenAt / ttsFirstByteAt / ttsFirstPlayAt / ttsServerMs`），`?debug=1` 时在头部展示。
  - 卸载 effect 同时清理 STT、aggregator、TTS queue、Daily、WS。

### 3.5 状态与数据流

- 服务端状态：[`ui/src/providers/QueryProvider.tsx`](../../ui/src/providers/QueryProvider.tsx) — TanStack Query；默认 `staleTime: 10s`、`refetchOnWindowFocus: false`；`useMutation` 全部走乐观更新 + `onError` 回滚 + `onSettled` 失效。
- 客户端状态：纯 `useState` / `useRef`（集中在 `useVoiceSession.ts`）。`window.CustomEvent`（`fae:config-changed` / `fae:tts-prefs-changed` / `fae:prefer-daily-changed`）做跨组件同步。

---

## 4. TS SDK — `sdk/typescript/src/`

- [`sdk/typescript/src/client.ts`](../../sdk/typescript/src/client.ts) `FaeClient`：HTTP / REST + 能力发现（`getCapabilities` / `getReady` / `listNotifications` / `subscribeNotifications`）。
- [`sdk/typescript/src/ws-chat.ts`](../../sdk/typescript/src/ws-chat.ts) `WsChatClient`：流式 `/ws/chat`，事件 `skills / subagent / token / done / notification / error`。
- [`sdk/typescript/src/types.ts`](../../sdk/typescript/src/types.ts) `LlmConfigInput` / `WsServerMessage` / `StreamHandlers` / `FaeCapabilities` / `FaeReady`。
- 被 UI 通过 `ui/package.json` 的 `"@fae/client": "file:../sdk/typescript"` link 直接使用。

---

## 5. 本机 TTS 子系统 — `scripts/tts/` + `.deps/qwen3-tts/`

仓库本身不带有 Qwen3-TTS 服务源码；运行时由 `scripts/tts/setup.sh` clone 第三方到 `.deps/qwen3-tts/`。

- [`scripts/tts/setup.sh`](../../scripts/tts/setup.sh) — `git clone --depth 1 https://github.com/groxaxo/Qwen3-TTS-Openai-Fastapi.git` 到 `.deps/qwen3-tts`；PyTorch venv 装 `.[api]`；Apple Silicon 额外建 `.venv-mlx` 装 `mlx-audio>=0.3`。
- [`scripts/tts/run.sh`](../../scripts/tts/run.sh) — 端口 8880（`FAE_TTS_PORT`，默认 8880）；Apple Silicon：`TTS_BACKEND=mlx` + `MLX_MODEL_ID=mlx-community/Qwen3-TTS-12Hz-1.7B-CustomVoice-bf16` + `TTS_MAX_CONCURRENT=1` + `TTS_LAZY_LOAD=false` + `TTS_WARMUP_ON_START=true`；其它平台：PyTorch + `Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice` + `TTS_DEVICE=cpu` + `TTS_DTYPE=float32` + `TTS_ATTN=sdpa`。最终 `exec python -m api.main`。
- [`scripts/tts/prepare.sh`](../../scripts/tts/prepare.sh) — 用 `huggingface_hub.snapshot_download` 下载权重；启动服务 → POST `/v1/audio/speech` 一句"你好，语音已就绪。" warmup → macOS 下 `afplay` 自动试听。
- 第三方 venv 用到的核心包：`mlx-audio`（Apple Silicon 推理）、`huggingface_hub[hf_xet]`、`fastapi`、`uvicorn[standard]`、`python-multipart`、`pydantic`、`inflect`、`aiofiles`、`pydub`、`httpx`、`numpy`、`librosa`、`soundfile`、`einops`、`PyYAML`、`requests`、`tqdm`；再 `pip install -e . --no-deps` 装仓库自身。

---

## 6. 部署 / 脚本

- [`deploy/scripts/start.sh`](../../deploy/scripts/start.sh) — 全栈 Compose（`docker-compose.yml`）。
- [`deploy/scripts/start-core.sh`](../../deploy/scripts/start-core.sh) — Slim Core（`docker-compose.core.yml`），`WITH_TTS_STUB=1` 时再生成 override，把 backend 的 `VLLM_TTS_URL` 指向 `http://tts:8880/v1`。
- `docker-compose.core.yml` — 默认只跑 `backend`（embedded SQLite 记忆），TTS stub 是 `--profile tts` 可选。
- `docker-compose.yml` — 全栈：`backend / ui / letta / vllm-asr / qdrant / redis`；`vllm-asr` 当前是固定返回"你好"的 stub（[`deploy/docker/asr-stub/main.py`](../../deploy/docker/asr-stub/main.py)）。
- 根 [`package.json`](../../package.json) `dev`（concurrently 启 backend/ui/tts）、`setup`、`setup:tts`、`prepare:tts`、`dev:stub`、`test:backend`、`build:ui`。

---

## 7. 关键调用链

```
┌── 文本 ───────────────────────────────────────────────┐
UI → ui/src/lib/ws-chat.ts → @fae/client.WsChatClient
 → POST /ws/chat (backend/src/fae/api/ws.py)
 → agent.prepare.prepare_chat_request()
 → agent.llm_turn.stream_assistant_turn()
 → llm.LLMClient.stream() → llm.OpenAICompatibleProvider → openai.AsyncOpenAI → DashScope compatible-mode
 → 工具分发：agent.known_tools → tools / scheduler.tools / agent.subagents
 → ConnectionHub.broadcast() 把 notification 推回 UI
└───────────────────────────────────────────────────────┘

┌── 语音（默认，浏览器 STT + 本机 Qwen3-TTS） ───────────┐
UI: useVoiceSession.startListening() → BrowserSTT.start(lang=zh-CN)
 → onResult(final) → runAssistant(text)
 → wsRef.chat()（同上）
 → onToken：assistantBuf += delta → toSpeakableText → SpeechChunkAggregator.push → TtsPlayQueue.enqueue
 → TtsPlayQueue.pumpSynth: POST /api/tts/speak → LocalTTSClient → POST {VLLM_TTS_URL}/v1/audio/speech → .deps/qwen3-tts/api.main
 → 拿到 WAV/PCM16 → primeNext → audio.play()
 → interrupt(): reset aggregator / ttsQueue.stop() / wsRef.cancel() / stt.stop()
└───────────────────────────────────────────────────────┘

┌── 语音（Daily，可选） ────────────────────────────────┐
voice_panel.preferDaily=true → useVoiceSession.connectDaily()
 → POST /api/voice/session {prefer_daily:true, llm_config, memory_session_id}
 → 拿 roomUrl + token → daily-session.joinDailyRoom(roomUrl, token)
 → 后端 run_daily_bot()：Pipecat pipeline
   OpenAI-STT (VLLM_ASR_URL=whisper-1) → OpenAI-LLM (DashScope) → LocalTTSService → Daily WebRTC
 → BargeInController 在 on_ready 注册 interrupt_pipeline()
 → barge-in: POST /api/voice/{sessionId}/barge-in
└───────────────────────────────────────────────────────┘

┌── 主动 Loop（后台） ───────────────────────────────────┐
lifespan → ProactiveLoop.start()
 → tick(): Scheduler 触发 heartbeat + builtin jobs + custom jobs
 → 必要时 ActivityTracker.idle_seconds(sid) + OutreachPolicy.should_outreach()
 → NotificationDelivery(item, channels=[ws, webpush, desktop, telegram, inbox])
 → ConnectionHub.broadcast()
└───────────────────────────────────────────────────────┘
```

---

## 8. 依赖速查（包 → 一句话用途）

### Backend — `backend/pyproject.toml`

| 包 | 用途 |
|---|---|
| `fastapi` | HTTP / WebSocket / OpenAPI |
| `uvicorn[standard]` | ASGI 服务进程（含 WebSocket） |
| `pydantic` / `pydantic-settings` | DTO + 配置（读取 `.env`） |
| `python-dotenv` | `.env` 装载（通过 Pydantic Settings） |
| `openai>=1.60` | `AsyncOpenAI` 客户端；用于 Qwen3 / DeepSeek / OpenAI / vLLM 全部 OpenAI 兼容端点 |
| `httpx>=0.28` | TTS、Letta、Telegram、Open-Meteo、embedding 等所有外部 HTTP |
| `websockets>=14.0` | WS peer；测试 + uvicorn 显式 WS |
| `pipecat-ai[daily,silero,soundfile]>=0.0.92` | Daily pipeline、Silero VAD、SmartTurn、音频 I/O |
| `pyyaml>=6.0` | 技能 frontmatter 解析 |
| `apscheduler>=3.10` | heartbeat / cron / 一次性任务 / 主动 Loop |
| `pywebpush>=2.0` | Web Push（VAPID），见 `notifications/webpush.py` |

> 注：未列入直接依赖但仍需要的运行时组件：标准库 `sqlite3`（Recall / Schedule / Episodic）；`fastapi` / `uvicorn` / `pydantic` / `httpx` / `numpy` 在第三方 Qwen3-TTS 仓的 `mlx-audio` venv 中单独安装。

> 不在本仓 manifest：`dashscope`、`qwen-tts`、`mlx-audio`、`vllm`、`letta`、`qdrant-client`、`redis`、`cosyvoice`、`python-multipart`（缺会导致 full compose 的 ASR stub 启动失败，见 §10.4）。

### UI — `ui/package.json`

| 包 | 用途 |
|---|---|
| `next 16.2.11` | App Router、构建、`output: "standalone"` |
| `react 19.2.8` / `react-dom` | UI 框架 |
| `@fae/client`（`file:../sdk/typescript`） | 同源 TS SDK（WS chat / capabilities / notifications） |
| `@daily-co/daily-js ^0.91.0` | Daily WebRTC 房间（仅启 mic，不订阅远端音频） |
| `@tanstack/react-query ^5` | 服务端状态（memory / skills / schedules / notifications / scheduler-status） |
| `@monaco-editor/react ^4.7.0` | Skill Markdown 编辑器 |
| `framer-motion ^12.42` | VoiceOrb 动画 |
| `react-markdown` + `remark-gfm` | 聊天富文本 + GFM 表格 / 任务列表 |
| `recharts ^3.10` | 记忆时间线折线图 |
| `tailwindcss ^4` + `@tailwindcss/postcss` | 样式系统 |
| `zod ^4.4.3` / `zustand ^5.0.14` | 已声明但当前源码无任何调用点（未使用，可清理） |

### 根 `package.json`

| 包 | 用途 |
|---|---|
| `concurrently ^9.2` | 并行启 backend / UI / TTS，任意进程失败整体终止 |

---

## 9. 默认配置与状态汇总表

| 组件 | 当前状态 | 配置开关 | 默认行为 |
|---|---|---|---|
| LLM provider | 实现 | `Settings.openai_compat_*` 或客户端 `apiKey/baseUrl/model` | DashScope `compatible-mode` + `qwen3-max` |
| TTS | 实现 | `VLLM_TTS_URL` | `http://127.0.0.1:8880/v1`（本机 Qwen3-TTS） |
| TTS 文本上限 | 实现 | `Settings.tts_*` | 单段 ≤ 120 字符（API 侧），UI 侧 chunk ≤ 40 字符 |
| TTS stub | 实现（默认未挂） | `Settings.tts_embed_stub` (False) | 仅当显式启用或 standalone `python -m fae.tts.stub_server` 时存在（8003） |
| 浏览器 STT | 实现 | `TtsPrefs.language` → `lang` 映射 | zh-CN/en-US/ja-JP/ko-KR |
| Daily STT | 实现 | `VLLM_ASR_URL` | Pipecat `OpenAISTTService` + model `whisper-1` |
| Pipecat `Qwen3ASRService` | 仅适配器占位 | — | 不挂入主路径 |
| Full compose ASR | stub | — | `vllm-asr` 容器固定返回 `{"text":"你好",…}`；镜像缺 `python-multipart` 时启动失败（见 §10.4） |
| Letta / SQLite | 二选一 | `Settings.letta_mode`：`off`/`embedded`/`remote` | 生产推荐 `remote`；CI / 单机推荐 `embedded` |
| CosyVoice | 协议兼容声明 | 替换 `VLLM_TTS_URL` 指向 OpenAI 兼容 CosyVoice 网关 | **未验证**；默认 voice 列表偏 Qwen CustomVoice，可能无效 |
| Scheduler | 实现（默认关） | `Settings.scheduler_enabled` | CI/tests 默认 `false` |
| Web Push | 实现（best-effort） | `Settings.vapid_*` | 未配 VAPID 时跳过 |
| Telegram | 实现 | `Settings.telegram_bot_token` + `telegram_chat_id` + `telegram_enabled` | 缺一则 `telegram_ready()==False` |
| 鉴权 | 实现 | `Settings.client_token` | 空 → 全开放；非空 → 必填 `Authorization: Bearer …` |

---

## 10. 与 `doc/architect/ARCHITECTURE.md` / `doc/operations/LOCAL_TTS.md` 的差异校正

> 这是"以代码为准" 的纠偏；阅读架构文档时建议同时对照本节。

### 10.1 默认语音链

- 代码事实：浏览器 `Web Speech API` STT → `/ws/chat` → 后端 proxy 不参与音频流 → UI `SpeechChunkAggregator` → `POST /api/tts/speak` → `LocalTTSClient` → `POST {VLLM_TTS_URL}/v1/audio/speech` → `.deps/qwen3-tts`（`python -m api.main`）→ WAV → 浏览器 `Audio.play()`。
- [`doc/architect/ARCHITECTURE.md`](ARCHITECTURE.md) 中历史段落曾写"云 DashScope Realtime" 或"自带 LLM TTS"，**目前未启用**。

### 10.2 TTS 实际后端

- 代码事实：默认是 `groxaxo/Qwen3-TTS-Openai-Fastapi`；Apple Silicon → `mlx-audio` + 1.7B CustomVoice bf16；其它平台 → PyTorch + 0.6B CustomVoice。
- [`doc/operations/LOCAL_TTS.md`](../operations/LOCAL_TTS.md) 几处与脚本默认值不一致：
  - 文档行 23–25 写"最多 4 个 in-flight，首播等待 2 个"，实际 `qwen-tts.ts:214-225` 是 `maxInflight=2`、`minStartReady=1`。
  - 文档行 66–69 与 85–87 写"8-bit / 8-bit checkpoint"，实际默认 `bf16`、并发 1。
  - 文档行 127 写"Mac `concurrent=2`"，实际 `scripts/tts/run.sh:26-29` 是 `TTS_MAX_CONCURRENT=1`。
  - 文档行 129 写"`pip install -e .[api,mlx]`"，实际 `scripts/tts/setup.sh:55-76` 是手动装依赖 + `pip install -e . --no-deps`。

### 10.3 CosyVoice

- 代码事实：仓库无 CosyVoice 包、无 Dockerfile / 启动脚本、无模型配置、无集成测试；只有 [`backend/src/fae/tts/local_client.py`](../../backend/src/fae/tts/local_client.py) 注释把它当作"如外部 CosyVoice 网关兼容 `/v1/audio/speech` 则可工作"的潜在后端。`Settings` 与 README 提到的"Qwen3-TTS / CosyVoice / stub" 在不替换 `VLLM_TTS_URL` 的情况下不会被实际启用。

### 10.4 ASR 与 full compose 的破损假设

- [`deploy/docker/vllm-asr.Dockerfile`](../../deploy/docker/vllm-asr.Dockerfile) 当前只装 `fastapi` + `uvicorn`，但 `deploy/docker/asr-stub/main.py` 用了 `File` / `UploadFile`，缺 `python-multipart` 启动可能直接报 `ImportError`。
- `Qwen3ASRService`（[`backend/src/fae/pipecat/services/qwen3_asr.py`](../../backend/src/fae/pipecat/services/qwen3_asr.py)）**未接入默认 Daily pipeline**；`daily_bot.py` 实际用 Pipecat `OpenAISTTService` + `VLLM_ASR_URL` + model `whisper-1`。

### 10.5 Daily / Pipecat 客户端角色

- [`ui/src/lib/pipecat-client.ts`](../../ui/src/lib/pipecat-client.ts) 只是 `POST /api/voice/session` 的 fetch 封装，**不引用 `@pipecat-ai/client-react`**（UI 并未安装该 SDK）；
- UI 对 Daily 路径只调用 `joinDailyRoom()` 起 mic，不订阅远端 track；真正的服务端 pipeline 由 `run_daily_bot` 驱动。

### 10.6 UI 路由 / 组件 / store 列表（与架构文档老版本不同）

- 实际存在的页面：`/`、`/memory`、`/memory/facts`、`/memory/search`、`/skills`、`/schedules`、`/settings`（tab 切）；**不存在** `src/app/tools/`、`src/app/onboarding/`、`src/app/settings/voice/`、`src/app/settings/model/`、`src/app/settings/privacy/`、`src/app/agents/`。
- 实际组件：`AppNav`、`voice/{VoiceOrb,MicButton,ChatTranscript}`、`memory/{MemoryNav,MemoryTimeline,MemorySearch,FactsList}`、`settings/{PersonaPanel,ProfilePanel,ModelsPanel,VoicePanel,NotificationsPanel}`、`skills/{SkillList,SkillEditor,...}`、`schedules/{JobList,JobRow,...}`。**不存在** `lib/store.ts`、Zustand store、Radix、`MessageBubble`、`ToolCallCard`、`AudioVisualizer`、`Sidebar`、`TopBar`。
- 实际 store：纯 React（`useState` / `useRef`），跨组件用 `window.CustomEvent`；`zod` / `zustand` 已声明但未使用。

### 10.7 `VLLM_LLM_URL`

- [`backend/src/fae/config.py`](../../backend/src/fae/config.py) 声明的 `vllm_llm_url` 在仓库内无任何调用点，是死配置；full compose 把 `LLM_BASE_URL` 传给 Letta 而不是 FAE 主聊天 provider。

### 10.8 stub / 占位 与可跳过项

- `backend/src/fae/pipecat/transport.py:44` `DailyTransportConfig` 仅占位；
- `backend/src/fae/memory/factory.py` 的 `MEMORY_TOOLS` 列表仅为 `tests/test_voice_runtime.py` 的存在性断言；
- `backend/src/fae/api/pipeline.py` `/api/pipeline/text` 是 smoke，不被 UI 路径使用；
- `TTS embed stub` 默认 `False`，需要显式开启或 standalone 运行 `python -m fae.tts.stub_server`。

---

## 11. 建议阅读顺序（新加入的开发者）

1. [`backend/src/fae/__init__.py`](../../backend/src/fae/__init__.py) → [`backend/src/fae/config.py`](../../backend/src/fae/config.py) → [`backend/src/fae/sessions.py`](../../backend/src/fae/sessions.py) → [`backend/src/fae/voice_runtime.py`](../../backend/src/fae/voice_runtime.py) — 全局。
2. [`backend/src/fae/api/__init__.py`](../../backend/src/fae/api/__init__.py)（lifespan）→ [`backend/src/fae/api/deps.py`](../../backend/src/fae/api/deps.py) → [`backend/src/fae/api/ws.py`](../../backend/src/fae/api/ws.py) — 请求路径与依赖注入。
3. [`backend/src/fae/llm/`](../../backend/src/fae/llm/) → [`backend/src/fae/agent/prepare.py`](../../backend/src/fae/agent/prepare.py) → [`backend/src/fae/agent/llm_turn.py`](../../backend/src/fae/agent/llm_turn.py) — 单轮对话 + 工具分发。
4. [`backend/src/fae/memory/factory.py`](../../backend/src/fae/memory/factory.py) → [`backend/src/fae/memory/letta_client.py`](../../backend/src/fae/memory/letta_client.py) & [`backend/src/fae/memory/embedded.py`](../../backend/src/fae/memory/embedded.py) → `recall_store / archival / compaction / consolidation / episodic` — 记忆栈。
5. [`backend/src/fae/agent/skills_runtime.py`](../../backend/src/fae/agent/skills_runtime.py) + `skills_loader / matcher / state / schema` → `subagents/*` — Skills + 子代理。
6. [`backend/src/fae/scheduler/`](../../backend/src/fae/scheduler/) 全目录 — 调度与通知。
7. [`backend/src/fae/pipecat/`](../../backend/src/fae/pipecat/) — 语音管线，重点是 `daily_bot.py` 与 `services/`。
8. [`backend/src/fae/tts/`](../../backend/src/fae/tts/) + [`backend/src/fae/tools/`](../../backend/src/fae/tools/) + [`backend/src/fae/channels/`](../../backend/src/fae/channels/) + [`backend/src/fae/notifications/`](../../backend/src/fae/notifications/) — 外围集成。
9. UI：[`ui/src/app/layout.tsx`](../../ui/src/app/layout.tsx) → [`ui/src/app/page.tsx`](../../ui/src/app/page.tsx) → [`ui/src/hooks/useVoiceSession.ts`](../../ui/src/hooks/useVoiceSession.ts) → [`ui/src/lib/`](../../ui/src/lib/) — 前端入口与状态机。
10. [`scripts/tts/`](../../scripts/tts/) 三脚本 + [`deploy/scripts/`](../../deploy/scripts/) — 部署。

---

## 12. 校验清单

- `rg "ProactiveLoop|LocalTTSClient|OpenAICompatibleProvider|ConnectionHub|ActivityTracker"` 在仓库内有命中。
- `rg "pipecat-ai|apscheduler|pywebpush|mlx-audio|groxaxo/Qwen3-TTS-Openai-Fastapi"` 在仓库内有命中。
- `rg "/ws/chat|/api/tts/speak|/api/voice/session"` 在仓库内有命中。
- `rg "BrowserSTT|TtsPlayQueue|SpeechChunkAggregator"` 在 UI 内有命中。
- 与 `doc/architect/ARCHITECTURE.md` / `doc/operations/LOCAL_TTS.md` 差异对照，§10 列出的差异仍有效。
