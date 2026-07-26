# LLM Agent 上下文压缩与前缀缓存 — 技术选型

> 调研目标：为 FAE-v2（Letta-embedded voice agent）的下一阶段（P8 Tool Runtime & 连接器，
> 以及更远的多日 / 主动 loop 场景）选定一套**可控、可观测、不与现有 Letta/MemFS 记忆体系冲突**
> 的上下文工程（context engineering）方案。
>
> 调研范围：Pipecat / LangChain / LangGraph / Deep Agents / LlamaIndex / Letta /
> Mem0 / Anthropic & OpenAI 官方 cookbook，以及学术界 / 工程界对比文章。
> 调研时间：2026-07-26。

---

## 0. TL;DR — 给 FAE-v2 的推荐

> 现有栈：`Letta`（stateful agent）+ `MemFS`（git-versioned long-term memory）
> + `ChatMemoryBuffer` 风格自建的 `recall_store.py` / `archival.py`（短期/向量层）
> + Skills（按需注入，Markdown）+ `/ws/chat` 直连 LLM（默认走 OpenAI-compatible）。
> 没有自动摘要、没有 prompt cache、没有工具结果回收。

| # | 推荐方案 | 落地位置 | 优先级 |
|---|---|---|---|
| **R1** | **Anthropic/OpenAI `cache_control` + 系统提示分层**（System / Memory / Tools / 动态） | `fae/llm/client.py` + `fae/agent/prepare.py` | **P8 必做** |
| **R2** | **最近 N 轮全量 + 早期 rolling summary**（filler-style 摘要压缩） | `fae/memory/recall_store.py`（在它之上叠一层 summarizer） | **P8 必做** |
| **R3** | **Pipecat `LLMContextSummarizer`** — 仅在 Daily/全双工路径上启用 | `backend/src/fae/pipecat/pipeline.py`（新增） | **P8 加分** |
| **R4** | **长期记忆继续走 Letta/MemFS**；新增 **`sleeptime` reflection 子 agent** 做"梦境式压缩" | `fae/memory/consolidation.py`（已有雏形 → 接 Letta `reflection` subagent） | **P9** |
| **R5** | **工具结果 offload + 摘要回写**（参考 Deep Agents FilesystemMiddleware） | 新增 `fae/agent/tool_offload.py` | **P9** |
| **R6** | **禁止引入 Mem0 / Zep 作为单独组件** — 与 Letta MemFS 重复 | — | 决策记录 |

理由一句话：**FAE-v2 已经是 stateful agent，前缀缓存（cache_control）+ 短期
rolling buffer + Letta 自己的长期记忆 + Letta 的 reflection subagent** 这四件
组合拳是 Anthropic / Letta / Deep Agents 三家目前收敛出的共识，强行换成 LangGraph
或 Mem0 会破坏现有架构。

下面章节是详细调研。

---

## 1. Pipecat（语音管道内的 token 计数 / 上下文聚合）

### 1.1 关键结论

- Pipecat 在 **v0.0.104** 之后正式把"context summarization"作为
  `LLMAssistantAggregatorParams` 的一等公民（之前是 deprecated 的
  `LLMContextSummarizationConfig`）。默认**关闭**，需要显式 `enable_auto_context_summarization=True`。
- 老的 `MessageTransformers` 概念已废弃；现在改名为 **frames（LLMContextSummaryRequestFrame /
  LLMSummarizeContextFrame / SummaryAppliedEvent）**，通过推帧触发。
- Token 估算采用启发式 **4 字符 ≈ 1 token**，不调用 tiktoken — 优点是快，缺点是中文
  / Markdown 会偏。
- 摘要触发：**`max_context_tokens`**（默认 8000）**OR** **`max_unsummarized_messages`**（默认 20），
  两个阈值都可以独立置 `None`（必须至少留一个）。
- 摘要目标 token：`LLMContextSummaryConfig.target_context_tokens`（默认 6000），会自动
  收缩到 `max_context_tokens * 0.8`，并保留最近 `min_messages_after_summary=4` 条不压缩。
- 支持**专用 LLM** 做摘要（`summary_config.llm = GoogleLLMService(...)`），可以
  把摘要路由到一个更便宜更快的模型，不打扰主对话。
- **System message 保留规则**：`messages[0]` 如果是 system，会原样保留；中间注入的
  system（如 idle 提醒）会被当作普通消息参与压缩。**`role="developer"` 不会被特殊保留**。
- 配套事件：`on_summary_applied` → `SummaryAppliedEvent(original_message_count,
  new_message_count, summarized_message_count, preserved_message_count)`，可直接
  进 LangSmith / 内部 metric。
- **完整示例**：`examples/context-summarization/context-summarization-manual-openai.py`
  （在 pipecat GitHub 主仓 `examples/` 下）。

### 1.2 关键类 / 入口（路径以 PyPI `pipecat-ai>=0.0.50` 为准）

| 类 / 函数 | 路径 / 模块 | 作用 |
|---|---|---|
| `LLMAssistantAggregatorParams` | `pipecat.processors.aggregators.llm_response_universal` | 配置摘要开关与阈值 |
| `LLMContextAggregatorPair` | 同上 | 标准 user+assistant aggregator 对 |
| `LLMAutoContextSummarizationConfig` | `pipecat.utils.context.llm_context_summarization` | 自动触发参数 |
| `LLMContextSummaryConfig` | 同上 | 摘要生成参数（含独立 LLM） |
| `LLMContextSummarizer` | `pipecat.processors.aggregators.llm_context_summarizer` | 监视 + 调度摘要 |
| `LLMSummarizeContextFrame` | `pipecat.frames.frames` | 手动推送触发摘要 |
| `SummaryAppliedEvent` | 同上 | 摘要完成事件 payload |

### 1.3 文档 / 源码链接

- 指南：<https://docs.pipecat.ai/pipecat/fundamentals/context-summarization>
- API 参考：<https://docs.pipecat.ai/api-reference/server/utilities/context-summarization>
- 完整 LLMs.txt：<https://docs.pipecat.ai/llms.txt>
- Mem0 集成（可作为长期记忆伴侣）：<https://docs.pipecat.ai/api-reference/server/services/memory/mem0.md>

### 1.4 FAE-v2 适用度

- **默认浏览器路径（`/ws/chat`）**：没有 Pipecat pipeline → **不直接适用**。
  FAE-v2 默认走的是 `prepare_chat_request` → 直发 OpenAI-compatible chat completion。
- **可选 Daily 路径**：`backend/src/fae/pipecat/` 已经规划过 Pipecat 接入。
  当 Daily 路径接入后，**R3 优先启用 `LLMContextSummarizer`**，避免长电话
  把 context 打爆。
