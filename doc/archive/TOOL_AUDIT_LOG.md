# 持久工具审计日志

**状态**：已完成  
**完成日期**：2026-07-26

## 已交付

- 独立 SQLite `ToolAuditStore`，支持工具调用的 start、done、error 生命周期。
- 记录 session、channel、channel_id、工具名、参数摘要、结果摘要、错误码、耗时和批准状态。
- 覆盖 coding、schedule、weather、subagent、request_skill 等工具分支。
- HTTP、WebSocket、Telegram 调用写入统一审计链路。
- 参数和结果做敏感字段脱敏与长度限制，审计写入失败不会阻断正常工具执行。
- 新增 `GET /api/tool-audit`，支持按 session、工具、channel、phase、时间游标和数量查询。
- 增加 SQLite store、API 和现有 coding tool loop 测试。

## 主要入口

- `backend/src/fae/tool_audit.py`
- `backend/src/fae/api/tool_audit.py`
- `backend/src/fae/agent/llm_turn.py`
- `backend/src/fae/api/__init__.py`
- `backend/src/fae/api/ws.py`
- `backend/src/fae/channels/bridge.py`

## 验证

- `uv run pytest`
- 417 passed
- 覆盖率 79.51%

## 后续关联

- Sensitive / Dangerous 操作确认仍在 `doc/TODO.md` 中维护。
- Agent 工作台与主线/细节分层视图可消费 `GET /api/tool-audit` 的审计数据。
