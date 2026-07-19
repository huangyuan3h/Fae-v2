# FAE-v2 开发计划 Checklist

> 本文档是 `ARCHITECTURE.md` 的**执行映射**，把架构设计拆解为可勾选的任务清单。  
> 用法：完成一项就打 `[x]`，每条任务标明阶段、依赖、产出、验收。  
> 维护原则：阶段边界 = 一次可演示的成果（Demo-Ready），不要跨阶段合并。  
> **现行优先级**：**质量 > 上限**。Phase 1–4 骨架已齐，下一主线是把「勉强能用」做成「真好用」。

---

## 0. 总览（2026-07-19 修订）

| 阶段 | 名称 | 状态 | 阶段成果（Demo-Ready 标准） |
|---|---|---|---|
| Phase 1 | MVP | ✅ 骨架完成 | 浏览器语音对话 + Docker 一键起 |
| Phase 2 | 记忆深化 | ✅ 骨架完成 | 三层记忆 + 记忆浏览器 UI |
| Phase 2.6 | 本地 TTS | ✅ 首版 | 浏览器 STT + `/ws/chat` + Qwen3-TTS（无 Daily） |
| Phase 3 | Skills 体系 | ✅ 骨架完成 | Markdown skill 自动触发 + 6 内置 + `/skills` |
| Phase 4 | 主动 Loop | ✅ 骨架完成 | 心跳 + 定时任务 + 主动问候 + 通知 |
| **Phase Q** | **质量硬化** | **🔜 下一主线** | 语音可用 · Skill 真触发 · 记忆真有用 · Loop 真主动 |
| Phase 5 | 上限扩展 | 待开始（按优先级取用） | 多端/channel → Subagents → 其余可选 |

### 0.1 现状判断

| 域 | 骨架 | 真实体验 | 一句话 |
|---|---|---|---|
| 语音 | ✅ | ⚠ 勉强能用 | 浏览器 STT 单次识别；TTS 非流式、首包慢；打断/路径分裂 |
| Skills | ✅ | ⚠ 很弱 | 关键词 Jaccard；`requires_tools` 未接线；剧本薄 |
| 记忆 | ✅ | ⚠ 很弱 | 事实靠正则；archival 常 stub 向量；sleeptime 非真摘要 |
| Loop | ✅ | ⚠ 很弱 | 主动文案常回落到罐头句；会话绑定弱；推送依赖 VAPID |

**结论**：不要急着冲 Phase 5「上限」。先做 **Phase Q**，把 1–4 从「能演示」做成「愿意天天用」。

### 0.2 概念速查（易混淆项）

#### Local ASR（本地语音识别，可选增强）

- **是什么**：本机跑的语音→文字服务（设计目标：Qwen3-ASR via `VLLM_ASR_URL`，OpenAI-compatible `POST /v1/audio/transcriptions`）。
- **现在默认用什么**：浏览器 **Web Speech API**（Chrome 等），**不经过** `VLLM_ASR_URL`。
- **仓库里现状**：Daily/Pipecat 路径会读 `VLLM_ASR_URL`；Compose 多半是 **stub（固定回「你好」）**，不能当真识别。
- **何时值得做**：要摆脱浏览器 STT 的语言/浏览器限制、或要做真全双工 WebRTC 时再升优先级。  
  → 归 **Phase 5 可选**，不阻塞 Phase Q。

#### Daily / LiveKit（可选 WebRTC 传输层）

| | Daily | LiveKit |
|---|---|---|
| 角色 | 把麦克风/扬声器音频用 **WebRTC** 送进 Pipecat | 同角色的另一家传输层 |
| 本仓库 | **部分实现**（需 `DAILY_API_KEY`） | **未实现**（仅架构文档提及） |
| 适合场景 | 低延迟全双工、服务端 VAD/打断、真流式 STT→LLM→TTS | 同上，换厂商 |
| 与默认路径关系 | **可选**；默认是「浏览器 STT + `/ws/chat` 文本 + HTTP 拉本地 TTS」 | 更后 |

**产品默认路径（现行）**：

```text
Mic → 浏览器 STT → /ws/chat（文本流）→ 本地 TTS HTTP → 浏览器 Audio 播放
```

Daily/LiveKit **不是**「本地 TTS」的开关；它们是「全双工实时语音房间」。没 Key、不勾选时，完全不需要它们。  
→ 归 **Phase 5 可选**；Phase Q 优先把默认 WS 路径做稳。