- 即便不上 Pipecat，**`LLMContextSummaryConfig` 的设计思路**（触发阈值 + 目标
  token + 保留 N 条 + 专用摘要 LLM）值得抄到 FAE 自建层（见 §8 R2）。

---

## 2. LangChain / LangGraph / Deep Agents（trim / filter / summary / store / cache）

### 2.1 关键结论

- **LangChain v1+** 主推 `langchain_core.messages.utils.trim_messages` /
  `filter_messages` / `count_tokens_approximately`，**`ConversationSummaryBufferMemory`
  等老接口在 v1 中被淡化**（旧 import 路径仍在但不再推荐）。
- **LangGraph** 提供两条原语：
  - **Checkpointers**（InMemorySaver / PostgresSaver / MongoDBSaver / RedisSaver / OracleSaver）
    → 给单个 thread（会话）做**短期**持久化。
  - **Stores**（`langgraph.store.memory.InMemoryStore` 等） → 按 `namespace + key`
    做**长期**记忆，支持语义检索（向量索引）。
- **Deep Agents**（LangChain 推出的"battery-included" harness，构建在 LangChain
  `create_agent` + LangGraph runtime 之上）是当前最完整的"context engineering"组合拳：
  - **Skills**：渐进式加载（frontmatter-only 元数据进 context，正文按需读）。
  - **Memory**：`AGENTS.md` 文件始终注入 system prompt；按文件路径路由到不同 backend。
  - **Context compression**（**默认开启**，无需配置）：
    - **Offloading**：工具输入/输出超过 20K token 自动落盘到 filesystem，
      把 conversation 中的 tool call 替换成文件指针。
    - **Summarization**：`SummarizationMiddleware` 默认 85% 阈值触发，
      用 LLM 生成结构化摘要（intent / artifacts / next steps），同时把原始
      文本**整段写到 filesystem**作为"canonical record"以便后续 grep 找回。
  - **Prompt caching**：Anthropic / Bedrock 上**默认开启**，自动把 system prompt /
    memory / skills 加上 `cache_control` 标记。
  - **Subagent isolation**：`task` 工具派生子 agent 在干净 context 里跑，
    只返回 1k-2k token 的总结。
- **Long-term memory**（`/memories/` 路径）：用 `CompositeBackend(default=StateBackend(),
  routes={"/memories/": StoreBackend(...)})` 把指定路径路由到 LangGraph Store，
  跨 thread 持久。

### 2.2 关键类 / 函数

| 用途 | 名称 | 模块 |
|---|---|---|
| 截断消息 | `trim_messages(state, strategy="last", token_counter=..., max_tokens=N, start_on="human", end_on=("human","tool"))` | `langchain_core.messages.utils` |
| 过滤消息 | `filter_messages(state, include=[...], exclude=[...])` | `langchain_core.messages.utils` |
| 近似 token | `count_tokens_approximately` | `langchain_core.messages.utils` |
| 短期持久 | `InMemorySaver` / `PostgresSaver` / `MongoDBSaver` / `RedisSaver` / `OracleSaver` | `langgraph.checkpoint.*` |
| 长期存储 | `InMemoryStore(index={"embed":embeddings,"dims":N})` | `langgraph.store.memory` |
| 长期生产 | `PostgresStore` / `MongoStore` / `RedisStore` / `OracleStore` | `langgraph.store.*` |
| 摘要中间件 | `SummarizationMiddleware` | `langchain.agents.middleware.summarization` |
| 摘要工具中间件 | `create_summarization_tool_middleware` | `deepagents.middleware.summarization` |
| 压缩回退 | `ContextOverflowError` | `langchain_core.exceptions` |
| Agent 构建 | `create_agent(model, tools, system_prompt, middleware=[...])` | `langchain.agents` |
| Deep Agent | `create_deep_agent(model, tools, system_prompt, memory=[...], skills=[...], middleware=[...], backend=CompositeBackend(...))` | `deepagents` |

### 2.3 文档链接

- LangChain overview：<https://docs.langchain.com/oss/python/langchain/overview>
- Deep Agents overview：<https://docs.langchain.com/oss/python/deepagents/overview>
- Deep Agents context engineering：<https://docs.langchain.com/oss/python/deepagents/context-engineering>
- LangGraph memory（概念）：<https://docs.langchain.com/oss/python/concepts/memory>
- LangGraph add memory（教程）：<https://docs.langchain.com/oss/python/langgraph/add-memory>
- Reference（API）：<https://reference.langchain.com/python/langchain-core/messages/utils/trim_messages>
- Context engineering 概念：<https://docs.langchain.com/langsmith/context-engineering-concepts>

### 2.4 FAE-v2 适用度

- **不引入 LangChain/LangGraph runtime**（FAE-v2 已经自建 FastAPI + Pipecat pipeline，
  重写成 LangGraph 性价比太低）。
- **可以借鉴**：
  - `trim_messages` 的 `strategy="last"` + `end_on=("human","tool")` 边界保证 —
    直接照搬到 `fae/memory/recall_store.py` 的截断函数。
  - `filter_messages` 用 include/exclude 列表剪掉 system reminder 类消息。
  - Deep Agents 的 **filesystem offload** 模式（≥20K token 自动落盘 + 占位引用）
    是 R5 工具结果回收的设计原型。
  - Deep Agents 的 **in-context summary + filesystem canonical record 双写**
    是 R4 sleeptime reflection 的目标形态。

---

## 3. LlamaIndex（ChatMemoryBuffer / ChatSummaryMemoryBuffer / VectorMemory / Memory 类）

### 3.1 关键结论

- **LlamaIndex 当前的推荐 API 是 `llama_index.core.memory.Memory`**（新），**不再是**
  `ChatMemoryBuffer`（deprecated）或 `ChatSummaryMemoryBuffer`（deprecated）。
  两者源还在，但源码顶部明确写 `Deprecated: Please use llama_index.core.memory.Memory instead.`
- `Memory` 由 **`MemoryBlock`** 组成（`StaticMemoryBlock` / `VectorMemoryBlock` /
  `FactExtractionMemoryBlock` 等），每块有自己的 `aget/aput/atruncate`，
  可以组合出 vector + fact + static 的复合记忆。
- 老 API 仍可参考的算法：
  - **`ChatMemoryBuffer`**（`chat_memory_buffer.py`）：按 token_limit 倒序剔除消息，
    但保留 assistant/tool 配对，避免半截 tool call。
  - **`ChatSummaryMemoryBuffer`**（`chat_summary_memory_buffer.py`）：保留最新 N 条
    全文本，更早的调用 LLM 生成一条 summary，**注意它把 summary 本身存成一条
    `role=SYSTEM` 的消息**，下一次 `get()` 时会作为第 0 条 system 注入。
