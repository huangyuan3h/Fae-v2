# Sensitive / Dangerous 操作确认

**状态**：已完成  
**完成日期**：2026-07-26  
**TODO 等级**：P1 / 高 / 1–2 周 / 大

## 已交付

- 显式 **Tool Registry**（`fae.tool_registry`）：每个工具一份 `ToolSpec`，标注 `risk_tier ∈ {safe, caution, sensitive, dangerous}`、`requires_approval`、`needs_diff_preview`、`needs_double_confirm`、`channel_allowlist` 与 `default_ttl_s`。
  - `read_file / search_files / get_weather / request_skill / git_*` 默认 `safe`、免审批。
  - `write_file / edit_file / run_bash / cancel_job` 默认 `sensitive`、需要审批。
  - `make_directory / schedule_create_job / run_subagent` 默认 `caution`（可后续按需升 tier）。
- 独立的 `ApprovalStore`（SQLite WAL）：
  - 状态机：`pending → {approved, denied, expired, cancelled, superseded, awaiting_confirm}`，终态幂等。
  - 内部 `asyncio.Future` 注册表，调用方 `await request_approval(...)` 阻塞；审批到达后立即唤醒。
  - `sweep_expired()` 启动时清残留；`cancel_event` 与 chat cancel 联动。
  - 双确认流程（dangerous）：第一次 `approve` → `awaiting_confirm`；二次 `approve(confirm=True)` → `approved`。
- **HTTP 表面 `/api/approvals`**（独立 router，不绑 Web UI）：
  - `GET /api/approvals`（filter by session_id/tool_name/status/before/limit）
  - `GET /api/approvals/{id}`
  - `POST /api/approvals/{id}/decide`（body `action`, `reason?`, `confirm?`, `remember?`）
  - `POST /api/approvals/{id}/cancel`
  - `GET /api/approvals/capabilities` — 全量 `ToolSpec` 元数据
  - `GET/PATCH /api/sessions/{id}/policies` — always_allow / denied_tools
  - 错误：`400 bad_action`、`404 not_found`、`503 no_store`，均走已有 error 结构。
- **WebSocket 协议扩展**（SDK 与 web UI 同源同步）：
  - 服务端推送 `approval_request { approval, follow_up? }` 和 `approval_resolved { approval_id, tool_name, status, decision_reason, decided_by }`。
  - 客户端可发 `approval_decision { approval_id, action, reason?, confirm?, remember?, decided_by? }`。
- **ToolAudit 与 AgentTrace 联动**：
  - `tool_audit` 新增 `approval_id` 列；`approval_status` 已存在（`not_required` / `pending` / `approved` / `denied` / `expired` / ...）。
  - `agent_trace` 加入 `kind=approval`（`approval_request` / `approval_resolved` 自动归类）。
- **Session 预授权**：`Session.meta["approvals.always"]` 与 `["approvals.denied"]` 约定键，零侵入（即不改 dataclass）。
- **能力暴露**：`/api/capabilities` 新增 `tool_specs` 与 `approval_flow` 节，UI 可静态渲染"风险分级 + 是否需要审批"。
- **SDK TypeScript**（`sdk/typescript/src/{types,client,ws-chat}.ts`）：
  - 新类型：`WsServerMessage.approval_request | approval_resolved`、`WsClientMessage.approval_decision`、`ApprovalRequestMsg`、`ApprovalDecisionInput`、`SessionPolicies`、`ToolSpecSummary`。
  - 新方法：`FaeClient.listApprovals / getApproval / decideApproval / cancelApproval / getSessionPolicies / patchSessionPolicies / getToolSpecs / sendApprovalDecision`。

## 主要入口

- `backend/src/fae/tool_registry.py` — `ToolSpec` / `TOOL_SPECS` / `resolve_policy` / `effective_policy`。
- `backend/src/fae/approvals.py` — `ApprovalStore` / `ApprovalRequest` / `request_approval` / 双确认 + 过期扫描。
- `backend/src/fae/api/approvals.py` — HTTP 路由 + `/api/sessions/{id}/policies`。
- `backend/src/fae/agent/llm_turn.py` — `_dispatch_coding_tool` 与 `apply_lazy_skill_tool` 内置 gate；`stream_assistant_turn` 接受 `approval_store`/`effective_policy`。
- `backend/src/fae/api/ws.py` — 处理 `approval_decision` 客户端消息 + 转发 `approval_request`/`approval_resolved`。
- `backend/src/fae/api/__init__.py` — lifespan 初始化 `ApprovalStore`；启动时 sweep 残留；shutdown 关闭。
- `backend/src/fae/api/capabilities.py` — 暴露 `tool_specs` + `approval_flow`。
- `backend/src/fae/tool_audit.py` — 新增 `approval_id` 列 + 透传到 writer。
- `backend/src/fae/agent_trace.py` — 新增 `KIND_APPROVAL`。
- `sdk/typescript/src/{types,client,ws-chat}.ts` — 客户端 SDK 同步。

## 验证

- `uv run pytest`：**494 passed**（+42 新增），覆盖率 **79.60%**（要求 ≥ 78%）。
- `pnpm lint && pnpm typecheck`：通过（前端消费新 SDK 类型零报错）。
- 新增测试覆盖：
  - `tests/test_tool_registry.py`（11 项）— Spec / 策略解析 / 通道白名单 / diff preview。
  - `tests/test_approvals_store.py`（14 项）— 状态机 / 双确认 / 过期扫描 / 会话规则缓存。
  - `tests/test_approval_dispatch.py`（6 项）— `write_file` / `run_bash` 真路径下等待 / 拒绝 / 无 store 兜底。
  - `tests/test_approvals_api.py`（11 项）— REST 决定 / 取消 / 会话预授权 / 错误码。

## 后续关联

- 被 **外部 channel 闭环**（P1 / 高 / 1–2 周 / 大）直接复用：Telegram 等 channel 可通过 `POST /api/approvals/{id}/decide` 处理 `needs_input`。
- 与 **统一 Tool Registry**（P1 / 高 / 1 周 / 大）天然衔接：`TOOL_SPECS` 已作为最小可行 registry；后续将 `BASH_TOOLS` 等 list 改成 `define_tool(spec)` 工厂即可归并。
- 为 **删除文件 / git push 等 dangerous 工具**（当前未实现）预留好 `needs_double_confirm` + `double_confirm_window_s`，新增时只需在 `TOOL_SPECS` 注册即可。
