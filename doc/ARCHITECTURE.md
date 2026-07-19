# FAE-v2 架构文档

> **F**ully **A**utonomous **E**cho · v2
> 一个有长期记忆、能主动 loop、可本地部署的语音 Agent。

---

## 0. 文档目的

本文档是 **FAE-v2** 的"第一份真相源（single source of truth）"，用于：

1. **交给 Coding Agent**：让它在无需进一步追问的情况下，自主完成 MVP 落地
2. **设计决策记录**：所有关键技术选型的"为什么"都在这里
3. **未来扩展锚点**：模块边界清晰，方便后续添加新能力

> 优先级：**质量 > 上限**。许可证 **Apache 2.0 / MIT 优先**，闭源 / 商用受限一律排除。

---

## 1. 项目愿景与核心能力

### 1.1 一句话定义

FAE-v2 是一个**可自托管的个人助理 Agent Core**：
- 🎙️ **能听会说**（默认浏览器路径；语音可加深）
- 🧠 **能记住事**：跨会话、跨天的长期记忆
- 🎯 **主动 loop**：定时任务 / 主动发起话题 / 提醒
- 🛠️ **有真本事**：可扩展工具（目标：日历、文件、脚本、第三方 API…）
- 📱 **Client 可替换**：Web / Telegram / 未来任意壳，只连同一 Core

> 产品叙事见 [`DEVELOPMENT_PLAN.md`](./DEVELOPMENT_PLAN.md)（P6 起）。Web UI 是**参考壳**，不是产品本体。

### 1.2 与同类产品的差异

| 维度 | ChatGPT Voice | ElevenLabs Agent | **FAE-v2** |
|---|---|---|---|
| 语音模型 | OpenAI 闭源 | ElevenLabs 闭源 | **Qwen3 全套（开源）** |
| 长期记忆 | 弱 / 黑盒 | 无 | **Letta 状态化 + 多层记忆** |
| 主动 loop | ❌ | ❌ | ✅ **APScheduler + 心跳** |
| 本地部署 | ❌ | ❌ | ✅ |
| 数据隐私 | 云端 | 云端 | **本地优先** |
| 上限天花板 | 受限于 OpenAI | 受限于 ElevenLabs | **无上限（自托管）** |

---

## 2. 顶层架构

> **现行默认路径**：浏览器 Web Speech STT → `/ws/chat`（LLM + memory + skills）→ 本机 TTS（`VLLM_TTS_URL`）。  
> **可选**：Daily + Pipecat 全双工（需 `DAILY_API_KEY`）；Telegram long-polling channel（`TELEGRAM_*`，共享 `session_id=default`）。  
> **未实现**：LiveKit / Slack。MCP 不作唯一扩展面（见 DEVELOPMENT_PLAN P8）。  
> **下一主线**：P6 Core 常驻 & 快速部署（配置外置、compose/Release、远程 channel）。

```text
┌────────────────────────────────────────────────────────────────┐
│                       浏览器（Web UI · Next.js）                 │
│  VoiceOrb · Chat · /memory · /skills · /schedules · Settings   │
└───────────────┬────────────────────────────┬───────────────────┘
                │ 默认                        │ 可选
                │ Web Speech STT              │ Daily WebRTC
                │ + /ws/chat                  │ + Pipecat bot
                ▼                             ▼
┌───────────────────────────────┐  ┌─────────────────────────────┐
│ FastAPI Agent Core            │  │ Daily voice pipeline        │
│  prepare → LLM → tools        │  │  VAD → STT → LLM → local TTS│
│  memory · skills · scheduler  │  │  (LiveKit: not implemented) │
└───────────────┬───────────────┘  └──────────────┬──────────────┘
                │                                 │
                └────────────┬────────────────────┘
                             ▼
┌────────────────────────────────────────────────────────────────┐
│ 本机 TTS HTTP（Qwen3-TTS / CosyVoice / stub · VLLM_TTS_URL）    │
│ 记忆：Letta remote 或 embedded SQLite · archival 可选向量       │
│ LLM：浏览器 Key 或服务端 DASHSCOPE / PROACTIVE_LLM_*            │
└────────────────────────────────────────────────────────────────┘
```

---

## 3. 技术选型（Why）

### 3.1 语音栈（现行）