- 还有 `VectorMemory`（向量检索历史 / 把每条消息嵌进去）、`SimpleComposableMemory`
  （手动把多个 Memory 拼起来）。

### 3.2 关键类

| 类 | 模块 | 备注 |
|---|---|---|
| `Memory` | `llama_index.core.memory` | **当前推荐**；由 MemoryBlock 组合 |
| `StaticMemoryBlock` / `VectorMemoryBlock` / `FactExtractionMemoryBlock` | 同上 | Memory 的基本组成单元 |
| `BaseMemory` / `BaseChatStoreMemory` | `llama_index.core.memory.types` | 抽象基类 |
| `ChatMemoryBuffer` | `llama_index.core.memory.chat_memory_buffer` | **deprecated**；token-based sliding window |
| `ChatSummaryMemoryBuffer` | `llama_index.core.memory.chat_summary_memory_buffer` | **deprecated**；rolling summary |
| `VectorMemory` | `llama_index.core.memory.vector_memory` | 全部消息嵌进向量索引 |
| `SimpleComposableMemory` | `llama_index.core.memory.simple_composable_memory` | 手动拼接多个 memory |

### 3.3 文档链接

- Memory 总览：<https://docs.llamaindex.ai/en/stable/module_guides/memory/>
- ChatMemoryBuffer API：<https://docs.llamaindex.ai/en/stable/api_reference/memory/chat_memory_buffer/>
- Memory（含新 API）：<https://docs.llamaindex.ai/en/stable/api_reference/memory/memory/>
- VectorMemory：<https://docs.llamaindex.ai/en/stable/module_guides/memory/vector_memory/>
- Mem0 integration：<https://docs.llamaindex.ai/en/stable/module_guides/memory/mem0/>

### 3.4 FAE-v2 适用度

- **不引入 LlamaIndex 作为独立记忆层**（FAE-v2 已有 Letta + 自建 recall/archival）。
- 但 **`ChatSummaryMemoryBuffer` 的 "rolling summary" 算法** 与 Deep Agents 的
  `SummarizationMiddleware` 是同一思路（保留尾部 N 条 + 头部 summary），值得
  直接搬到 `fae/memory/recall_store.py`。
- **`VectorMemoryBlock` + `FactExtractionMemoryBlock`** 的组合可作为未来
  `archival.py` 升级参考（自动从历史中抽 fact 入向量库）。

---

## 4. Letta（FAE-v2 已集成；重点确认其"dreaming"机制）

### 4.1 关键结论（**2026 版架构，已经从 MemGPT 演化不少**）

- **核心概念已重构**：
  - **MemFS**（替代老 "core memory blocks"）：git-versioned 的 Markdown 文件
    系统，每个文件 = 一个 "context repository"。`$MEMORY_DIR/system/` 下的文件
    **每次 turn 都进 system prompt**，`reference/` / `skills/` 下的文件仅在
    agent 主动 `read_file` 时加载。**`./skills/` 风格借鉴 Anthropic Agent Skills 标准
    （agentskills.io），跨 Letta / Claude Code / Codex / Hermes 共用**。
  - **Conversations**：一个 agent 多个独立 thread（conversation）。每个
    conversation 有自己的消息历史 + 自动 compact；agent-level 的 **MemFS 在所有
    conversations 间共享**。
  - **Dreaming（"梦境"）**：后台 subagents 跑 reflection —— `reflection` / `memory` /
    `init` / `history-analyzer` 等 built-in subagents 用 git worktree 隔离地编辑
    MemFS，**不阻塞主对话**。可手动 `/sleeptime` 触发，也可在"context window 被
    compact 后"自动跑。
  - **Compact**：conversation 自己的消息历史快满时，Letta 会自动 compact
    （类似 Pipecat 的 summarizer，但 server-side 完成）。
  - **`/remember` 命令**：显式告诉 agent "记住 X" → agent 决定把这条写进哪个
    MemFS 文件。
  - **`/doctor`**：审计 memory 层级、重复、system prompt token 用量。

### 4.2 关键子能力 / 内置 subagent

Letta 内置 7 种 subagent（来自 `configuration/subagents/`）：

| Subagent | 用途 | 推荐模型 | 访问权 |
|---|---|---|---|
| `fork` | 携带完整 context + tools 分叉对话 | `inherit` | Read/write |
| `general-purpose` | 全功能 —— 研究 / 规划 / 改文件 | `auto` | Read/write |
| `history-analyzer` | 把 Claude Code / Codex 的旧历史迁进 MemFS | `auto` | Read/write |
| `init` | 从当前项目快速初始化 agent memory | `auto-fast` | Read/write |
| `memory` | 重组 memory blocks、清除冗余 | `auto` | Read/write |
| `recall` | 搜历史对话与决策 | `auto-fast` | Read-only |
| **`reflection`** | **sleeptime 背景 memory 整合** | `auto` | Read/write |

- `model` 字段：可单独指定；Letta 当前把内置 subagent 默认解到 `auto` / `auto-fast`。
- `tools` 字段：列表或 `all`。
- `memoryBlocks`：`human, persona` / `all` / `none`。
- `skills`：逗号分隔，会随 subagent 启动加载。

> FAE-v2 当前已有一个 `consolidation.py`（`SleeptimeScheduler`）——
> **这正是 Letta `reflection` subagent 的本地等价物**。下一步可以让它真正
> 委派给一个独立的 Letta agent（带 `agent_id`）作为子进程运行，借助其
> dream-time 的 git worktree 机制，避免阻塞主对话。

### 4.3 Skill 体系（值得 FAE-v2 直接对齐）