#### MCP（降级 / 暂缓）

MCP（Model Context Protocol）曾是「接外部工具」的通用协议。对本项目：

- Skills + 自有 Tool Registry 已是主扩展面；
- 通用 MCP client（stdio/SSE、权限合并）**投入大、短期收益低**；
- 用户判断：**已落伍于当前优先级**，不排入近期主线。

若未来某类工具生态（filesystem / IDE / 数据库）以 MCP 为唯一入口，再单独立项；**不默认进 Phase 5 主清单**。

---

## Phase 1 · MVP — ✅ 骨架完成

> 细节见 git 历史。摘要：脚手架、FastAPI、Pipecat（含 Daily 可选）、Next UI、Docker。

- [x] 基础设施 / FastAPI / Pipecat 最小管线 / 最小 UI / 部署闭环
- [x] 浏览器路径：Web Speech STT/TTS + `/ws/chat`
- [x] Daily 可选路径（WebRTC）— TTS 已统一为本机服务

**质量债 → Phase Q.1**

---

## Phase 2 · 记忆深化 — ✅ 骨架完成

- [x] 2.1 Letta（remote / embedded）
- [x] 2.2 Pipecat / WS 记忆注入与持久化
- [x] 2.3 Recall + Archival + Episodic
- [x] 2.4 sleeptime consolidation
- [x] 2.5 记忆浏览器 UI

**质量债 → Phase Q.3**

---

## Phase 2.6 · 本地语音栈 — ✅ 首版

> 目标：开发者 **零 Daily Key** 即可听到自然、本地合成的中文语音。

### 已完成

- [x] `VLLM_TTS_URL` + `POST /api/tts/speak` / `GET /api/tts/status`
- [x] 移除云端 TTS；UI 优先 Qwen3-TTS，失败降级 `speechSynthesis`
- [x] TTS stub 内嵌；`npm run setup:tts` + 真模型路径文档

### 未完成（并入 Phase Q.1）

- [ ] 流式首包 / 降低首句可听延迟
- [ ] 同步 `ARCHITECTURE.md` 默认路径说明（WS + 本地 TTS，非 WebRTC 主路径）

---

## Phase 3 · Skills 体系 — ✅ 骨架完成

- [x] Schema / Loader / Matcher / 6 内置 / `/skills` UI / REST
- [x] `SkillRuntime` + WS `skills` 事件；Phase 4 `activate()`
- [x] LAZY：`request_skill` 一轮 tool

### 已知残留（并入 Phase Q.2）— ✅ 已消化

| 项 | 状态 | 说明 |
|---|---|---|
| Daily 路径按轮 match | ✅ | seed 空文本；每轮 rematch |
| `max_context_tokens` / `requires_tools` / approval UI | ✅ | 校验+截断；徽章无审批流 |
| 内置 skill 剧本深度 | ✅ | Acceptance dialogues |
| `technical_debugging` 的 `search_history` | ✅ | 已删除悬空声明 |

---

## Phase 4 · 主动 Loop — ✅ 骨架完成

- [x] APScheduler + Heartbeat + builtin cron
- [x] `/schedules` UI + 通知（inbox / WS / desktop / Web Push）
- [x] NL 创建任务（regex 级）

**质量债 → Phase Q.4**

---

## Phase Q · 质量硬化 — 🔜 下一主线

> **目标**：同一套功能，从「冒烟能过」变成「日常愿意开着」。  
> **不做**：MCP、多用户、LiveKit（除非 Q 完成且明确需要）。  
> **验收总标**：本地无 Daily Key，中文语音聊 10 轮可打断；跨天记得 3 件事实；贴 Traceback 稳触发 skill；idle 后主动问候有记忆、非罐头句。

### Q.1 语音可用（Voice Quality）— ✅ 首版

**问题**：浏览器 STT 单次、硬编码 `zh-CN`；TTS 整段 WAV + 队列门槛导致首包慢；打断浏览器/服务端分裂；长回复被 clip。