| 层 | 默认路径 | 可选 / 后置 | 说明 |
|---|---|---|---|
| **STT** | 浏览器 Web Speech API | Daily 路径上的 OpenAI-compatible ASR（`VLLM_ASR_URL`） | 本地 ASR（Qwen3-ASR）属 Phase 5 可选 |
| **TTS** | 本机 OpenAI-compatible HTTP（`VLLM_TTS_URL`：Qwen3-TTS / CosyVoice / stub） | — | **不是** DashScope Realtime 云端 TTS |
| **LLM** | 浏览器 Settings 的 OpenAI-compatible Key | 服务端 `DASHSCOPE_API_KEY` / `PROACTIVE_LLM_*`（主动 Loop） | 聊天 Key 不落盘到服务端 UI 配置 |

### 3.2 语音管道：默认 WS vs 可选 Pipecat/Daily

- **默认**：无 WebRTC — UI STT → FastAPI `/ws/chat` → 流式 token → UI 调 `/api/tts/speak` 播本机 TTS
- **可选 Daily**：Pipecat + Daily transport（VAD / SmartTurn / barge-in）；需 `DAILY_API_KEY`
- **LiveKit**：未实现；不要当作现行路径
- Pipecat 仍是 Daily 路径的框架选择（Python-first、frame pipeline）

> 不使用 **Vercel AI SDK 7 Realtime** 作默认语音栈。  
> MCP（Model Context Protocol）**暂缓**，不以近期主清单推进。

### 3.3 长期记忆：Letta（原 MemGPT）

#### 选型对比

| 框架 | 哲学 | 上限 | 适配度 |
|---|---|---|---|
| Mem0 | "记忆层"插件 | 中 | ⭐⭐⭐ |
| Zep | 时序知识图谱 | 高 | ⭐⭐⭐⭐（偏企业） |
| **Letta** | **Agent 即状态** | **极高** | ⭐⭐⭐⭐⭐ |

#### 为什么选 Letta

1. **stateful runtime**：agent 是长进程，自管记忆预算，不只是"调一次 API"
2. **sleeptime 整理**：闲时自动压缩 / 整理 / 摘要记忆，不阻塞对话
3. **三层记忆**：core memory（in-context） + recall memory（最近对话） + archival memory（向量检索）
4. **REST API**：天然可被 Pipecat 调度
5. **开源 Apache 2.0**，自部署

#### 记忆架构（FAE-v2 自定义扩展）

```text
┌──────────────────────────────────────────────────┐
│           Letta Memory Hierarchy                  │
├──────────────────────────────────────────────────┤
│                                                   │
│  ┌────────────────────────────────────────────┐   │
│  │ Core Memory（in-context，永远在 prompt 里）│   │
│  │  • persona:  FAE 是谁 / 性格 / 边界        │   │
│  │  • user:     用户画像 / 偏好 / 禁忌        │   │
│  │  • current:  当前会话上下文（短窗口）      │   │
│  └────────────────────────────────────────────┘   │
│                       ↓ 自动溢出                  │
│  ┌────────────────────────────────────────────┐   │
│  │ Recall Memory（最近 N 轮对话）             │   │
│  │  • SQLite + 时间戳                          │   │
│  │  • 自动按 session 分桶                      │   │
│  └────────────────────────────────────────────┘   │
│                       ↓ 长期归档                  │
│  ┌────────────────────────────────────────────┐   │
│  │ Archival Memory（向量 + 结构化）            │   │
│  │  • Qdrant 向量库（语义检索）               │   │
│  │  • 标签：topic / entity / event             │   │
│  │  • 时效衰减：6 个月未访问降权               │   │
│  └────────────────────────────────────────────┘   │
│                                                   │
│  ┌────────────────────────────────────────────┐   │
│  │ Episodic Memory（FAE-v2 扩展：事件日志）    │   │
│  │  • 关键事件标记："用户搬家" / "换了工作"     │   │
│  │  • 跨检索链接相关记忆                       │   │
│  └────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────┘
```

#### 记忆工具（Agent 可调用）

| 工具名 | 作用 | 触发时机 |
|---|---|---|
| `memory_save_fact` | 写入结构化事实 | 用户说"记住：……" / 重要决策时 |
| `memory_search` | 语义检索历史 | 每次 LLM 调用前自动注入 |
| `memory_update_user` | 更新用户画像 | 检测到用户偏好 / 习惯变化 |
| `memory_link_events` | 建立事件关联 | 检测到话题相关性时 |
| `memory_consolidate` | 主动整理记忆 | sleeptime / 定时任务 |
| `memory_forget` | 主动遗忘 | 用户说"忘掉这件事" |

