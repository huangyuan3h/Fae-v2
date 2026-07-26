# 可查询的 Agent 执行轨迹

**状态**：已完成  
**完成日期**：2026-07-26

## 已交付

- 独立 SQLite `AgentTraceStore`，按 `turn_id` 顺序记录 subagent / tool / skill 三类过程事件。
- 新事件 API 兼容 WS / HTTP / Telegram 三路，事件形态按 `kind` 自解释（`type` 保留为 `tool` / `subagent` / `skill`，新加 `kind` 字段）。
- 复用 `fae.sanitize` 公共 helper，与 `tool_audit` 共享脱敏规则与长度限制。
- `GET /api/agent-trace`，支持按 session、turn、kind、before 游标与 limit（默认 200 / 上限 500）查询。
- 跨重启恢复：测试中重新打开 store 仍能取到上次写入的事件。
- 三路 callback 接入 `HTTP /api/chat`、`/ws/chat` 与 Telegram inbound；两路统一双写（trace + audit）。

## 主要入口

- `backend/src/fae/agent_trace.py` — store + callback。
- `backend/src/fae/api/agent_trace.py` — `/api/agent-trace` 路由。
- `backend/src/fae/agent/llm_turn.py` — 工具事件统一打 `kind=tool`，并透传 `trace_turn_id`。
- `backend/src/fae/agent/subagents/tools.py` — subagent 事件打 `kind=subagent`。
- `backend/src/fae/api/ws.py` — WS 三元回调链（send → trace → audit）。
- `backend/src/fae/api/__init__.py` — lifespan 初始化 / 关闭 `AgentTraceStore`。
- `backend/src/fae/channels/bridge.py` — `handle_inbound_text` 透传 `trace_turn_id`。

## 公共助手

- `backend/src/fae/sanitize.py` — `safe_text` / `safe_json` / `sanitize_value` 与共享正则。

## 验证

- `uv run pytest`：428 通过、覆盖率 79.73%（要求 ≥ 78%）。
- `pnpm lint` / `pnpm typecheck`：通过。

## 后续关联

- `可查询的 Agent 执行轨迹` 在 `doc/TODO.md` 中已标记为完成并归档。
- 可被“Agent 工作台式 FE 重构”与“主线/细节分层 Agent 执行视图”复用为数据源。
