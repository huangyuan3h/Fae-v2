# Context Engineering — 现状与选型

> 替代 [`CONTEXT_ENGINEERING_RESEARCH_2026-07-26.md`](../archive/CONTEXT_ENGINEERING_RESEARCH_2026-07-26.md)：那份是 2026-07-26
> 写的研究选型（Pipecat / Deep Agents / Anthropic / Letta / Mem0 对比），现在已
> 落地 — 本文只留**当前生效的选型 + 入口 + 配置**。

## 0. TL;DR

FAE-v2 的 context engineering 由 6 个相互正交的模块组成，全部默认开启（除
明确标注的 opt-in 项）：

| # | 模块 | 入口 | 触发条件 | 收益 | 配置 |
|---|---|---|---|---|---|
| **R1** | **cache_control 透传** | `fae/llm/provider.py` `_apply_cache_control_to_kwargs` | base_url 命中 Anthropic / 携带 `anthropic-version` 头 | 首 token **-75%**，输入 **-50% ~ -90%** | `LLMConfig.cache_control: auto\|off\|ephemeral-5m\|ephemeral-1h` |
| **R2** | **LLM rolling summary** | `fae/memory/summarizer.py` `RollingSummarizer.maybe_summarize` | 热窗口 ≥ `rolling_summary_max_turns=30` 或 ≥ 9000 字符 | 长会话输入 token 减半；保留最近 6 条原文 | `settings.rolling_summary_*` |
| **R3** | **Pipecat LLMContextSummarizer**（Daily 路径） | `fae/pipecat/summarizer_bridge.py` `build_assistant_aggregator_params` | `LLMAssistantAggregatorParams.enable_auto_context_summarization=True` | 长电话不会被 context 打爆 | `settings.daily_context_summary_enabled=False`（默认 off） |
| **R4** | **Letta-style reflection subagent** | `fae/memory/reflection.py` `SubagentReflectionRunner` + `fae/memory/consolidation.py` `MemoryConsolidator.reflection_runner` | `SleeptimeScheduler.consolidate_now()` 触发 | 启发式正则升级到 LLM 摘要 + 抽取事实；失败时自动回退 | `settings.reflection_enabled=True` |
| **R5** | **Tool-result offload**（Deep Agents FilesystemMiddleware 移植） | `fae/agent/tool_offload.py` `ToolOffloader.maybe_offload` + `_wrap_tool_result` | tool result > `tool_offload_chars=8000` | 大工具输出 **-90%**；offloaded 路径 + preview 进 cache | `settings.tool_offload_*` |
| **R6** | **Contextual Retrieval**（Anthropic §6.3） | `fae/memory/contextual.py` `ContextualizingArchival` | `contextual_retrieval_enabled=True` 时包裹 `archival.upsert` | 检索失败率 **-49%**（Anthropic 实测）；利用 cache_control 让 chunk-contextualization 几乎免费 | `settings.contextual_retrieval_*`（**默认 off**，需手动开启） |

监控：`GET /api/memory/stats` 现已暴露 `cache_health`（hit ratio + 信号提示）和
`context_engineering` 子树（每个模块的 on/off 状态）。

完整研究笔记与对比表见 [`CONTEXT_ENGINEERING_RESEARCH_2026-07-26.md`](../archive/CONTEXT_ENGINEERING_RESEARCH_2026-07-26.md)。

---

## 1. 决策记录（不做什么）

来自原研究 §10.3，仍旧有效：

- ❌ **不引入 LangGraph runtime** — FAE-v2 自建 FastAPI + Pipecat 已稳。
- ❌ **不引入 Mem0 / Zep** — 与 Letta MemFS 重叠（FAE 已有 SQLite + Qdrant
  自做 recall/archival）。
- ❌ **不引入 LlamaIndex runtime** — 仅借鉴其 `ChatSummaryMemoryBuffer` 算法
  思想（即 R2 rolling summary）。

---

## 2. 各模块详解

### R1 · `cache_control` 透传（Anthropic）

**入口**：`fae/llm/provider.py::_apply_cache_control_to_kwargs`

- 自动检测：`base_url` 包含 `anthropic.com` / `anthropic.` / `/anthropic`
  子串，或 `headers` 含 `anthropic-version` 字段。
- 自动行为：
  - system messages → Anthropic 数组形式，最后一块带 `cache_control: ephemeral`。
  - 最后一个 tool 加上同样的 marker（保护 tool schema cache）。
  - `extra_body.cache_control` 同步写入（off-spec gateway 用）。