### 3.4 Skills 系统（重点）

> **Skill = 在特定场景下，按需加载到 prompt 的"剧本"**
> 设计哲学借鉴 Vercel Eve：Markdown 编写，描述触发条件，运行时按需加载。

#### Skill 文件结构

```text
agent/
├── skills/
│   ├── daily_check_in.md            # 每日问候 + 行程确认
│   ├── technical_debugging.md       # 帮用户排查代码 bug
│   ├── travel_planning.md           # 行程规划（结合记忆）
│   ├── reading_companion.md         # 一起读文章 / 总结
│   ├── writing_assistant.md         # 写作助手
│   ├── mood_support.md              # 情绪支持（谨慎设计）
│   └── proactive_outreach.md        # 主动发起话题
```

#### Skill 格式规范

```markdown
---
name: technical_debugging
description: 帮助用户排查代码 bug、分析错误日志、阅读 stack trace
triggers:
  - 用户贴 stack trace / error message
  - 用户说"帮我看看这个报错"
  - 用户描述一个程序行为异常
requires_tools:
  - read_file
  - search_history  # 检查是否聊过类似问题
priority: 8
max_context_tokens: 1500
---

# Technical Debugging Skill

## 角色
你是 FAE，技术调试专家。你的风格：
- 先复述问题，再分析
- 不要急着给答案，先问 1-2 个澄清问题
- 引用 stack trace 时保留原始格式

## 工作流
1. **复述**：用 1-2 句话复述用户的问题
2. **检索记忆**：调用 `search_history` 检查是否遇到过类似问题
3. **澄清**：如果信息不全，最多问 2 个关键问题
4. **分析**：给出 2-3 个可能原因，按概率排序
5. **建议**：给出可操作的排查步骤
6. **记录**：解决后调用 `memory_save_fact` 存到用户档案

## 边界
- 不直接执行代码（除非用户明确允许）
- 不假设用户用的是哪种语言 / 框架
- 涉及删除 / 部署操作，必须 human-in-the-loop 确认
```

#### Skill 加载策略

| 策略 | 说明 | 何时用 |
|---|---|---|
| **Always-on** | 永远在 core prompt 里 | persona / 安全边界 |
| **Trigger-based** | 匹配 trigger 自动加载 | 大部分 skills |
| **Manual** | 用户手动启用 | 高风险 skills（写文件 / 执行命令） |
| **Lazy** | LLM 主动请求 | 大型 skill，避免 prompt 膨胀 |

#### Skill 元数据 Schema

```python
class SkillMetadata(BaseModel):
    name: str
    description: str
    triggers: list[str]          # 关键词 / 意图
    requires_tools: list[str]    # 依赖的工具
    priority: int = 5           # 0-10，多个 skill 冲突时优先级
    max_context_tokens: int = 1000
    enabled: bool = True
    requires_approval: bool = False  # 是否需要人工确认
    cooldown_seconds: int = 0    # 同一 skill 触发冷却
```

### 3.5 Tool / Function Calling

#### 工具分类

```text
tools/
├── core/                     # 核心工具
│   ├── memory/               # 记忆相关（见 3.3）
│   ├── search/               # 网络搜索（Tavily / Serper）
│   ├── file_ops/             # 读 / 写 / 搜索本地文件
│   ├── shell/                # 受限的 shell 执行（需人工确认）
│   └── schedule/             # 创建 / 查询 / 取消定时任务
├── skills/                   # Skill-specific 工具
│   ├── code_runner.py        # 安全执行 Python 代码
│   ├── git_ops.py            # git status / diff / commit
│   └── doc_search.py         # 检索本地文档
└── integrations/             # 外部集成
    ├── github.py             # GitHub API（PR / issue）
    ├── notion.py             # Notion 读写
    ├── calendar.py           # 日程（ics）
    └── email.py              # 邮件收发
```

#### Tool Schema 规范（TypeScript 风格，借鉴 Vercel Eve）

```typescript
// tools/get_weather.ts
import { defineTool } from "eve/tools";
import { z } from "zod";

export default defineTool({
  name: "get_weather",
  description: "查询指定城市的当前天气",
  inputSchema: z.object({
    city: z.string().describe("城市名，如 'Tokyo' / '北京'"),
    unit: z.enum(["celsius", "fahrenheit"]).default("celsius"),
  }),
  requiresApproval: false,
  async execute(input, ctx) {
    const res = await fetch(`${process.env.WEATHER_API}/current?city=${input.city}`);
    return res.json();
  },
});
```

