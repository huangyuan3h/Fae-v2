# 长任务进度、重试与幂等

> 2026-08 落地归档。承接 `doc/TODO.md:204-212` 的「长任务进度、重试与幂等」与 `doc/TODO.md:214-222` 的「外部 channel 闭环」（前置依赖）。把 TaskStore 从「状态机已有但 CAS 与审计缺失」收口为「可幂等、可重试、可审计、可进度可见」。

## 背景

`doc/TODO.md:204-212`：

- 状态：待开始
- 验收：重复请求不会产生重复副作用，失败任务可安全重试。

收口前 TaskStore 已具备 SQLite/WAL、状态图、`attempts/max_attempts`、`needs_input`、人工 `retry`、REST 查询、启动恢复；但缺：

1. 真正的 idempotency_key 与请求去重
2. 原子 CAS（重复 `claim` / `complete` / `fail` 会被接受且副作用叠加）
3. `max_attempts` 仅存不执行
4. `retry()` 不会真正清空旧错误（`if patch.x is not None` 语义陷阱）
5. 进度只有粗粒度 `status/notes`，没有 progress / current_step / percent
6. 错误只有当前快照，没有 attempt 历史结构化
7. recovery 会无差别自增 attempts，可能误伤多 worker

`doc/TODO.md:214-222` 的「外部 channel 闭环」被这些缺陷直接阻塞：Telegram 重复投递 / 重试 / 用户在手机上重新触发都需要可靠幂等。

## 范围

- `tasks.py` schema：新增 `idempotency_key` / `fingerprint` / `progress_json` 三列 + UNIQUE 部分索引
- `tasks.py` store：`create_task` idempotent replay、`claim`/`complete`/`fail` 走 SQLite CAS、`retry` 真清空、`update_progress` 合并写、`error_history` 结构化
- `tasks.py` 错误类型：`AttemptsExhausted`、`IdempotencyConflict`
- `api/tasks.py`：读 `Idempotency-Key` header、`PATCH /api/tasks/{id}/progress`、响应增加 `progress` / `error_history` / `idempotency_key` / `fingerprint` 字段

## 后端改动

### `backend/src/fae/scheduler/tasks.py`

**Schema 迁移**：

```sql
CREATE TABLE IF NOT EXISTS tasks (
  ...
  notes_json TEXT NOT NULL DEFAULT '[]',
  idempotency_key TEXT,
  fingerprint TEXT,
  progress_json TEXT NOT NULL DEFAULT '{}'
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_tasks_session_idem
  ON tasks (session_id, idempotency_key)
  WHERE idempotency_key IS NOT NULL;
```

`_migrate_schema()` 通过 `PRAGMA table_info(tasks)` 检查缺失列后 `ALTER TABLE ADD COLUMN`，最后单独创建 UNIQUE 索引（确保迁移后列存在）。

**`_UNSET` sentinel**：

```python
_UNSET: Any = object()
```

`TaskUpdate` 接受 `_UNSET` 表示「显式清空此列到 NULL」，与 `None`（不更新）区分。这是 `retry()` 真清空旧错误 / result / timestamps 的关键。

**`create_task` idempotent**：

- 同 `(session_id, idempotency_key)` 已存在 → 校验 fingerprint 一致则 replay 原 task（返回相同 id）；不一致抛 `IdempotencyConflict`。
- 无 key → 始终插入（兼容旧调用）。
- 用 `INSERT ...` + 捕获 `sqlite3.IntegrityError` 兜底并发 race（两个 worker 同时插同一 key）。

**CAS state transitions**：

`claim()` 走：

```sql
UPDATE tasks SET status='running', attempts=attempts+1, ...
WHERE id=? AND status IN ('queued','needs_input') AND attempts < max_attempts
```

`rowcount=0` → `InvalidTaskTransition` 或 `AttemptsExhausted`。这同时关闭了「重复 claim」「同状态重复操作」「超额尝试」三个 P0 漏洞。

`complete()` 走 `WHERE id=? AND status='running'` CAS。同结果 replay，不同结果 → 409。
`fail()` 走 `WHERE id=? AND status IN ('running','needs_input')` CAS，重复 fail → 409。

**`retry()` 真清空**：

```python
TaskUpdate(
    status=TaskStatus.QUEUED.value,
    result=_UNSET,
    error_code=_UNSET,
    error_message=_UNSET,
    resume_token=_UNSET,
    clear_started_at=True,
    clear_finished_at=True,
    note=note or "retry queued",
)
```

`attempts` 不在此处增加 —— 只有真正的 `claim` 才会递增 attempts（语义清晰：attempts = 进入 running 的次数）。

**`update_progress()` + `error_history()`**：

- `update_progress(task_id, progress=..., note=...)`：仅非终态可更新，done 同值 replay / 不同值 409。merge 写入而非覆盖。
- `error_history(task_id)`：从 notes 里提取 `event=attempt_failed` 结构化事件，附带 `attempt` / `error_code` / `error_message` / `at`。

