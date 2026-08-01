# Rolling Summary 生命周期（收口）

> 2026-08 落地归档。承接 `doc/TODO.md:148-156` 的 Rolling Summary 生命周期（部分实现），把 R2 摘要从「局部重压」升级为「真正可幂等的滚动」。同时把 `MemoryCompactor` 与 R2 摘要的 ownership 关系落到代码、测试与监控上。

## 背景

`doc/TODO.md:148-156`：

- 状态：部分实现
- 需求：统一触发条件，明确 compactor 与 summarizer 的执行顺序和归档所有权，避免重复摘要。
- 验收：集成测试证明同一批 turns 不会重复摘要，关键事实不会丢失。

之前已实现：

- `RollingSummarizer`：按 hot window 调 LLM 写 `current` + archival + facts
- `MemoryCompactor`：超 max_turns 时 raw 归档
- `LettaMemoryService.persist_turn`：调 compactor + summarizer

但 R2 没有：

1. **批 ID / fingerprint**：同一批 turns 重复调用会再次调 LLM、再次写 archival、再次写 facts。
2. **Ownership 标记**：summarizer 没有 `mark_archived` 或 `summary_batch_id`，compactor 会把它已认领的 turns 再 raw 一遍。
3. **跨轮 rolling 累积**：下一轮摘要看不到上一轮 `summary_text`，是「每次重新压缩当前窗口」而非「真 rolling」。
4. **执行顺序**：文档描述 `summarizer -> compactor`，实际代码 `compactor -> summarizer`。

## 范围

- `recall_store.py`：新增 `recall_summary_batches` 表 + `recall_turns.summary_batch_id` 列；新增 `peek_oldest_uncovered` / `commit_summary_batch` / `latest_batch` / `find_batch_by_fingerprint`。
- `summarizer.py`：fingerprint 幂等、prompt 注入 previous summary、原子 batch commit、archival 写入使用 deterministic `point_id`。
- `compaction.py`：跳过 `summary_batch_id IS NOT NULL` 的 turns；保留 raw 兜底语义。
- `letta_memory.py` 持久化顺序：summarizer 先、compactor 后。

## 后端改动

### `backend/src/fae/memory/recall_store.py`

- 新表 `recall_summary_batches`（schema 见 `recall_store.py:33-49`）：

  ```sql
  CREATE TABLE recall_summary_batches (
    batch_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    fingerprint TEXT NOT NULL,
    source_first_id TEXT NOT NULL,
    source_last_id TEXT NOT NULL,
    source_count INTEGER NOT NULL,
    summary_text TEXT NOT NULL DEFAULT '',
    committed_at TEXT NOT NULL,
    UNIQUE(session_id, fingerprint)
  );
  ```

- `recall_turns` 增加 `summary_batch_id TEXT` 列。
- 新方法：
  - `peek_oldest_uncovered(sid, n)`：只返回 hot 且 `summary_batch_id IS NULL` 的 turns。
  - `commit_summary_batch(session_id, fingerprint, turn_ids, summary_text, batch_id)`：`BEGIN IMMEDIATE` + 插入 batch + 把 turns 标 `summary_batch_id`。`(session_id, fingerprint)` UNIQUE 冲突 → 返回 `None`，调用方视为幂等成功。
  - `latest_batch(sid)` / `find_batch_by_fingerprint(sid, fingerprint)`。

### `backend/src/fae/memory/summarizer.py`

- `maybe_summarize()` 重写：
  1. 触发条件维持原 AND 语义（见 `CONTEXT_ENGINEERING.md` §R2）。
  2. 用 `hot[:len(hot) - recent_keep]` 算 fingerprint（覆盖逻辑窗口，**包括已被上一 batch claim 的 turns**）—— 这样下一轮观察同一 hot 窗口时一定会命中已有 batch。
  3. 命中已有 batch → 返回 `SummaryResult(skipped="already_committed", batch_id=...)`，**不调 LLM、不写 archival、不写 facts**。
  4. 未命中 → `peek_oldest_uncovered` 取实际可 claim 的 turns，注入上一 batch 的 `summary_text` 为 `<previous_summary>` 后调 LLM。
  5. LLM 成功后：
     - 写 `current` block（含 batch_id）
     - 写 archival（`point_id = UUID5(BATCH_FINGERPRINT_NS, fingerprint)`）
     - 写 facts
     - 调 `commit_summary_batch` 原子 commit；UNIQUE 冲突时仍视为成功，回写 canonical batch_id。
- `_fingerprint_for(session_id, turns)`：`sha256(session_id::"|".join(turn.id))[:32]`。
- `_SUMMARY_SYSTEM_PROMPT` 追加「merge durable facts from <previous_summary>」。
- `SummaryResult` 新增 `batch_id` / `archive_point_id` 字段。