> **设计原则**：文件名即工具名（参考 Eve），零注册成本。

### 3.6 主动 Loop & 定时任务

#### 心跳架构

```text
┌──────────────────────────────────────────────────────┐
│              FAE-v2 Proactive Loop                    │
├──────────────────────────────────────────────────────┤
│                                                       │
│   APScheduler（asyncio）                              │
│    ├── Heartbeat: 每 30s 检查                        │
│    │    └── 有新事件？→ 唤醒 agent → 调用工具          │
│    │                                                  │
│    ├── Daily Trigger: 每天 08:00                      │
│    │    └── 加载 daily_check_in skill                 │
│    │    └── 检索昨日记忆 → 生成问候                    │
│    │                                                  │
│    ├── Weekly Trigger: 每周日 20:00                    │
│    │    └── 生成周报 / 整理记忆                        │
│    │                                                  │
│    └── User-defined Cron: 用户自定义                  │
│         └── "明天下午 3 点提醒我开会"                  │
│                                                       │
│   主动发起对话的触发条件（心跳层判断）：                │
│    • 用户超过 6 小时未交互 + 有未回应话题              │
│    • 检测到记忆中的"待办事项"到期                     │
│    • Skill 定义：proactive_outreach（每天最多 1 次）  │
└──────────────────────────────────────────────────────┘
```

#### 心跳实现（伪代码）

```python
# agent/scheduler.py

class ProactiveLoop:
    def __init__(self, agent: LettaAgent):
        self.agent = agent
        self.scheduler = AsyncIOScheduler()
        self.last_interaction = datetime.now()
        self.outreach_cooldown = timedelta(hours=12)

    async def on_user_message(self):
        self.last_interaction = datetime.now()

    async def heartbeat(self):
        if datetime.now() - self.last_interaction < timedelta(minutes=30):
            return

        # 检查是否有待办 / 事件
        pending = await self.agent.call_tool(
            "memory_search",
            {"query": "待办 提醒 即将到期", "tier": "episodic"}
        )
        if pending:
            await self.agent.generate_response(
                context=pending,
                intent="remind_user",
                channel=self._pick_channel(),
            )

    def start(self):
        self.scheduler.add_job(self.heartbeat, "interval", seconds=30)
        self.scheduler.add_job(self.daily_checkin, "cron", hour=8, minute=0)
        self.scheduler.add_job(self.weekly_recap, "cron", day_of_week="sun", hour=20)
        self.scheduler.start()
```

### 3.7 图形界面：Next.js 15 + shadcn/ui

#### 技术栈

| 层 | 选型 | 理由 |
|---|---|---|
| 框架 | **Next.js 15**（App Router） | RSC、Streaming、Server Actions |
| UI 库 | **shadcn/ui** + Tailwind CSS 4 | 2026 本地 AI 工具主流，可复制粘贴定制 |
| 状态 | **Zustand** | 轻量、对接 WebRTC 流简单 |
| 数据请求 | **TanStack Query** | 记忆 / 任务的乐观更新 |
| 音频 | **Pipecat React Client** + **Daily JS SDK** | 官方配套 |
| 动画 | **Framer Motion** | VoiceOrb 动效 |
| 图表 | **Recharts** | 记忆增长 / Token 用量可视化 |

#### 关键页面

```text
src/app/
├── page.tsx                    # 主对话页（VoiceOrb + ChatPanel）
├── memory/                     # 记忆浏览器
│   ├── page.tsx                # 记忆总览（按时间线）
│   ├── facts/page.tsx          # 结构化事实
│   └── search/page.tsx         # 语义搜索
├── schedules/                  # 定时任务管理
│   └── page.tsx
├── skills/                     # Skills 启用 / 配置
│   └── page.tsx
├── tools/                      # 工具调用历史
│   └── page.tsx
├── settings/
│   ├── voice/page.tsx          # 声音克隆（Qwen3-TTS）
│   ├── model/page.tsx          # LLM 选择
│   └── privacy/page.tsx        # 数据导出 / 删除
└── onboarding/                 # 首次使用引导
```

#### UI 设计原则