**`_append_attempt_failed_locked`**：fail 时自动追加一条 `attempt_failed` 事件到 notes，attempt 编号取当时的 attempts（claim 已 +1），保证 retry 后历史仍按真实尝试编号排列。

### `backend/src/fae/api/tasks.py`

**Idempotency-Key header**：

- `POST /api/tasks` 接受 `Idempotency-Key` header。
- fingerprint = `sha256(json.dumps({kind, title, payload, session_id}, sort_keys=True))` 取前 32 字符。
- 同 key 同 fp → 201 replay；同 key 不同 fp → 409 `idempotency_conflict`。

**新增 `PATCH /api/tasks/{task_id}/progress`**：

```text
PATCH /api/tasks/{id}/progress
{ "progress": { "current": 1, "total": 5, "percent": 20, "current_step": "fetch" }, "note": "…" }
```

**响应增强**：`TaskOut` 增加 `idempotency_key` / `fingerprint` / `progress` / `error_history` 四字段。所有 GET / POST 端点都返 error_history（结构化查询方便）。

**错误码**：
- 409 `invalid_transition` / `attempts_exhausted` / `idempotency_conflict`
- 404 `task not found`
- 503 `task store not ready`

## 测试

新增 / 调整：

- `backend/tests/test_task_reliability.py`（14 例）：
  - `test_create_idempotency_key_replays_same_task`
  - `test_create_idempotency_key_with_different_payload_raises`
  - `test_create_without_idempotency_key_always_inserts`
  - `test_concurrent_claim_only_one_wins`（多 TaskStore 句柄同文件）
  - `test_claim_enforces_max_attempts` → `AttemptsExhausted`
  - `test_duplicate_claim_is_rejected`
  - `test_duplicate_complete_is_idempotent_with_same_result`
  - `test_duplicate_complete_on_running_rejected`
  - `test_duplicate_fail_rejected`
  - `test_retry_clears_stale_state`（验证 error_code / started_at / finished_at 都被清空，历史保留）
  - `test_progress_round_trip`（merge 行为）
  - `test_progress_rejected_after_done`
  - `test_fail_appends_structured_attempt_failed`
  - `test_recovery_does_not_invalidate_idempotency_keys`

- `backend/tests/test_task_api_reliability.py`（8 例）：
  - `test_idempotency_key_replays_same_task` / `test_idempotency_key_with_different_payload_returns_409`
  - `test_attempts_exhausted_returns_409`
  - `test_progress_endpoint_round_trip` / `test_progress_endpoint_rejects_done_with_different_value`
  - `test_fail_appends_error_history`
  - `test_retry_clears_stale_error`
  - `test_duplicate_complete_returns_409_on_mismatch`

- 既有 `tests/test_task_store.py` / `tests/test_task_api.py` 24 例全部通过（迁移兼容）。

后端整体 **607** 例通过，覆盖率 **78.99%**（>78% 阈值）。
FE：`pnpm typecheck` / `pnpm lint` / `pnpm build` 全部通过。

## 验收对齐

- ✅ **重复请求不会产生重复副作用**：
  - `test_concurrent_claim_only_one_wins`：两个 TaskStore 同文件并发 claim → 仅一个成功。
  - `test_duplicate_claim_is_rejected`：同状态重复 claim → 409。
  - `test_duplicate_complete_on_running_rejected`：done 后再 complete 不同 result → 409。
  - HTTP `test_idempotency_key_replays_same_task`：同 key 同 fingerprint 复用原 task，单行存在。

- ✅ **失败任务可安全重试**：
  - `test_claim_enforces_max_attempts`：超额 claim → `AttemptsExhausted` 409。
  - `test_retry_clears_stale_state`：failed → retry 后 error / started_at / finished_at 全清零，attempts 不增。
  - `test_fail_appends_structured_attempt_failed`：每次失败追加 `attempt_failed` 事件到历史。

- ✅ **进度可见**：
  - `test_progress_round_trip`：merge 行为 + 字段回读。
  - HTTP `test_progress_endpoint_round_trip`：PATCH 进度端点 + GET 返回合并结果。

- ✅ **错误审计**：
  - `test_fail_appends_error_history`：多次失败的历史按 attempt 编号累加。
  - HTTP 响应 `error_history` 字段直接结构化查询。

## 仍未覆盖（保留给后续）

- **Schedule execution 接入 TaskStore**：`scheduler/loop.py` 仍独立走 ScheduleStore；本次未把 cron/date job occurrence 创建为 Task（涉及 `_check_due_reminders` 与 `run_job` 的 race 治理）。下一次 phase。
- **Lease / worker_id**：当前 CAS 防止 duplicate claim，但无法检测「同一 worker 崩溃后另一 worker 接续」。若引入多 worker / 多进程，需要 `lease_owner` + `lease_until`。
- **NotificationDelivery idempotency**：`scheduler/delivery.py` 仍每次生成新 inbox + 调 Telegram；Telegram 投递无 delivery key，下次 phase。
- **Telegram inbound needs_input**：依赖 Telegram poll loop 把 `update_id` 写入 store，去重后再路由到 `provide_input`。本次未实现。