- [x] **STT UX**：单击开关 + continuous；语言跟 Settings；错误中文提示
- [x] **TTS 延迟**：`minStartReady=1`；`clip` 放宽到 120（真流式后置）
- [x] **打断一条故事**：浏览器用停播 + WS cancel；Daily 才打 barge-in；speaking 打断后自动再听
- [x] **路径诚实**：首页/Settings 区分「浏览器 STT · 本机 TTS」vs「Daily 全双工」
- [x] **埋点**：`console.debug("[fae.voice]", …)` + `X-FAE-TTS-Ms`
- [x] **验收（MQ-1）**：无 Daily Key，真 Qwen3-TTS，3 轮中文问答，首句可听，可打断

### Q.2 Skills 变强（Skill Usefulness）— ✅ 首版

**问题**：匹配浅、工具契约假、剧本薄、Daily 不同步。

- [x] **契约诚实**：删除悬空 `search_history`；`requires_tools` 对照已知工具集校验；`max_context_tokens` 注入截断；需审批徽章（无完整审批流）
- [x] **匹配质量**：短 trigger 单独命中封顶低于阈值；fixture 正负例；对话页展示 `name(score)`（未上 embedding）
- [x] **6 个内置加深**：Acceptance dialogues；旅行/写作记忆写回约定
- [x] **路径对齐**：Daily seed 空文本仅 always_on；每轮 Transcription 后 rematch
- [x] **验收（MQ-2）**：Traceback / 旅行 / 写作 fixture + Skills 页三场景 preset；误触发负例可对比

### Q.0 人设可配置（人情味入口）— ✅

> 先让用户能设定「FAE 是谁、怎么说话」，再谈记忆/技能深度。

- [x] `persona` 注入 `recall_for_prompt`（修复「存了不进 prompt」）
- [x] 共享 `DEFAULT_PERSONA` + 温暖默认文案 + 3 预设
- [x] `GET/PUT /api/memory/persona`（含 `reset`）
- [x] Settings →「人设」tab；与「重要信息」(human) 分离
- [x] Daily `system_instruction` 读取同一 persona

**验收**：Settings 改人设 → 下一轮对话语气一致；恢复默认可用。

### Q.3 记忆真有用（Memory Usefulness）— ✅ 首版

**问题**：事实正则、episodic 关键词、archival stub 向量、sleeptime 堆字、会话 ID 碎片。

- [x] **身份稳定**：UI `localStorage` → `session_id=default`；chat / WS / Daily memory / proactive / consolidate 对齐
- [x] **事实提取升级**：姓名/城市/忌口启发式写入 `human`（LLM 抽取仍后置）
- [x] **Archival 诚实 + 可选真向量**：`vector_mode` stub|real；`EMBEDDING_*` OpenAI-compatible；身份 fact upsert archival
- [x] **Sleeptime 短摘要**：`current` 替换为短 bullet；durable 行再跑 `facts_from_turn` → human
- [x] **Recall 偏置**：`[current]` 注入截断；identity facts 置顶；identity archival 全局检索
- [x] **Memory UI 最小可观测**：vector_mode 横幅、session 显示、facts tags/时间
- [ ] **后置**：LLM 事实抽取 / 待确认队列 / 完整 provenance 面板 / 一键遗忘
- [x] **验收（MQ-3）**：说「我叫 X，住 Y，忌 Z」→ 关页重开仍答对（human）；stub 时 UI 标明不可靠

### Q.4 Loop 真主动（Proactive Usefulness）

**问题**：主动生成常缺服务端 LLM Key → 罐头句；idle 状态进程内丢失；任务绑 `default` session；open_topic 过粗。

- [x] **主动生成有脑**：服务端 `PROACTIVE_LLM_*`（回退 `DASHSCOPE_API_KEY`）+ `prepare_chat_request` 注入记忆；失败 `notify` 告警，禁止静默罐头句
- [x] **Activity 持久化**：`activity_last_at` / `outreach_state` SQLite；启动 hydrate
- [x] **投递绑会话**：notify 默认 `session_id=default`；WS `speak: true` → 在线短本地 TTS
- [x] **资格更聪明**：human 非默认或问句/身份话题才 open；勿扰与 `proactive_enabled` 抑制生成
- [x] **日程解析加固**：中文 fixture（明早8点 / 明天早上八点 / 后天9点）；Schedules 解析→确认→创建
- [x] **验收（MQ-4）**：调短 idle 后主动问候可引用记忆；「明早 8 点提醒…」parse 确认后到点进收件箱（+ WS）