1. **VoiceOrb 为主视觉**：圆环动效，说话时呼吸感、思考时旋转、待机时缓慢脉冲
2. **暗色优先**：默认 dark mode（OLED 友好），用户可切换
3. **可降级**：麦克风坏了 → 文字输入；TTS 失败 → 只看文本
4. **本地优先**：所有数据存本地（IndexedDB），UI 是浏览器里的本地应用
5. **可观测**：每页都有"现在在做什么"的透明显示（"FAE 正在调用 memory_search……"）

---

## 4. 数据流：从麦克风到扬声器

### 4.1 默认链路（无 Daily）

```text
1. 用户说话 → 浏览器 Web Speech STT（continuous）→ 文本
              ↓
2. UI WebSocket → FastAPI /ws/chat
              ↓
3. prepare_chat_request：memory 注入 + skill match/inject + tools
              ↓
4. LLM 流式 token → WS type=token（可带 skills scores）
              ↓
5. UI 分句聚合 → POST /api/tts/speak → 本机 TTS（VLLM_TTS_URL）→ 播放
              ↓
6. 打断：停本地 TTS + WS cancel（非 Daily barge-in）
              ↓
7. persist_turn → recall / human facts；sleeptime 闲时整理
```

### 4.1b 可选 Daily 链路

```text
浏览器 Daily room → Pipecat（VAD / SmartTurn / STT）
  → LLM（persona + memory seed；每轮 skills rematch）
  → 本机 LocalTTSService → Daily 出站音频
LiveKit：未实现
```

### 4.2 延迟预算

| 阶段 | 目标延迟 |
|---|---|
| VAD + ASR | < 400ms |
| LLM 首 token | < 500ms |
| LLM 整句生成 | < 1500ms |
| TTS 首包 | < 150ms |
| **端到端** | **< 2500ms（P50）** |

> 当 LLM 在工具调用循环里时，整体可达 < 4s（P95）。

### 4.3 打断处理

- **默认浏览器路径**：停止本地 TTS 播放队列 + 向 `/ws/chat` 发 `cancel`；说完后可自动再听
- **Daily 路径**：Pipecat `InterruptionFrame` / barge-in（仅此路径）

---

## 5. 项目目录结构

```text
FAE-v2/
├── README.md
├── ARCHITECTURE.md                  # → points to doc/ARCHITECTURE.md
├── docker-compose.yml
├── .env.example
├── doc/
│   ├── ARCHITECTURE.md              # 本文档（权威）
│   ├── DEVELOPMENT_PLAN.md          # 阶段 checklist
│   └── LOCAL_TTS.md
│
├── backend/
│   ├── pyproject.toml
│   ├── src/
│   │   ├── fae/
│   │   │   ├── config.py
│   │   │   ├── api/                 # FastAPI package
│   │   │   │   ├── __init__.py      # create_app + lifespan
│   │   │   │   ├── ws.py / chat paths
│   │   │   │   ├── memory.py        # /api/memory/*
│   │   │   │   ├── skills.py        # /api/skills/*
│   │   │   │   ├── tts.py / voice.py / pipeline.py
│   │   │   │   └── (schedules.py — Phase 4)
│   │   │   ├── agent/               # Skills + turn prep
│   │   │   │   ├── skills_schema.py / skills_loader.py
│   │   │   │   ├── skills_matcher.py / skills_runtime.py
│   │   │   │   ├── prepare.py / llm_turn.py
│   │   │   ├── memory/              # Letta + recall/archival/episodic
│   │   │   │   └── consolidation.py # SleeptimeScheduler (≠ proactive)
│   │   │   ├── scheduler/           # Phase 4 proactive loop
│   │   │   │   ├── activity.py / heartbeat.py
│   │   │   │   ├── proactive.py / jobs.py
│   │   │   ├── tts/                  # local OpenAI-compatible client + stub
│   │   │   ├── llm/ / pipecat/
│   │   └── skills/                  # Markdown skills (6 built-ins)
│   └── tests/
│
├── ui/
│   ├── package.json
│   ├── src/
│   │   ├── app/                     # /  /settings  /memory  /skills  (/schedules Phase 4)
│   │   ├── components/
│   │   │   ├── AppNav.tsx            # shared primary nav
│   │   │   ├── voice/
│   │   │   │   ├── VoiceOrb.tsx
│   │   │   │   ├── MicButton.tsx
│   │   │   │   └── AudioVisualizer.tsx
│   │   │   ├── chat/
│   │   │   │   ├── ChatPanel.tsx
│   │   │   │   ├── MessageBubble.tsx
│   │   │   │   └── ToolCallCard.tsx
│   │   │   ├── memory/
│   │   │   │   ├── MemoryTimeline.tsx
│   │   │   │   └── MemorySearch.tsx
│   │   │   └── layout/
│   │   │       ├── Sidebar.tsx
│   │   │       └── TopBar.tsx
│   │   ├── lib/
│   │   │   ├── pipecat-client.ts
│   │   │   ├── api.ts
│   │   │   └── store.ts
│   │   └── hooks/
│   │       ├── useVoiceSession.ts
│   │       └── useMemory.ts
│   └── public/
│
├── deploy/                          # 部署相关
│   ├── docker/
│   │   ├── backend.Dockerfile
│   │   ├── ui.Dockerfile
│   │   ├── vllm-asr.Dockerfile
│   │   └── letta.Dockerfile
│   ├── scripts/
│   │   ├── setup.sh                 # 首次安装
│   │   ├── start.sh                 # 一键启动
│   │   └── update.sh
│   └── systemd/                     # Linux 自启
│       └── fae-v2.service
│
├── docs/
│   ├── ARCHITECTURE.md              # ← 本文档
│   ├── design/
│   │   ├── memory-design.md
│   │   ├── skills-format.md
│   │   └── ui-mockups.md
│   └── api/
│       └── api-reference.md
│
└── examples/
    ├── conversations.jsonl          # 示例对话（用于评测）
    └── skills/                      # 用户自定义 skill 示例
```