- TTL：`auto` / `off` / `ephemeral-5m` / `ephemeral-1h`，默认 `auto`。
- 关闭方法：客户端 `LLMConfig.cache_control="off"` 或 base_url 改成
  非 Anthropic（DashScope OpenAI-compat 默认走 OpenAI 自动缓存）。

**测试**：`backend/tests/test_context_engineering.py` `test_cache_control_*`

### R2 · LLM-driven rolling summary

**入口**：`fae/memory/summarizer.py::RollingSummarizer.maybe_summarize`

- 触发：`len(hot_turns) >= max_turns` **AND** (`char_total >= max_chars`
  **OR** `len(hot_turns) >= 2 * max_turns`)（默认 30 / 9000）。
- 行为：
  - 仅选**未被任何 batch 认领**的最旧 `N = hot - recent_keep` 条 turn。
  - 用 `(session_id, ordered_turn_ids)` 算 fingerprint。命中已有 batch
    → 返回 `SummaryResult(skipped="already_committed")`，**不调 LLM**。
  - 新指纹：调便宜 LLM（默认 `resolve_server_llm_config` 的 proactive
    模型），提示词注入上一次 batch 的 `summary_text` 作为
    `<previous_summary>` 让 summary 真正累计而非重新压缩。
  - 严格 JSON 提示词返回 `{summary, facts, open_questions}`。
  - `summary` → Letta `current` block（overwrite，非 append）。
  - `facts` → 通过 `client.save_fact()` 入事实库。
  - 同 summary 文本 + `["recall_summary", "rolling"]` 标签 → archival，
    `point_id = UUID5(fingerprint)` 让重复写入幂等。
  - LLM 成功后原子提交 `recall_summary_batches` 行：
    `(batch_id, session_id, fingerprint, source_first_id,
    source_last_id, source_count, summary_text, committed_at)`，并把
    `recall_turns.summary_batch_id` 标上。
- 不破坏 cache_control：稳定前缀（system/tools）不动；最近 6 条原文
  继续直进 prompt。

**与 `compaction.py` 的关系（执行顺序）**：

1. `RollingSummarizer` 先跑，claim 它负责的 turns；
2. `MemoryCompactor` 后跑，**跳过**所有 `summary_batch_id IS NOT NULL`
   的 turn —— 这些 turn 已经被语义摘要认领过，再走 raw 归档会双写。
3. 若 summarizer 不可用或上一 batch 失败，compactor 仍兜底剩下的
   `summary_batch_id IS NULL` overflow，老链路不破。

**测试**：`backend/tests/test_rolling_summary.py` + 新增
`backend/tests/test_rolling_summary_lifecycle.py`
（同窗口重复不重复摘要 / 上轮 summary 注入 prompt / compactor 跳过
已认领 / summarizer 缺席时 compactor 兜底 / batch 提交层幂等）。

### R3 · Pipecat `LLMContextSummarizer`（Daily 路径）

**入口**：`fae/pipecat/summarizer_bridge.py::build_assistant_aggregator_params`

- 仅 Daily 路径（`daily_bot.py`）启用。默认 **off** — Daily 路径尚未作为
  默认路径，opt-in 避免对单条 LLM 加上额外 summarize 成本。
- 接 `LLMAssistantAggregatorParams.enable_auto_context_summarization=True`，
  `LLMAutoContextSummarizationConfig` 设 `max_context_tokens` /
  `max_unsummarized_messages` / `target_context_tokens` / `min_messages_after_summary`。
- 默认 Pipecat 启发式（4 char ≈ 1 token）。

**测试**：`backend/tests/test_daily_context_summarizer.py`

### R4 · Letta-style reflection subagent

**入口**：
- `fae/memory/reflection.py::SubagentReflectionRunner`
- `fae/agent/subagents/builtins.py` `reflection` prompt
- `fae/memory/consolidation.py` `MemoryConsolidator.reflection_runner`

- 触发：SleeptimeScheduler 触发 consolidation 时。
- 行为：把最近 N 条 turn 作为 `task` 喂给 `run_subagent("reflection", ...)`，
  子 agent 输出严格 JSON `{summary, facts, open_questions}`。
- 结果写入：
  - `current` block → `"# Reflection session=…\n# compressed=N turns\n…"`
  - facts → `client.save_fact`，tag `["reflection", "auto"]`
  - 同 summary → archival，tag `["reflection", "recall_summary"]`
- **失败兜底**：subagent 返回 `ok=False` 或空 payload 时，consolidator 自动
  退到原有启发式 bullet 路径（不会被破坏）。
- 关闭：`settings.reflection_enabled=False`。