### Q.5 横切（随 Q.1–Q.4 穿插）

- [ ] 同步 `ARCHITECTURE.md`：默认语音路径、Daily 可选、LiveKit 未实现、MCP 暂缓
- [ ] README：质量状态与「下一主线 = Phase Q」一致
- [ ] 最小 evals：`evals/agent/` memory-recall + skill-trigger；`evals/e2e/` 无 Daily 一轮语音（可 stub TTS）

---

## Phase 5 · 上限扩展（按优先级，不并行冲）

> 进入「无上限」前，**默认已完成 Phase Q 主验收（MQ-1～MQ-4）**。  
> 下列顺序 = 当前产品优先级（高 → 低）。

### 5.1 多端 & 第三方 channel ← **优先做**

> 需要：同一 Agent 不只困在桌面浏览器标签页。

- [ ] PWA（manifest + SW，基础离线壳）
- [ ] 移动端响应式（对话 / 通知 / 设置主路径可用）
- [ ] Telegram bot 适配器（先做 1 个 channel，跑通记忆 + 主动通知）
- [ ] Slack 适配器（第二 channel）
- [ ] 通道统一：inbound 文本/命令 → 同一 agent core；outbound 通知可路由到 channel

**验收（M5-1）**：手机浏览器可用主对话；Telegram 能收主动提醒并回一句写入记忆。

### 5.2 Subagents ← **要做，但次于多端**

> 主 agent 委派重活，结果回灌；不做「多智能体产品」叙事膨胀。

- [ ] 接口：`run_subagent(name, task, context)` + 超时 / 取消 / 结果摘要
- [ ] 内置 2～3 个：`researcher` / `coder`（或 `reviewer`）— 先质量后数量
- [ ] 主对话可委派；UI 可见「子任务进行中 / 结果」
- [ ] 与 Skills：委派可由 skill 剧本触发，而非另起一套触发器

**验收（M5-2）**：主对话委托「调研 X」→ 子 agent 回摘要进记忆，主回复可引用。

### 5.3 多用户 / 多角色 ← **低优先级**

> 单用户本地陪伴仍是主场景；多租户延后。

- [ ] Letta agent 池化（每用户 `agent_id`）
- [ ] Auth（OAuth / magic link）— 选型时再定，不提前锁 NextAuth
- [ ] 存储与记忆隔离

**验收**：仅在明确要分享给第二人时开工。

### 5.4 本地 ASR（可选增强）

> 见 §0.2。默认路径仍可继续用浏览器 STT，直到 Q.1 体验到位再决定是否切换。

- [ ] 真 Qwen3-ASR（或兼容服务）替换 compose stub
- [ ] Settings：STT 来源 `browser` / `local`
- [ ] 浏览器路径可选走本地 ASR（麦克风 PCM → 后端转写），不强制 Daily

**验收**：无外网、无浏览器 STT 时，本地 ASR 中文可用。

### 5.5 Daily / LiveKit（可选增强）

> 见 §0.2。仅在需要 **低延迟全双工 WebRTC** 时投入。

- [ ] Daily：每轮 skills/memory 与 WS 对齐；文本输入不再 stub
- [ ] 文档标明 LiveKit = 未实现备选；**不提前双栈**
- [ ] 若 Daily 授权/成本不可接受，再评估 LiveKit 单栈替换（二选一，不并行维护）

### 5.6 MCP（暂缓）

- [ ] ~~近期实现通用 MCP client~~ → **暂缓**（理由见 §0.2）
- [ ] 若重启：仅接「明确需要的 1 个 server」做垂直集成，不做大而全 registry

---

## 跨阶段横切关注（Continuous）

### 安全 / 隐私

- [ ] 工具权限分级（Safe / Caution / Sensitive / Dangerous）
- [ ] UI 确认：Sensitive / Dangerous
- [ ] 「一键遗忘」+ 数据导出 JSONL
- [x] LLM API Key 默认存浏览器；服务端不落盘 UI Key；主动 Loop 用服务端 `PROACTIVE_LLM_*` / `DASHSCOPE_API_KEY`（Q.4）
- [ ] 本地 TTS / ASR：音频默认不离开本机（文档写清）

### 可观测性 / 性能 / 评测

