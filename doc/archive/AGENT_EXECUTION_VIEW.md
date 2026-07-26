# 主线与细节分层的 Agent 执行视图（归档）

> 完成日期：2026-07-26

## 目标

将聊天界面从全局 AgentSteps 重构为 per-turn 主线里程碑 + 可展开细节抽屉（Cursor-style），同时修复后端 turn 相关性、trace normalization、HTTP `subagent_timeout` 未定义变量、Telegram `on_subagent_event` 缺失等多处问题。

## 范围

三个 slice 并行落地：

- **Slice A**：live 两层视图（前端 `useVoiceSession` per-turn execution state + `ExecutionView` 组件 + approval 全链路）
- **Slice B**：backend turn 相关性（WS `turn_started`/`done.turn_id/chat_turn_id`、`ChatHistoryTurn.trace_turn_id`、`AgentTraceStore` 接受 `phase=result`、`ToolAuditEvent.turn_id`、HTTP `subagent_timeout` 修复、Telegram `on_subagent_event` 接线）
- **Slice C**：refresh 一致性（SDK `listAgentTrace`/`listToolAudit`、`fetchAgentTrace`/`fetchToolAudit`、`hydrateExecutionsFromTrace`）

## 核心改动

### 前端

| 文件 | 改动 |
|---|---|
| `ui/hooks/useVoiceSession.ts` | `TurnExecution`/`ExecutionEvent`/`ExecutionMilestone` 类型；`turnExecutions` per-turn state；`currentAssistantLineRef`；`updateExecution`/`pushMilestone` helpers；WS handlers 写入 per-turn execution；`onDone` 捕获 `turn_id`/`chat_turn_id`；`hydrateExecutionsFromTrace`；`sendApprovalDecision` wrapper；session 切换清空执行状态 |
| `ui/components/voice/ExecutionView.tsx` | 新建。主行里程碑条 + `details` 抽屉 + `ApprovalCard` + `EventRow` |
| `ui/components/voice/ChatTranscript.tsx` | 接收 `turnExecutions`/`approval` props；每个 assistant 行后渲染 `ExecutionView` |
| `ui/app/page.tsx` | 移除 `AgentSteps` import；解构 `turnExecutions`/`sendApprovalDecision`；传递给 `ChatTranscript` |
| `ui/components/voice/AgentSteps.tsx` | 已删除 |
| `ui/lib/ws-chat.ts` | re-export SDK 类型 + `ApprovalRequestMsg`；新增 `fetchAgentTrace()`/`fetchToolAudit()` |

### 后端

| 文件 | 改动 |
|---|---|
| `backend/src/fae/api/ws.py` | WS 发送 `turn_started { turn_id, session_id }`；`done` 消息新增 `turn_id` + `chat_turn_id` |
| `backend/src/fae/api/__init__.py` | HTTP `/api/chat` 修复 `subagent_timeout` 未定义；传递 `trace_turn_id`/`effective_policy`/`on_subagent_event`；新增 `_http_policy_for_session()` |
| `backend/src/fae/chat_history.py` | `ChatHistoryTurn` 新增 `trace_turn_id: str \| None`；`append` 接受该参数；ALTER + partial index |
| `backend/src/fae/api/chat_history.py` | `ChatHistoryTurnOut` 新增 `trace_turn_id`；`persist_chat_history_turn` 接受并返回 `trace_turn_id` |
| `backend/src/fae/tool_audit.py` | `ToolAuditEvent` 新增 `turn_id`；`record_event` 接受 `turn_id`；terminal UPDATE 保留 start 行的 turn_id；`list_events` 支持 `turn_id` 过滤 |
| `backend/src/fae/agent_trace.py` | 接受 `phase="result"` 并归一化为 `done`/`error`；terminal 行写入 `finished_at` + `duration_ms` |
| `backend/src/fae/api/tool_audit.py` | `ToolAuditOut` 暴露 `approval_id`/`turn_id`；`list_events` 支持 `turn_id` 过滤 |
| `backend/src/fae/channels/bridge.py` | Telegram `handle_inbound_text` 透传 `on_subagent_event`/`trace_turn_id` |

### SDK

| 文件 | 改动 |
|---|---|
| `sdk/typescript/src/types.ts` | `WsServerMessage` 扩展 `turn_started`；`done` 新增 `turn_id`/`chat_turn_id`；`ToolHandler.error_code`；`StreamHandlers.onDone` 扩展；`ChatHistoryTurn.trace_turn_id`；新增 `ApprovalDecisionInput`/`ApprovalRequestHandler`/`ApprovalResolvedHandler`/`TurnStartedHandler` |
| `sdk/typescript/src/ws-chat.ts` | `TurnStartedHandler`；`turnStartedHandler` 字段 + `setTurnStartedHandler`；`sendApprovalDecision`/`setApprovalRequestHandler`/`setApprovalResolvedHandler` |
| `sdk/typescript/src/client.ts` | `listAgentTrace()`/`listToolAudit()`；`AgentTraceEvent`/`ToolAuditEvent` 类型 |

## 修复的 Bug

1. **ToolAuditStore terminal UPDATE turn_id 覆盖**：terminal UPDATE SET 中不再无条件覆盖 turn_id，而是优先保留 start 行的值（`merged_turn_id = turn_id_clean or row["turn_id"]`）。
2. **test_history_endpoint 503**：`client.get()` 原本在 `with TestClient(app)` 块外执行，lifespan shutdown 后 `chat_history` 被置 None；已移入 `with` 块内。
3. **WS `chat_turn_id` None**：`persist_chat_history_turn` 原本返回 `None`；已改为返回 `ChatHistoryTurn | None`。

## 测试结果

- `uv run pytest`：**523 passed**，覆盖率 **79.63%**（≥ 78%）
- `pnpm lint && pnpm typecheck`：全通过