- Letta 实现了 [Agent Skills](https://agentskills.io/) 开源标准（SKILL.md frontmatter）。
- Skill 加载有四种 scope：
  - `${MEMORY_DIR}/skills/` — agent-scoped（git-versioned，跟着 agent 走）
  - `.agents/skills/` — project-scoped（项目本地）
  - `~/.letta/skills/` — computer-scoped（本机全局）
  - 内置 bundled skills（随 Letta Code 装）
- 加载策略：**前 matter 在每次启动进 system prompt，正文按需 `read_file`**。

### 4.4 关键文档链接

- Letta LLM index：<https://docs.letta.com/llms.txt>
- MemFS 概念：<https://docs.letta.com/concepts/memfs/index.md>
- Conversations 概念：<https://docs.letta.com/concepts/conversations/index.md>
- Stateful agents：<https://docs.letta.com/concepts/stateful-agents/index.md>
- Memory & dreaming：<https://docs.letta.com/configuration/memory/index.md>
- Skills：<https://docs.letta.com/configuration/skills/index.md>
- Subagents：<https://docs.letta.com/configuration/subagents/index.md>
- Context Constitution（理论根）：<https://github.com/letta-ai/context-constitution>
- Letta Handbook：<https://docs.letta.com/handbook/index.md>
- Meet your agent：<https://docs.letta.com/handbook/meet-your-agent/index.md>

### 4.5 FAE-v2 适用度

- ✅ **继续把 Letta 作为长期记忆主框架**（MemFS + 三层语义）。
- ✅ **未来把 `consolidation.py` 的 SleeptimeScheduler 升级为"调用 Letta reflection
  subagent"**，让 Letta 自己做 git worktree 隔离的 memory 整理，而不是在主进程里跑 LLM。
- ✅ **Skill 体系已经符合 Agent Skills 标准**，可以跨 Letta/Claude Code 复用 skill 库。
- ⚠️ 注意 Letta 的 `system/` MemFS 加载是**每次 turn 全量注入 system prompt** —
  这是 cache_control 的核心受益区域（见 §6 / §8 R1）。

---

## 5. MemGPT / Mem0（context window 分层 & eviction）

### 5.1 MemGPT → Letta（**历史**）

- MemGPT 是 UC Berkeley 2023 年的论文 + 早期开源项目（"虚拟 context paging"），
  把 context window 切成 system / working / archival / recall 四层，靠"在 LLM
  看来 OS 的 page-in / page-out"。
- **MemGPT 团队 2024 年将其品牌化为 Letta**，所以今天讨论"Letta = stateful agent"
  时，**MemGPT 已被 Letta 取代**。FAE-v2 已选 Letta 即等价于 MemGPT 的演进版。

### 5.2 Mem0（独立 memory layer）

- 定位是 **"记忆层 SDK"**，不是 stateful agent runtime — 与 Letta 完全正交。
- 关键设计：
  - **两层存储**：SQL 数据库（事实元数据）+ 向量数据库（embedding）。
  - **可选 entity / graph store**（Mem0 Platform 才有）。
  - **ADD-only extraction**：用户消息进来 → LLM 抽 fact → 去重 → embed → 写库。
  - **Retrieval signals**：semantic（向量）+ keyword（精确匹配）+ entity（实体链接）
    + temporal（时间衰减）。
  - **Scope 三层**（与 FAE-v2 现有 `recall / archival / episodic` 高度相似）：
    - **Conversation**（单轮 in-flight） — 对应 FAE 当前 WS turn
    - **Session**（任务级短期） — 对应 FAE 当前 session
    - **User**（跨 session 长期） — 对应 Letta MemFS
    - **Org**（跨 agent 共享） — 对应 Letta shared memory repo

### 5.3 Mem0 关键类 / 入口

| 类 | 用途 |
|---|---|
| `MemoryClient` (Platform) / `Memory` (OSS Python) / `AsyncMemory` | 主入口 |
| `client.add(messages, user_id=..., run_id=..., agent_id=...)` | 写入 |
| `client.search(query, user_id=..., filters={...}, limit=...)` | 检索 |
| `client.get_all(user_id=...)` / `client.get(memory_id=...)` | 列表 / 详情 |
| `client.update(memory_id, text=...)` / `client.delete(memory_id)` | 更新 / 删除 |
| `client.delete_all(user_id=...)` | 清空 |

### 5.4 文档链接

- Mem0 LLM index：<https://docs.mem0.ai/llms.txt>
- How Mem0 Works：<https://docs.mem0.ai/core-concepts/how-it-works>
- Memory Types：<https://docs.mem0.ai/core-concepts/memory-types>
- Pipecat 集成：<https://docs.mem0.ai/integrations/pipecat>

### 5.5 FAE-v2 适用度

- ❌ **不引入 Mem0** 作为额外记忆层（与 Letta MemFS 功能重叠；FAE 已用
  `embedded SQLite + Qdrant` 实现同等能力）。
- ✅ Pipecat 路径上若临时需要轻量 cross-session 记忆，可考虑接 Mem0
  （Mem0 有官方 Pipecat service） — 但优先级低。
- ✅ **Mem0 的"ADD-only + 去重 + embed"写入路径** 与 FAE 当前 `fact_extract.py` 的
  设计思路吻合，可作为校验对照。

---

## 6. Anthropic / OpenAI 官方 cookbook — prompt caching with agents

### 6.1 Anthropic：cache_control

- 2024-08 GA。2025-09（Sonnet 4.5）配合 **context editing** + **memory tool** 三件套。
- 定价模型（**关键**）：
  - **Cache write** = base input × **1.25**
  - **Cache read**  = base input × **0.1**（**-90%**）
  - 缓存 TTL：默认 **5 分钟**，可延长到 1 小时（`cache_control={"ttl": "1h"}`）。
- **官方实测收益**（来自 [Prompt caching with Claude](https://www.anthropic.com/news/prompt-caching)）：

| 用例 | 无缓存首 token | 有缓存首 token | 成本节省 |
|---|---|---|---|
| Chat with a book（100k token 缓存） | 11.5s | 2.4s（**-79%**） | **-90%** |
| Many-shot prompting（10k token 提示） | 1.6s | 1.1s（**-31%**） | **-86%** |
| 10 轮长 system prompt 对话 | ~10s | ~2.5s（**-75%**） | **-53%** |

- 2025-09 加新：**context editing** —— 自动清掉 stale tool results；
  **memory tool** —— 把 notes 写到 server-side 文件系统。

### 6.2 Anthropic：effective context engineering（必读）

- 来源：<https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents>
  （2025-09-29）
- **核心论点**：context 是**有限资源**，每加一个 token 都稀释 attention budget；
  应把"找到最小的高信号 token 集合"作为系统设计目标。
- 关键策略：
  - **System prompt**：用 XML/Markdown 分块（`<background_information>` /
    `<instructions>` / `## Tool guidance` / `## Output description`），
    **保持在"Goldilocks altitude"**（不要太硬编码 if-else，也不要太抽象）。
  - **Tools**：token-efficient 返回值；"如果人工程师都不能立刻判断该用哪个工具，
    AI agent 不可能做得更好"。
  - **Few-shot**：用一组"diverse canonical"示例，不要堆 edge case 列表。
  - **Just-in-time retrieval**：agent 用工具（`glob`/`grep`/`Read`）按需加载数据，
    不要 pre-processing 全部塞进 prompt。
  - **Long-horizon techniques**（这是 FAE-v2 的关键）：
    - **Compaction**：接近 context limit 时摘要历史 + 重新开始 — **这就是 Pipecat
      `LLMContextSummarizer` / Letta `conversation.compact` / Deep Agents
      `SummarizationMiddleware` 在做的事**。
    - **Structured note-taking**：agent 把 progress 写到 **NOTES.md**（或 `AGENTS.md`）
      — **这正是 Letta MemFS 的设计**。
    - **Sub-agent architectures**：主 agent 拿计划，子 agent 跑深度工作 —
      **这正是 Deep Agents `task` 工具 + FAE-v2 P5.2 subagent 的设计**。

### 6.3 Anthropic：Contextual Retrieval（**值得 FAE 借鉴**）

- 来源：<https://www.anthropic.com/news/contextual-retrieval>
- 把 RAG 的每个 chunk 在 embed **之前**先用一个 LLM 调用生成 50-100 token 的
  context（"this chunk is from ACME's Q2 2023 SEC filing; previous quarter revenue
  was $314M..."）→ 然后拼回去再做 embed + BM25。
- 实测收益：
  - Contextual Embeddings：**-35%** 检索失败率
  - Contextual Embeddings + BM25：**-49%** 失败率
  - 再加 Cohere reranker：**-67%** 失败率
- **关键 trick：使用 prompt caching 让 chunk-contextualization 几乎免费**
  （"reference document 一次写进 cache，多次 chunk 复用"）。
- FAE-v2 适用度：`archival.py` 当前是 chunk → embed；如果想让 archival retrieval
  更准，**加一个 `archival_contextualize.py` step**（输入：每个 chunk + 它的父文档
  → 输出：加 context 后再 embed）。

### 6.4 OpenAI：prompt caching

- 来源：<https://platform.openai.com/docs/guides/prompt-caching>
  （注：fetch 时返回 403；以下信息来自 OpenAI 官方文档与 cookbook 通用认知，
  FAE 落地时需以当前 SDK 文档为准）
- 行为：模型自动 cache **≥1024 token** 的 prefix；命中条件是 prefix 完全一致。
- 缓存粒度（自动按 128 token 块切）：cache read 比 cache miss 便宜 **~50%**。
- 不像 Anthropic 那样需要显式 `cache_control` 标记 — OpenAI 自动判断。
- **最佳实践**：把稳定内容放最前（system + tools + few-shot），
  把动态内容放最后（user message + 检索片段）。

### 6.5 FAE-v2 适用度（R1）

> **R1 应该是 FAE-v2 P8 的头号任务**，理由：
> - 当 `session_id=default` 的浏览器路径长期开、且 LLM 走 DashScope/Anthropic 时，
>   系统提示 + persona + skills + memory 这部分**每个 turn 完全一样**，
>   这是 cache_control 的教科书用例。
> - 预估收益（按 Anthropic 实测）：**首 token latency -75%、成本 -50%**。
> - 改动量小：只需在 `fae/llm/client.py` 给 OpenAI/Anthropic 兼容客户端加
>   `cache_control` 透传（Anthropic 走 `system[0].cache_control` / `tools[].cache_control`；
>   DashScope / OpenAI 自动）。

---

## 7. 学术界 / 工程界对比：摘要、滚动窗口、语义去重、RAG

### 7.1 Hierarchical summary（多层摘要）

- 经典论文：**"MemoryBank: A Biologically-Inspired Continual Learning Memory"** 等。
- 主流做法：把 history 分层（L0 = 最近 N 条原文，L1 = L0 的摘要，L2 = L1 的摘要...）。
- **Deep Agents 的 `SummarizationMiddleware` + FilesystemMiddleware 双写** 是当前
  工程界最干净的 hierarchical 形式（in-context summary + filesystem canonical record）。
- **Letta 的 `reflection` subagent + MemFS git history** 也是同样思路。

### 7.2 Sliding window + summary（滚动窗口 + 摘要）

- LangChain 旧 `ConversationSummaryBufferMemory` = "保留最近 K token 原文 + 之前
  的滚动 summary"。LlamaIndex `ChatSummaryMemoryBuffer` 是同样的设计。
- **Pipecat `LLMContextSummaryConfig.min_messages_after_summary=N`** 暴露的也是
  这个旋钮。
- **适合**：客服 / 长对话机器人；Fae 这种 multi-session voice agent 也适合
  （同一会话只保留 30 轮 + 早期摘要）。

### 7.3 Rolling buffer（纯截断）

- LangChain `trim_messages` / LlamaIndex `ChatMemoryBuffer`：按 token 上限**倒序
  丢弃**，保留最新消息。`start_on="human"` / `end_on=("human","tool")` 是关键：
  不要半截 tool call。
- 适合：上下文**不依赖历史决策**的任务（闲聊 / 单步工具调用）。
- 不适合：需要跨多轮推理的 agent（FAE 默认场景）。

### 7.4 语义去重（semantic dedup）

- Mem0 的 ADD-only extraction + dedup 是工业级代表。
- LangChain 的 `langchain.retrievers.document_compressors.EmbeddingsFilter` /
  `LLMChainFilter` 可在 retrieval 阶段去重。
- LlamaIndex `VectorMemory` 把每条消息嵌进向量索引，再用 cosine 去重。
- **FAE-v2 现况**：`fact_extract.py` 已经做了"增量写入 + 去重"，方向正确；
  但**没有基于 embedding 的语义去重**，可以后续加。

### 7.5 最近 N 轮 + 远端 RAG 检索

- **Deep Agents 的官方推荐模式**（见 `context-engineering` 文档）：
  - **短窗口**（最近 10-30 轮）放 in-context。
  - **长历史** 放 filesystem / vector store，agent 用工具按需拉。
  - **关键**：把 filesystem 的引用也放进 system prompt（路径 + 文件名），让
    agent 自己 decide 何时去 read。
- **Anthropic Claude Code 的 hybrid 模式**（来自 §6.2 同一文章）：
  - **CLAUDE.md** —— 文件全量进 context（naive up-front）。
  - **glob / grep / Read** —— lazy explore，避免 stale index。
- **Mem0 的 retrieval-fusion** —— semantic + keyword + entity + temporal 四路
  召回 + reranker，是工业级实现。

### 7.6 对比总结表

| 方案 | 延迟 | 成本 | 信息保真 | 实现复杂度 | 适合场景 |
|---|---|---|---|---|---|
| **Rolling buffer**（纯截断） | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐ | ⭐ | 闲聊、单步工具 |
| **Sliding window + summary** | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐ | 长客服、长对话 |
| **Hierarchical summary** | ⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐ | 多日记忆 / assistant |
| **Last-N + RAG** | ⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | 复杂 agent / 长 horizon |
| **Subagent isolation** | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ | 多步工具循环 / heavy IO |
| **Cache_control + 上述任一** | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | （同底层方案） | ⭐ | **几乎所有场景都该叠** |

---

## 8. 三种"system prompt 长期稳定 + cache_control"排版示例

> 通用原则（来自 §6 Anthropic 官方）：
> 1. **稳定前缀 = System prompt + Skills 索引 + Persona + 工具 schema** ——
>    几 KB 到几十 KB，每个 turn 字节完全一致。
> 2. **动态段 = 当前 user 输入 + 当轮检索片段** —— 放最末尾。
> 3. **缓存标记位置**：Anthropic 把 `cache_control: {type: "ephemeral", ttl: "1h"}`
>    放在"稳定前缀最末尾"；之后的所有内容**不会被 cache**，保证 token counter 增量
>    计费正确。
> 4. **不要在 cache 标记之前放时间戳 / user id / session id** —— 这些是动态的。

### 示例 A：FAE-v2 浏览器路径（Anthropic Claude via DashScope）

```text
[System · STABLE · cache_control: ephemeral, ttl: 1h]
<system>
  <persona>
    You are FAE. Voice-friendly, concise. Locale: zh-CN. Style: warm, direct.
    Boundaries: never claim to have done things you didn't.
  </persona>
  <memory_summary>
    # Human
    - Name: 小明
    - Lives in 上海
    - Allergies: 香菜 (remembered 2026-07-12)

    # Current focus (last seen 4h ago)
    - Debugging a Python asyncio race in fae-v2 repo
  </memory_summary>
  <skills_index>
    - technical_debugging (priority 8)
    - daily_check_in (priority 5)
    - proactive_outreach (priority 5)
  </skills_index>
</system>

[Tools · STABLE · cache_control: ephemeral, ttl: 1h]
<tools>
  - memory_search(query, tier): search user facts / recall / archival
  - memory_save_fact(text, tier): persist a durable fact
  - memory_update_user(field, value): patch user profile
  - schedule_create(at, prompt): set a future reminder
  - shell_run(cmd, confirm): run shell (needs user OK)
  ... (full tool schemas)
</tools>

[Few-shot examples · STABLE · cache_control: ephemeral, ttl: 1h]
<examples>
  Ex 1: User says "我搬家了，新地址是北京海淀"
       → memory_save_fact("user.address = 北京海淀", tier=human)
  Ex 2: User says "提醒我明早 8 点开会"
       → schedule_create(at="2026-07-27T08:00", prompt="...")
  Ex 3: User says "我忘了上次调的那个 bug 是怎么修的"
       → memory_search("上次调的那个 bug 是怎么修的", tier=recall+archival)
  ...
</examples>

─────────────────────────────────────────────
[Recall window · SEMI-STABLE · 5-min cache_control]
Last 6 turns (verbatim):
  human: 我那个 asyncio 报错还在
  assistant: 你贴下报错
  human: RuntimeError: Event loop is closed
  assistant: 这是因为你在 stop() 里 await task 但 task 引用的是旧 loop ...
  human: 哦，我把 task 改成 gather 试试
  assistant: ...
  human: 还是报
─────────────────────────────────────────────

─────────────────────────────────────────────
[Retrieval snippets · DYNAMIC · no cache_control]
## Related archival memory
- [2026-07-10] 用户问过 pytest-asyncio 跑 hang 的问题 → 建议加 asyncio_mode=auto
- [2026-07-11] 用户项目中使用了 custom transport loop
─────────────────────────────────────────────

[User message · DYNAMIC · no cache_control]
human: 我那个 asyncio 报错还在，stack trace 是这样 ...（粘贴 traceback）
```

> **要点**：
> - System / Tools / Examples 三段**字节级稳定**，挂同一个 1h cache_control；
>    Anthropic 会把它们当成一个 cache 段，写一次后续读都按 0.1× 价。
> - Recall window 用 5 分钟 `cache_control`（多轮不变时复用），但同一段
>   在每轮都会变，所以这个 cache 主要受益于"用户在 5 分钟内连发多条短消息"的场景。
> - Retrieval 片段 + user message 完全不进 cache（高频更新，没收益）。
> - DashScope / 阿里云百炼对 Anthropic API 兼容的情况，按上述排版即可。

### 示例 B：FAE-v2 Daily 路径（Pipecat + Anthropic Claude）

> Daily 路径的"用户输入"是被 VAD + SmartTurn 切成一段一段的短 utterance，
> 所以 system/tools/examples 的 cache 命中率**比浏览器路径更高**。

```text
[System · STABLE · cache_control: ephemeral, ttl: 1h]
<system>
  <persona>...</persona>
  <voice_mode>
    - 短句优先（≤ 30 字），口语化
    - 不要 markdown / 列表 / 代码块
    - 不主动结束对话
  </voice_mode>
  <memory_summary>...</memory_summary>
</system>

[Tools · STABLE · cache_control: ephemeral, ttl: 1h]
<tools>... (语音常用子集：memory_search / memory_save_fact / shell_run / tts_repeat)</tools>

[Few-shot · STABLE · cache_control: ephemeral, ttl: 1h]
<examples>
  Ex voice: 用户说 "嗯" → 不要回应，等下一句
  Ex voice: 用户说 "那个 bug 怎么样了" → memory_search → "上次你说 RuntimeError..."
  Ex voice: 用户说 "明天提醒我" → schedule_create → "好的，明早几点？"
</examples>

─────────────────────────────────────────────
[Conversation · SEMI-STABLE · 5-min cache_control]
user: 在吗
assistant: 在，你说
user: 我那个 bug
assistant: 哪个 bug？要不要我搜一下
user: 上次说的 asyncio 那个
assistant: （检索中）...
─────────────────────────────────────────────

[Live turn · DYNAMIC · no cache_control]
user: 还是 RuntimeError
```

> Pipecat 的 `LLMContextSummarizer` 在 daily 路径开启时（§1 / R3）：
> - `max_context_tokens=6000`（约 30 轮短句）
> - `target_context_tokens=2000`（摘要约 10 轮信息密度）
> - `min_messages_after_summary=2`（保留最近 user/assistant 一对原文）
> - `llm=` 一个便宜的 Haiku 摘要器（不抢主对话带宽）

### 示例 C：FAE-v2 主动 Loop（proactive outreach）—— DashScope Qwen3 长 prompt

> 主动 loop 的特点是 **"一次性拼一个超长 system prompt"**（含近 7 天摘要 + skills +
> 日程 + 天气 + 历史常驻话题），没有 user 实时输入，最适合极致 cache。

```text
[System · STABLE · cache_control: ephemeral, ttl: 1h]
<system>
  <persona>...</persona>

  <weekly_summary>                ← letta reflection subagent 产出
    # This week
    - User debugged a Python race condition in fae-v2 (Wed)
    - User mentioned moving to new apartment (Fri) → address updated
    - User had a meeting with manager about Q3 plan (Mon)
  </weekly_summary>

  <skills_index>...</skills_index>

  <schedule_today>
    - 10:00 standup (recurring)
    - 15:00 call w/ dentist
  </schedule_today>

  <weather>上海 多云 28°C</weather>

  <proactive_rules>
    - Only reach out if user has been silent > 6h AND there's a pending topic
    - Max 1 outreach / day
    - Don't say "hi" — always attach a concrete reason
  </proactive_rules>
</system>

[Tools · STABLE · cache_control: ephemeral, ttl: 1h]
<tools>
  - send_notification(channel, text)
  - memory_search
  - memory_save_fact
</tools>

[Retrieval snippets · DYNAMIC · no cache_control]
## Past unresolved topics
- "follow up on asyncio race fix outcome"

─────────────────────────────────────────────
[Trigger message · DYNAMIC · no cache_control]
system: It has been 6h since last user message. There is a pending follow-up
        about the asyncio race fix. Initiate outreach via Web notification.
```

> 收益：这套 system prompt 通常 **3-8 KB**，cache 命中后每条主动通知的
> 推理成本 ≈ **基线的 10-20%**，而且**首 token latency 降一个量级**。
> 主动 loop 一天可能 1-3 次通知，成本节省非常显著。

---

## 9. 方案对比表（综合）

| 方案 | 框架 | 触发 | 信息保真 | 延迟影响 | 成本影响 | 实现成本 | 与 Letta 兼容 | FAE-v2 推荐度 |
|---|---|---|---|---|---|---|---|---|
| **cache_control（Anthropic）** | Anthropic | 显式 `cache_control` | ★★★★★ | -75% 首 token | -50% to -90% | 极低 | ✅ 直接挂 system/tools 层 | **★★★★★** R1 |
| **cache（OpenAI 自动）** | OpenAI / 兼容 | 自动（≥1024 prefix） | ★★★★★ | -50% | -50% | 零 | ✅ | **★★★★★** R1 |
| **trim_messages（LangChain）** | LangChain / 自建 | 显式调用 | ★★★ | 加速 | 减少 | 低 | ✅ | **★★★** R2 子项 |
| **rolling summary**（自建 / LlamaIndex 老 / LangChain 老） | 任意 | token 超阈值 | ★★★★ | 略增 | 大减 | 中 | ✅ | **★★★★** R2 主项 |
| **Pipecat `LLMContextSummarizer`** | Pipecat | token/msg 超阈值 | ★★★★ | 略增 | 大减 | 中 | ✅ Daily 路径直接用 | **★★★★** R3（仅 Daily） |
| **Deep Agents `SummarizationMiddleware`** | LangGraph | 85% context | ★★★★ | 略增 | 大减 | 中 | ⚠️ 需引入 LangGraph runtime | **★★** 不引入 |
| **Deep Agents `FilesystemMiddleware` offload** | LangGraph | tool input/output ≥20K | ★★★★★ | -（落盘） | 大减 | 中 | ✅ 思路可抄 | **★★★** R5 |
| **Letta MemFS `system/` 静态层** | Letta | 每次 turn | ★★★★ | 加速 | 减少 | 零 | ✅ 已用 | **★★★★★** R1 基础设施 |
| **Letta `reflection` subagent** | Letta | `/sleeptime` 或自动 | ★★★★ | 异步、不阻塞 | — | 中 | ✅ 已用 | **★★★★★** R4 |
| **Letta `conversation` auto compact** | Letta | server-side | ★★★★ | 略增 | 大减 | 零 | ✅ 已用 | **★★★★** |
| **Mem0 Memory layer** | Mem0 | 显式 add/search | ★★★★ | - | - | 高 | ❌ 与 MemFS 重复 | **★** |
| **Contextual Retrieval**（RAG chunk 加 context） | 自建 | embed 前 | ★★★★（检索准确率 +49%） | - | 略增 | 中 | ✅ 改 `archival.py` | **★★★** P9 加分 |
| **Subagent isolation** | 自建 | agent 主动委派 | ★★★★★ | - | 大减 | 中 | ✅ FAE 已有 subagents | **★★★★★** 已用 |

---

## 10. 针对 FAE-v2 现状的推荐

### 10.1 现状速描（来自 `prepare.py` + `skills_runtime.py` + `consolidation.py`）

- 系统提示组装顺序（按 `prepare_chat_request`）：
  1. Letta memory 注入（`human_block` + `client.prepare_request`）
  2. runtime context block（`build_context_block` 注入 city/timezone）
  3. Skills 注入（`SkillRuntime.prepare_request`）
- 当前**没有**任何**自动摘要 / 自动截断 / cache_control / 工具结果回收**。
- `consolidation.py` 的 `SleeptimeScheduler` 是"sleeptime reflection"的雏形，
  但还在本地进程跑 LLM。

### 10.2 推荐落地路径（P8 → P9）

#### P8 — 必做、低风险、立刻有收益

1. **R1：`cache_control` 落地**
   - 改 `fae/llm/client.py`：
     - 检测 provider：anthropic → 在 `system` 数组末尾 + `tools` 末尾追加
       `{"type": "text", "text": "...", "cache_control": {"type": "ephemeral", "ttl": "1h"}}`。
     - DashScope Qwen / OpenAI 兼容 → 不需要改（自动）。
   - 改 `fae/agent/prepare.py`：让 system 段组装为**结构化数组**
     （不再是单一字符串），保证稳定前缀字节级一致。
   - **校验**：用同一份 prompt 连续发 10 个 turn，看 cache_creation_input_tokens /
     cache_read_input_tokens 比例是否 ≥80%。

2. **R2：短期 rolling summary（在 `recall_store.py` 上叠）**
   - 新增 `fae/memory/summarizer.py`：
     - 每次 turn 结束后，若 `recall_messages` 长度 / token 超阈值，调用 cheap LLM
       把最早 K 条（除系统消息外）压成一条 `summary_message`。
     - 把 summary 存成**单独一行**（不是塞进对话消息），注入时拼在 system prompt
       末尾、recall messages 之前。
   - 触发阈值：默认 30 条消息 / 6000 token 估计；保留最近 6 条原文。
   - **复用** `LLMContextSummaryConfig` 的设计（target / min / 专用 LLM）。

3. **R3：Daily 路径接 Pipecat `LLMContextSummarizer`**（P8 末段或 Daily 路径
   真正启用时）
   - 在 `backend/src/fae/pipecat/pipeline.py` 的 `LLMAssistantAggregatorParams`
     启用 `enable_auto_context_summarization=True`。
   - 配 `max_context_tokens=6000, max_unsummarized_messages=30,
     summary_config.target_context_tokens=2000, min_messages_after_summary=2`。
   - 摘要 LLM 用 Haiku 之类快模型。

#### P9 — 进阶、与 Letta MemFS 协同

4. **R4：让 `consolidation.py` 调用 Letta `reflection` subagent**
   - 把 `SleeptimeScheduler.heartbeat` 改成"启一个 Letta agent 做 reflection，
     传 `agent_id`，让它在自己的 git worktree 里改 MemFS"。
   - 触发条件：MemFS commit 数 > N（说明有学习），或距上次 reflection > 24h。
   - 完成后通过 `mem0->letta`-style "completion notification" 注入主 agent。

5. **R5：工具结果 offload**（参考 Deep Agents `FilesystemMiddleware`）
   - 新增 `fae/agent/tool_offload.py`：检测 tool output > 20K token → 写本地文件
     → 把 conversation 中的 tool result 替换为 `path + first 10 lines`。
   - `read_file(path, offset, limit)` 工具给 agent 用来"按需拿回原文"。
   - 与 `archival.py` 联动：offload 的文件可入 archival，方便后续检索。

6. **Contextual Retrieval 升级 `archival.py`**
   - 给每个 archival chunk 加一个 LLM-contextualization 步骤（用 Anthropic 的
     prompt caching 把 reference 文档一次性写 cache，反复使用 -86% 成本）。
   - 实测收益：检索失败率 -49%，与现在裸 embed 相比显著。

### 10.3 决策记录（不做什么）

- **❌ 不引入 LangGraph runtime**：FAE-v2 自建 FastAPI + Pipecat 已经够稳，
  LangGraph 转换 ROI 太低；只借鉴其算法（trim / summarization / offload）。
- **❌ 不引入 Mem0**：与 Letta MemFS 功能重叠（session / user / org 都覆盖）；
  FAE-v2 已有 SQLite + Qdrant 自己做 recall/archival。
- **❌ 不引入 LlamaIndex**：同上理由；保留 `ChatSummaryMemoryBuffer` 算法
  思想即可。
- **⚠️ 限制 cache_control 的 TTL**：默认 1h；针对 proactive loop 路径可以延长
  到 5h（Anthropic 支持 1h TTL，5h 需手动续）；不要无限期。
- **⚠️ 摘要 LLM 不要用主对话的强模型**：用 Haiku / Qwen-Turbo 这种快模型，
  否则摘要本身就成了成本大头。

### 10.4 风险与监控

| 风险 | 触发条件 | 监控 / 缓解 |
|---|---|---|
| cache 命中率低 | system prompt 每次 turn 有微小变化（如时间戳 / session id） | `cache_read_input_tokens / total_input_tokens` 上报到 metric；**禁止把动态数据放稳定前缀** |
| 摘要丢失关键事实 | summarizer prompt 写得太短 / LLM 偷懒 | 加 eval：定期回放历史 → 检查摘要是否含必要事实 |
| offload 后 agent 找不到 | 路径没写入 system prompt 或 system prompt 频繁变化 | offload 必须在 system 层暴露 "active files" 清单 |
| Letta reflection 阻塞主进程 | 当前 `SleeptimeScheduler` 还是同步调 LLM | 必须切到**子进程 / 独立 Letta agent**（R4） |
| token 估算偏差 | Pipecat 用 4 字符 ≈ 1 token；中文 + Markdown 会偏 | 实测前先校准；若偏差大切换到 tiktoken（langchain_core 已自带 `count_tokens_approximately`） |

### 10.5 期望收益（量级估算）

| 优化 | 触发频率 | 单次节省 | 全局影响 |
|---|---|---|---|
| cache_control（系统提示稳定前缀） | 每 turn | -50% to -90% 输入成本 | 整链路成本腰斩 |
| rolling summary | > 30 轮会话 | 输入 token 减半 | 长会话场景延迟与成本都降 |
| tool result offload | 工具输出 > 20K token | -90% 该工具结果成本 | 重工具调用场景关键 |
| Letta reflection | 每日 ≤ 1 次 | — | 长期记忆保真度显著提升 |

---

## 11. 附录：参考链接汇总

### Pipecat

- <https://docs.pipecat.ai/pipecat/fundamentals/context-summarization>
- <https://docs.pipecat.ai/api-reference/server/utilities/context-summarization>
- <https://docs.pipecat.ai/api-reference/server/services/memory/mem0.md>
- <https://docs.pipecat.ai/llms.txt>

### LangChain / LangGraph / Deep Agents

- <https://docs.langchain.com/oss/python/langchain/overview>
- <https://docs.langchain.com/oss/python/langgraph/add-memory>
- <https://docs.langchain.com/oss/python/deepagents/overview>
- <https://docs.langchain.com/oss/python/deepagents/context-engineering>
- <https://docs.langchain.com/oss/python/concepts/memory>
- <https://reference.langchain.com/python/langchain-core/messages/utils/trim_messages>

### LlamaIndex

- <https://docs.llamaindex.ai/en/stable/module_guides/memory/>
- <https://docs.llamaindex.ai/en/stable/api_reference/memory/chat_memory_buffer/>
- <https://docs.llamaindex.ai/en/stable/api_reference/memory/memory/>

### Letta

- <https://docs.letta.com/llms.txt>
- <https://docs.letta.com/concepts/memfs/index.md>
- <https://docs.letta.com/concepts/conversations/index.md>
- <https://docs.letta.com/concepts/stateful-agents/index.md>
- <https://docs.letta.com/configuration/memory/index.md>
- <https://docs.letta.com/configuration/skills/index.md>
- <https://docs.letta.com/configuration/subagents/index.md>
- <https://docs.letta.com/handbook/index.md>
- <https://github.com/letta-ai/context-constitution>
- <https://agentskills.io/>

### Mem0

- <https://docs.mem0.ai/llms.txt>
- <https://docs.mem0.ai/core-concepts/how-it-works>
- <https://docs.mem0.ai/core-concepts/memory-types>

### Anthropic / OpenAI

- <https://www.anthropic.com/news/prompt-caching>
- <https://www.anthropic.com/news/context-management>
- <https://www.anthropic.com/news/contextual-retrieval>
- <https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents>
- <https://www.anthropic.com/research/building-effective-agents>
- <https://platform.openai.com/docs/guides/prompt-caching>
- <https://cookbook.openai.com/examples/prompt_caching_intro>

### 学术界 / 工程界对比文章

- Anthropic "Effective context engineering for AI agents"（必读）
- Anthropic "Building effective AI agents"
- Anthropic "Writing tools for AI agents"（<https://www.anthropic.com/engineering/writing-tools-for-agents>）
- Anthropic "How we built our multi-agent research system"
- LangChain Blog "Memory and AI agents" 系列
- Letta "Context Constitution" 论文/规范
- CoALA paper：<https://arxiv.org/pdf/2309.02427>（人类记忆 → AI agent 映射）

---

**调研人**：FAE-v2 Architecture Team · **最后更新**：2026-07-26