---

## 6. 部署方案

### 6.1 硬件要求

| 模式 | GPU | 内存 | 备注 |
|---|---|---|---|
| **完整本地** | RTX 4090 / 5090 (24GB) | 32GB+ | Qwen3-ASR + Qwen3-Max 全本地 |
| **轻量本地** | RTX 3060 (12GB) | 16GB | ASR 本地，LLM 走 DashScope API |
| **开发模式** | 无 GPU | 16GB | 全走 DashScope + Letta Cloud |

### 6.2 Docker Compose 一键启动

```yaml
# docker-compose.yml（核心服务）
services:
  backend:
    build: ./deploy/docker/backend.Dockerfile
    ports: ["8000:8000"]
    depends_on: [letta, vllm-asr]

  ui:
    build: ./deploy/docker/ui.Dockerfile
    ports: ["3000:3000"]
    environment:
      - NEXT_PUBLIC_PIPECAT_URL=http://backend:8000

  letta:
    image: letta/letta:latest
    ports: ["8283:8283"]
    volumes:
      - letta-data:/data

  vllm-asr:
    build: ./deploy/docker/vllm-asr.Dockerfile
    ports: ["8001:8000"]
    # GPU: 1

  qdrant:
    image: qdrant/qdrant:latest
    ports: ["6333:6333"]
    volumes:
      - qdrant-data:/data

  redis:
    image: redis:7-alpine
    ports: ["6379:6379"]
```

### 6.3 启动流程

```bash
git clone https://github.com/huangyuan3h/Fae-v2.git
cd Fae-v2
cp .env.example .env  # 填入 DashScope API Key 等
./deploy/scripts/setup.sh   # 下载模型权重
./deploy/scripts/start.sh   # docker-compose up
open http://localhost:3000  # 浏览器打开
```

---

## 7. 安全与隐私

### 7.1 原则

1. **本地优先**：所有数据存本地，云端只作为可选加速
2. **零信任工具**：每个工具执行需在 UI 上确认（首次）
3. **可审计**：所有 tool call 持久化、可回看
4. **可遗忘**：用户可一键清空所有记忆

### 7.2 工具权限分级

| 级别 | 工具 | 执行方式 |
|---|---|---|
| **Safe** | memory / search | 自动执行 |
| **Caution** | file read / doc search | 自动执行 + 通知 |
| **Sensitive** | file write / shell | 每次人工确认 |
| **Dangerous** | 删文件 / git push | 二次确认 + 5s 倒计时 |

### 7.3 数据流控制

- STT（默认）：浏览器 Web Speech，音频不出 FAE 后端
- LLM：浏览器配置的 OpenAI-compatible 端点，或服务端 Key（主动 Loop）
- TTS：默认本机 `VLLM_TTS_URL`（不经过 DashScope Realtime）
- 记忆：默认 embedded SQLite 或 Compose Letta；archival 可 stub / 真向量

---

## 8. 性能指标（目标）