- [ ] 结构化日志：tool call / TTS 后端 / skill 触发分
- [ ] 「现在在做什么」面板
- [ ] 端到端延迟：STT / LLM / 本地 TTS（P50/P95 可后补仪表盘）
- [ ] `evals/`：memory-recall · skill-trigger · 无 Daily 语音回合

### 文档

- [ ] `ARCHITECTURE.md` 与现行默认路径一致
- [ ] README：Phase Q 为下一主线；Daily ≠ 本地 TTS；MCP 暂缓
- [x] README Quick Start：`npm run setup` + `npm run dev`

---

## 关键里程碑（修订）

| ID | 验收标准 | 状态 |
|---|---|---|
| M0～M4 | 各阶段骨架 Demo | ✅ |
| M2.6-1 / M2.6-2 | 本地 TTS stub / 真模型可播 | ✅ 首版（体验进 Q.1） |
| **MQ-0** | 人设可配置：Settings 改 persona 下一轮生效 | ✅ |
| **MQ-3** | 记忆：名字/城市/忌口跨刷新；vector_mode 诚实 | ✅ 首版 |
| **MQ-1** | 语音：可打断、首包可接受、路径文案诚实 | ✅ 首版 |
| **MQ-2** | Skills：三场景稳定 + 契约无悬空 | ✅ Q.2 首版 |
| **MQ-3** | 记忆：跨会话事实 + 非 stub 检索 | 🔜 |
| **MQ-4** | Loop：有记忆的主动问候 + 可靠提醒 | ✅ Q.4 首版 |
| **M5-1** | 多端 / Telegram（或等价 channel） | 待 Q 后 |
| **M5-2** | Subagent 委派回灌 | 待 Q 后 |
| M5.3+ | 多用户 / 本地 ASR / WebRTC / MCP | 按需 |

---

## 风险登记（修订）

| 风险 | 概率 | 影响 | 缓解 |
|---|---|---|---|
| 把「骨架完成」当「可用」继续堆功能 | 高 | 高 | **锁定 Phase Q 为下一主线** |
| 本地 TTS VRAM / 首包慢 | 中 | 高 | stub 保开发；流式/分句；文档写清机型 |
| 主动 Loop 无服务端模型配置 → 罐头句 | 高 | 高 | Q.4 显式配置 + 失败告警 |
| archival stub 向量伪装「语义记忆」 | 高 | 高 | UI/日志标明 stub；Q.3 上真 embedding |
| 误把 Daily 当本地 TTS | 中 | 中 | Settings 文案 + ARCH 同步 |
| MCP / 多用户过早投入 | 中 | 中 | 文档降级；默认不做 |
| 主动 loop 误触 | 中 | 中 | cooldown + 勿扰 + 更严 open_topic |

---

## 完成度跟踪

- [x] Phase 1～4 骨架
- [x] Phase 2.6 本地 TTS 首版
- [x] Phase Q.0 人设可配置
- [x] Phase Q.3 记忆真有用（首版）
- [x] Phase Q.1 语音可用（首版）
- [x] Phase Q.4 Loop 真主动（首版）
- [x] Phase Q.2 Skills 变强（首版）
- [ ] **Phase Q 横切 / Q.5** ← **下一主线**（evals · README · ARCHITECTURE）
- [ ] Phase 5.1 多端 & channel
- [ ] Phase 5.2 Subagents
- [ ] Phase 5.3+ 按需（多用户 / ASR / WebRTC）；MCP 暂缓

---

## 近期执行顺序（建议）

1. **Phase Q.0** 人设可配置 — ✅  
2. **Phase Q.3** 记忆真有用 — ✅ 首版  
3. **Phase Q.1** 语音可用 — ✅ 首版  
4. **Phase Q.4** Loop 真主动 — ✅ 首版  
5. **Phase Q.2** Skills 变强 — ✅ 首版  
6. **Phase Q.5** 横切（evals / README / ARCHITECTURE）  
7. **Phase 5.1** 多端 & Telegram  
8. **Phase 5.2** Subagents  
9. 可选：本地 ASR → Daily 对齐 →（仅必要时）LiveKit；**MCP 默认不做**

---

**最后更新**：2026-07-19（Q.0～Q.4 首版落地；下一主线 Q.5 横切）  
**关联文档**：[`ARCHITECTURE.md`](./ARCHITECTURE.md) · [`LOCAL_TTS.md`](./LOCAL_TTS.md)  
**反馈**：GitHub Issues / PR