**测试**：`backend/tests/test_reflection.py`

### R5 · Tool-result offload

**入口**：
- `fae/agent/tool_offload.py::ToolOffloader.{maybe_offload, cleanup_expired}`
- `fae/agent/tool_offload.py::tool_offload_cleanup_loop`（周期性 GC）
- `fae/agent/llm_turn.py::_wrap_tool_result`（覆盖所有 tool result 注入点）

- 触发：`len(result) > settings.tool_offload_chars=8000`。
- 行为：写到 `settings.tool_offload_dir=.data/tool-offload/<safe_tool>-<safe_id>-<sha12>.json`，
  在 prompt 中替换为：
  ```text
  <tool_result name="X" offloaded="true" path="..." full_chars="...">
  <tool_offload tool="X" path="..." chars="..." preview_chars="..."></tool_offload>
  </tool_result>
  The full result body was offloaded to disk to keep context small.
  Use the read_file tool on the path above to pull it back...
  ```
- **路径字节稳定**：仅含 content digest（无 wall-clock ts），同一内容跨进程同路径；多次相同写入幂等覆盖。
- **替换 body 字节稳定**：`OffloadResult.to_prompt_replacement` 输出被 `test_prompt_envelope_is_byte_stable` 钉住，cache_control 命中不受影响。
- **`read_file` 触达 offload 指针**：`dispatch_filesystem_tool(read_file, ..., extra_roots=(tool_offload_dir,))`。`safe_resolve` 接受多个 root，让 `read_file` 不必配置 `coding_workspace_root` 也能读回本体；同时仍遵守 `outside_workspace` 沙箱规则。
- **TTL 自动清理**：
  - 设置 `tool_offload_ttl_s`（默认 86400=24h）+ `tool_offload_cleanup_interval_s`（默认 300=5min）。
  - lifespan 启动时跑一次 `cleanup_expired()` 兜底（捕进程停机期间的过期）。
  - 后台 `tool_offload_cleanup_loop` 周期执行；shutdown 取消。
- 已接入的 tool 注入点：
  - coding tools（filesystem/bash/git）`llm_turn.py:_dispatch_coding_tool`
  - weather tool
  - subagent run_subagent
  - 未来所有 `_tool_result_message` 站点
- 已接入的入口：HTTP `/api/chat`、WS `/ws/chat`、Telegram inbound；所有入口都把 `tool_offload_dir` 透传给 `read_file` 沙箱。

**测试**：`backend/tests/test_tool_offload.py`（覆盖：稳定路径、TTL GC、loop / cancel、read_file 往返、envelope 字节钉）+ `tests/test_api.py::test_lifespan_wires_tool_offloader_and_cleanup_task`

### R6 · Contextual Retrieval

**入口**：
- `fae/memory/contextual.py::ContextualRetriever.enhance`
- `fae/memory/contextual.py::ContextualizingArchival`（包裹 archival backend）

- 触发：每次 `archival.upsert()` 时调用 LLM 生成 50–100 token 的 context
  句，prefix 拼接到 chunk 一起 embed。
- LLM 输入包含"reference document"（最近的 recall 摘要或 chunk 自身），可被
  Anthropic cache_control 命中 → 多次 chunk-contextualization 几乎免费。
- **默认关闭**（`contextual_retrieval_enabled=False`）——多一次 LLM call，
  没有 Anthropic cache 时成本偏贵；Anthropic 直连路径打开最有价值。
- 关闭后所有 archival 行为照旧。

**测试**：`backend/tests/test_contextual_retrieval.py`

---

## 3. 监控 — `/api/memory/stats`

`GET /api/memory/stats` 现在返回：

```jsonc
{
  "recall_turns": 12,
  "core": { "blocks": { "persona": {...}, "human": {...}, "current": {...} } },
  "archival": "ok",
  "vector_mode": "stub",
  "events": 4,
  "sleeptime": "on",
  "llm_usage": {
    "prompt_tokens": 120000,
    "completion_tokens": 9000,
    "cached_tokens": 80000,
    "cache_creation_tokens": 20000,
    "calls": 250
  },
  "cache_hit_ratio": 0.6667,
  "cache_health": {
    "status": "ok",                       // ok | warn | unknown
    "ratio": 0.6667,
    "prompt_tokens": 120000,
    "cached_tokens": 80000,
    "cache_creation_tokens": 20000,
    "signal": "cache_control paying off"
  },
  "context_engineering": {
    "rolling_summary": "on",
    "tool_offload": "on",
    "reflection": "on",
    "contextual_retrieval": "off",        // opt-in
    "daily_summarizer": "off",            // opt-in
    "cache_control": "auto_or_anthropic"
  }
}
```