| 指标 | 目标 |
|---|---|
| 端到端首音频延迟（P50） | < 2.5s |
| 端到端首音频延迟（P95） | < 4s |
| ASR 准确率（英文） | WER < 2% |
| ASR 准确率（中文） | CER < 5% |
| TTS 首包延迟 | < 150ms |
| 工具调用成功率 | > 95% |
| 记忆检索召回率 | > 90% |
| 主动 loop 误触率 | < 1次/天 |

---

## 9. 评测（Evals）

### 9.1 最小评测集（Phase Q.5 · 已落地）

完整 ASR/TTS corpus **未**建设。现行最小集：

```text
evals/
├── agent/
│   ├── skill-trigger.json    # MQ-2 触发正负例
│   └── memory-recall.json    # 名/城/忌口写入后 recall
└── e2e/
    └── ws_voice_round_no_daily.json   # 无 Daily：WS chat + TTS stub
```

Runners（进 CI）：`backend/tests/test_evals_*.py`（`uv run pytest`）。说明见 [`evals/README.md`](../evals/README.md)。

### 9.2 评测维度（目标）

| 维度 | 现行最小断言 |
|---|---|
| **Skills** | fixture 三场景稳定 + 短词不误触 |
| **记忆** | embedded recall 含写入事实 |
| **语音路径** | FakeProvider WS + stub TTS 出 WAV；不依赖 Daily |
| **后置** | WER/MOS、真模型 e2e、主动 loop 相关性 |

---

## 10. 路线图（Roadmap）

### Phase 1: MVP（第 1-2 周）

- [ ] Pipecat + Qwen3-ASR + Qwen3-TTS 跑通对话
- [ ] Letta 集成 + 基础记忆
- [ ] Next.js UI：VoiceOrb + ChatPanel
- [ ] Docker Compose 一键启动

### Phase 2: 记忆深化（第 3-4 周）

- [x] 三层记忆架构（core/recall/archival）
- [x] Episodic memory 事件日志
- [x] 记忆浏览器 UI
- [x] sleeptime 整理任务

### Phase 3: Skills 体系（第 5-6 周）

- [x] Markdown skill 格式规范
- [x] Skill 自动触发 + 优先级调度
- [x] 5+ 内置 skills
- [x] Skill 编辑器（UI）

### Phase 4: 主动 Loop（第 7-8 周）

- [x] APScheduler + Heartbeat（`fae/scheduler/loop.py`）
- [x] 定时任务 UI（`/schedules`）
- [x] Proactive outreach（主动发起话题）
- [x] 通知通道（Web Push / 桌面通知 / WS）

### Phase Q: 质量硬化 — ✅ 首版（见 DEVELOPMENT_PLAN）

- [x] Q.0 人设 · Q.1 语音 · Q.2 Skills · Q.3 记忆 · Q.4 Loop · Q.5 横切

### Phase 5: 上限扩展（按优先级）

- [x] **5.1** 多端 & Telegram（首版：PWA 壳 + long polling；共享 `session_id=default`）
- [x] **5.2** Subagents（`run_subagent` 工具；builtins researcher/coder/reviewer；摘要 → archival）
- [ ] 多用户 / 本地 ASR / Daily 加深 / Slack（按需）
- [ ] **MCP 暂缓**（默认不做）
- [ ] LiveKit：仅在明确需要时再评估（当前未实现）

**Telegram（可选）**：`TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` 启用 `fae/channels/` long-polling；inbound 经 `bridge.handle_inbound_text`（与 `/api/chat` 同 core）；outbound 挂在 `NotificationDelivery.notify`。无 Token 时零影响。默认路径仍是浏览器。

**Subagents**：与 `request_skill` / weather 同属工具环（`fae/agent/subagents/`）。仅当**已激活 skill** 声明 `requires_tools: [run_subagent]` 时挂上工具（避免每轮额外 probe）。子 turn **不**再挂 `run_subagent`。WS 推送 `type: subagent` 供 UI 系统行展示。不是多智能体产品叙事。

---

## 11. 给 Coding Agent 的执行清单

> 当本仓库的 coding agent 接到任务时，按以下顺序执行：

### 第一波：基础设施

1. 创建 `backend/pyproject.toml` + `ui/package.json` 基础结构
2. 写 `docker-compose.yml`，先把 5 个服务跑起来
3. 写 FastAPI 入口 + 健康检查

### 第二波：语音管道

