# 一键遗忘 — 归档记录

**完成日期**：2026-07-26
**重要等级**：P1
**收益程度**：高
**改动量**：大

## 目标

统一删除用户个人数据（facts、recall、archival、episodic、chat history），
支持按 session 或全局删除，删除边界明确且可验证。

## 实现

### 新增文件
- `backend/src/fae/data_deletion.py` — `DataDeletionService` 编排所有 store 的 clear/delete 方法
- `backend/src/fae/api/data_forget.py` — `POST /api/data/forget` 端点，需客户端 token 认证
- `backend/tests/test_data_deletion.py` — 9 个测试覆盖各 store clear 方法和 DataDeletionService

### 各 Store 添加的 clear() 方法

| Store | 文件 | clear 方法 |
|-------|------|-----------|
| ChatHistoryStore | `chat_history.py` | `clear(session_id=None)` 删除 turns + sessions |
| ToolAuditStore | `tool_audit.py` | `clear(session_id=None)` 删除事件 |
| AgentTraceStore | `agent_trace.py` | `clear(session_id=None)` 删除 trace 事件 |
| ApprovalStore | `approvals.py` | `clear(session_id=None)` 删除审批行 + 清除 futures |
| TaskStore | `scheduler/tasks.py` | `clear(session_id=None)` 删除任务 |
| ScheduleStore | `scheduler/store.py` | `clear_user(session_id=None)` 删除用户任务 + inbox + activity + outreach |
| RecallStore | `memory/recall_store.py` | `clear(session_id=None)` 物理删除（非 mark_archived） |
| EpisodicStore | `memory/episodic.py` | `clear(session_id=None)` 删除事件 + event_links |
| EmbeddedMemoryClient | `memory/embedded.py` | `delete_all_facts()` / `delete_session_facts(session_id)` |
| LettaMemoryClient | `memory/letta_client.py` | `delete_all_facts()` / `delete_session_facts(session_id)` |
| StubArchival | `memory/archival.py` | `clear(session_id=None)` 清空 `_items` |
| QdrantArchival | `memory/archival.py` | `clear(session_id=None)` drop collection; per-session 用 filter 删除 |
| ToolOffloader | `agent/tool_offload.py` | `clear(session_id=None)` 删除所有 offload JSON 文件 |

### 协议扩展
- `ArchivalBackend` protocol 添加 `async def clear(*, session_id=None) -> int`

### 删除范围策略

- **Session-scoped**：删除该 session_id 对应的所有数据（chat、trace、audit、approval、task、recall、episodic、facts、offload files、notification inbox、activity/outreach for that session）
- **Global**：删除所有非系统配置数据（保留 builtin schedules、notification prefs、push subs）

### 验收

- 9 个测试全部通过（`pytest tests/test_data_deletion.py`）
- 端到端验证：写入数据 → `POST /api/data/forget` → 各 store 返回空
- `pnpm lint && pnpm typecheck` 通过