`cache_health.status` 阈值：

| 状态 | hit_ratio | 含义 |
|---|---|---|
| `ok` | ≥ 0.5 | cache_control 生效（Anthropic 实测 -50% ~ -90%） |
| `warn` | 0.2 ~ 0.5 | 命中偏低 — 检查 system 前缀是否含 session id / 时间戳 |
| `warn` | < 0.2 | 几乎无缓存 — 前缀可能在每轮变化，或 cache_control 未送达 |
| `unknown` | n/a | 还没累积 usage |

**测试**：`backend/tests/test_memory_stats_health.py`

---

## 4. 风险与运维

| 风险 | 触发条件 | 监控 / 缓解 |
|---|---|---|
| cache 命中率低 | system prompt 每轮变（时间戳 / session id） | `cache_health.status` 上报到 metric；system 前缀禁止放动态数据 |
| 摘要丢关键事实 | summarizer prompt 太短 / LLM 偷懒 | 后续加 eval 回放（R8 候选）；failure 时回退到 bullet summary |
| reflection 阻塞主进程 | subagent 调用卡住 | `_run` 已有 `max_runtime_s=30s` timeout；失败 → 启发式 fallback |
| tool offload 占用盘 | 长会话累积 .json | `tool_offload_ttl_s` + `cleanup_interval_s`；启动 sweep + 后台 loop；`OFFLOAD_TTL_S=0` 可关闭 |
| offloaded 路径 Agent 读不回来 | sandbox 拒绝 workspace 之外的路径 | `dispatch_filesystem_tool(read_file, ..., extra_roots=(tool_offload_dir,))`；只有显式传入的 extra_roots 才豁免 |
| Contextual Retrieval 成本 | 没启用 cache_control 时仍每 chunk 调一次 LLM | 默认 off；开启前必须确认走 Anthropic 直连 |

---

## 5. 设置汇总（`backend/src/fae/config.py`）

```python
# R1 — 在 LLMConfig（per-request）层，不在 Settings
# LLMConfig.cache_control: auto | off | ephemeral-5m | ephemeral-1h

# R2 rolling summary
rolling_summary_enabled: bool = True
rolling_summary_max_turns: int = 30
rolling_summary_max_chars: int = 9000
rolling_summary_recent_keep: int = 6
rolling_summary_timeout_s: float = 20.0

# R3 Daily summarizer（仅 Daily 路径）
daily_context_summary_enabled: bool = False
daily_context_max_tokens: int = 8000
daily_context_target_tokens: int = 4000
daily_context_recent_messages: int = 4

# R4 reflection subagent
reflection_enabled: bool = True
reflection_max_task_chars: int = 6000
reflection_timeout_s: float = 20.0

# R5 tool offload
tool_offload_enabled: bool = True
tool_offload_chars: int = 8000
tool_offload_dir: str = ".data/tool-offload"
tool_offload_keep_lines: int = 20
tool_offload_ttl_s: float = 86_400      # 24h; 0 disables sweeping
tool_offload_cleanup_interval_s: float = 300  # 5min background loop

# R6 Contextual Retrieval（默认 off）
contextual_retrieval_enabled: bool = False
contextual_retrieval_chars: int = 160
```

---

## 6. 模块 → 文件索引

| 模块 | 主文件 | 测试 |
|---|---|---|
| R1 cache_control | `fae/llm/provider.py` · `fae/llm/types.py` | `tests/test_context_engineering.py` |
| R2 rolling summary | `fae/memory/summarizer.py` · `fae/memory/factory.py` | `tests/test_rolling_summary.py` |
| R3 Pipecat summarizer | `fae/pipecat/summarizer_bridge.py` · `fae/pipecat/daily_bot.py` | `tests/test_daily_context_summarizer.py` |
| R4 reflection subagent | `fae/memory/reflection.py` · `fae/memory/consolidation.py` · `fae/agent/subagents/builtins.py` | `tests/test_reflection.py` |
| R5 tool offload | `fae/agent/tool_offload.py` · `fae/agent/llm_turn.py` | `tests/test_tool_offload.py` |
| R6 Contextual Retrieval | `fae/memory/contextual.py` · `fae/memory/factory.py` | `tests/test_contextual_retrieval.py` |
| 监控 | `fae/api/memory.py` `_cache_health` | `tests/test_memory_stats_health.py` |

---

**最后更新**：2026-07-26（v0.5.x 之后下一波收口）