4. 实现 `backend/src/fae/pipecat/services/qwen3_asr.py`
5. 实现 `backend/src/fae/pipecat/services/qwen3_tts.py`
6. 实现 `backend/src/fae/pipecat/bot.py`（最小 pipeline）
7. 集成 Silero VAD + SmartTurn
8. **冒烟测试**：浏览器能听到自己的声音回放

### 第三波：记忆系统

9. 起 Letta server，配置 SQLite 持久化
10. 实现 `letta_client.py` + 三个基础工具
11. 把 memory service 插入 Pipecat pipeline
12. **冒烟测试**：说"我叫 X"，下一轮问"我叫什么"

### 第四波：Skills

13. 设计 skill markdown 加载器
14. 写 3 个内置 skill（daily_check_in / tech_debug / reading）
15. Skill 自动触发逻辑
16. **冒烟测试**：贴 stack trace → 自动加载 tech_debug skill

### 第五波：主动 Loop

17. 实现 Heartbeat + APScheduler
18. Proactive outreach 触发条件
19. 定时任务 UI
20. **冒烟测试**：创建"明早 8 点提醒" → 准点收到

### 第六波：UI 完善

21. shadcn/ui 安装 + 主题
22. VoiceOrb 动效
23. 记忆浏览器
24. Skills / Schedules 管理页

### 第七波：评测 & 文档

25. 写 5+ evals 跑通
26. README + 截图
27. 录 demo 视频

---

## 12. 关键决策日志

| 日期 | 决策 | 备选 | 理由 |
|---|---|---|---|
| 2026-07-12 | STT 选 Qwen3-ASR-1.7B | Canary-Qwen 2.5B | 后者英文专用，不支持中文 |
| 2026-07-12 | TTS 选 Qwen3-TTS | Fish Audio S2 Pro | 商用 Apache 2.0 阵营里最强 |
| 2026-07-12 | 语音框架选 Pipecat | Vercel AI SDK | SDK 7 只接闭源语音模型 |
| 2026-07-12 | 记忆选 Letta | Mem0 / Zep | 上限最高，agent 即状态 |
| 2026-07-12 | 不用 Vercel Eve 做核心 | — | Eve 不擅长实时语音 |
| 2026-07-12 | 借鉴 Eve 的 skill markdown | — | 设计优雅，开发者友好 |
| 2026-07-12 | UI 选 Next.js + shadcn/ui | Electron / Tauri | 上限高，本地 PWA 体验更好 |

---

## 附录 A：技术依赖清单

### 后端（Python）

```toml
[project]
dependencies = [
    "pipecat-ai[daily,openai,silero,sentence]>=0.0.50",
    "letta>=0.50",
    "fastapi>=0.115",
    "uvicorn[standard]>=0.32",
    "dashscope>=1.20",          # Qwen3-TTS Realtime
    "vllm>=0.7",                # 自部署 Qwen3-ASR / LLM
    "apscheduler>=3.10",
    "qdrant-client>=1.12",
    "redis>=5.2",
    "pydantic>=2.10",
    "python-dotenv>=1.0",
]
```

### 前端（TypeScript）

```json
{
  "dependencies": {
    "next": "^15.1.0",
    "react": "^19.0.0",
    "@pipecat-ai/client-react": "^0.0.20",
    "@daily-co/daily-js": "^0.70.0",
    "@radix-ui/react-*": "latest",
    "tailwindcss": "^4.0",
    "framer-motion": "^11",
    "zustand": "^5",
    "@tanstack/react-query": "^5",
    "zod": "^3.24",
    "recharts": "^2.15"
  }
}
```

---

## 附录 B：环境变量

```bash
# .env.example

# DashScope (Qwen3-TTS Realtime + Qwen3 LLM)
DASHSCOPE_API_KEY=sk-xxx

# Letta
LETTA_SERVER_URL=http://letta:8283

# vLLM 自部署（可选）
VLLM_ASR_URL=http://vllm-asr:8000
VLLM_LLM_URL=http://vllm-llm:8000

# 向量库
QDRANT_URL=http://qdrant:6333

# Redis
REDIS_URL=redis://redis:6379

# 第三方 API（可选）
TAVILY_API_KEY=
GITHUB_TOKEN=

# 安全
SECRET_KEY=change-me
```

---

**最后更新**：2026-07-12
**文档维护者**：FAE-v2 Architecture Team
**反馈**：GitHub Issues / PR