### `backend/src/fae/memory/compaction.py`

- `peek_oldest_hot` → `peek_oldest_uncovered`：只选 hot 且 `summary_batch_id IS NULL` 的 turns。
- 顶部 docstring 明确 ownership：

  > `MemoryCompactor` is the **raw fallback** of the rolling summary
  > lifecycle. `RollingSummarizer` runs first; when it successfully
  > commits a summary batch it claims ownership of the source turns by
  > writing `recall_turns.summary_batch_id`. The compactor then **skips**
  > any turn that has `summary_batch_id IS NOT NULL` so the same turn is
  > never raw-archived twice.

- `still_hot` 检查扩大为 `max(hot, n)`，保证最近追加的 uncovered turn 也通过 liveness 检查。

### `backend/src/fae/pipecat/services/letta_memory.py`

`persist_turn()` 顺序：

```text
append_recall → persist_episodes → RollingSummarizer.maybe_summarize → MemoryCompactor.maybe_compact → on_persist
```

注释明确：「semantic summary 优先认领，compactor 兜底剩余 overflow」。

## 测试

新增 `backend/tests/test_rolling_summary_lifecycle.py`（6 例）：

| 测试 | 覆盖点 |
|---|---|
| `test_summary_idempotent_for_same_hot_turns` | 同一 hot 窗口连续两次 `maybe_summarize` → 第二次 `skipped="already_committed"`、`provider.calls` 仍为 1、`archival._items` 仍为 1、batch 表仍为 1 行 |
| `test_summary_passes_previous_summary_to_next_round` | 第二次 LLM 收到的 user message 含 `<previous_summary>...</previous_summary>`，且包含第一轮 `summary_text` |
| `test_compactor_skips_already_summarized_turns` | 摘要 commit 后再 `maybe_compact` → compactor 只 raw 归档未被 claim 的 turn，summarized turn 的 id 不会出现在任何 raw archival 文本中 |
| `test_compactor_falls_back_for_unsummarized_overflow` | summarizer 缺席时，compactor 仍能 raw 归档 overflow；没有任何 turn 被 claim |
| `test_summary_fingerprint_changes_when_window_changes` | 新 turn 推进窗口 → 新 fingerprint → 新 LLM call + 新 batch_id |
| `test_commit_summary_batch_is_idempotent_at_store_layer` | store 层 `commit_summary_batch` 重复提交同 fingerprint 第二次返回 `None`，`latest_batch` 仍是第一次的 canonical 数据 |

既有 `tests/test_rolling_summary.py` / `test_recall_archival.py` / `test_sleeptime.py` / `test_reflection.py` 全部 35 例通过。

后端整体 **585** 例通过，覆盖率 **79.02%**（>78% 阈值）。

## 文档

- `doc/design/CONTEXT_ENGINEERING.md` §R2 重写：触发条件改为 AND 文案；新增 fingerprint 幂等、previous_summary 注入、archival deterministic point_id、batch commit、ownership 与 compactor 的关系；测试索引新增 `test_rolling_summary_lifecycle.py`。
- `doc/TODO.md` 第 148-156 行 Rolling Summary 生命周期更新为「已完成（归档见 `doc/archive/ROLLING_SUMMARY_LIFECYCLE.md`）」。

## 验收对齐

- ✅ 集成测试证明同一批 turns 不会重复摘要：`test_summary_idempotent_for_same_hot_turns` + `test_commit_summary_batch_is_idempotent_at_store_layer`。
- ✅ 关键事实不会丢失：`test_summary_passes_previous_summary_to_next_round` 断言上一轮 `summary_text` 进入下一轮 prompt，并由 prompt 升级为合并指令（durable facts 不会被丢弃）。
- ✅ 统一触发条件：触发逻辑以代码为准（AND of count and (chars or 2×count)），文档与代码对齐。
- ✅ 执行顺序：`LettaMemoryService.persist_turn` 改为 summarizer→compactor。
- ✅ 归档所有权：`summary_batch_id` + `peek_oldest_uncovered` 双向断言。

## 仍未覆盖（留作后续）

- **评测 harness**：`doc/TODO.md:180-188` Context Engineering 集成评测——把本次 lifecycle 测试的离线 runner 接入 CI。
- **Token 阈值**：当前 R2 是字符阈值；如需 token-aware，可扩展 `RollingSummarizer` 而不破坏 fingerprint 语义。
- **多进程并发**：`BEGIN IMMEDIATE` 解决 SQLite 单 DB 内原子性；若引入多进程 RecallStore，需要外部分布式锁（当前架构未使用）。