# Plan Mode · 用户 blocked 接续（Reengage）

> 2026-08 落地归档。承接 `doc/archive/PLAN_MODE.md` 的「用户消息解 blocked 后自动 unblock」与「FE 重连 plan_loaded 待完善」两条遗留。本期补足「blocked → 用户补充输入 → 重新推进」的完整闭环，并新增 HTTP 端点让 FE 在 WS 冷启动时即可恢复 active plan。

## 背景

`doc/TODO.md:24` 当前焦点：
> 复杂任务 Plan Mode 后续：补充用户 blocked 接上交互、Plan 手动编辑 / 取消 / 重排序以及跨 turn 续推的边界场景。

`doc/archive/PLAN_MODE.md:75-81` 「未实现 (Next Steps)」中与本归档相关的两条：
- ❌ 用户消息解 blocked 后自动 unblock（验收 4 的部分内容）
- 验收 4 中「FE 重连 plan_loaded 待完善」

本次只解决 blocked 接续与跨 turn 恢复这两个最小闭环。手动编辑 / 重排序 仍是 Backlog。

## 范围

- 后端：状态机扩展、Prompt 强约束、WS 入站新消息、HTTP 恢复端点。
- SDK：协议类型与客户端方法扩展。
- FE：PlanPanel 接入交互、useVoiceSession 拉取 active plan。

## 后端改动

### 数据层 `backend/src/fae/plans.py`

- `unblock_step(step_id, note: str | None = None)`：`note` 提供时覆盖式写入 pending 步骤的 note，未提供时保留旧 note（向后兼容）。
- 新增 `append_step_note(step_id, note)`：不改 status，把 `note` 追加到现有内容（用于「pending 步骤接收上下文」场景，避免与 unblock 混淆）。

### 工具层 `backend/src/fae/agent/plan_tools.py`

- `UPDATE_PLAN_TOOL` schema description：显式加入「reengage rule」——若 `<active_plan>` 含 blocked 且用户给出回复，必须先 `action=unblock, step_index=N, note=<答案>` 再 claim/complete。
- `unblock` action 现在支持 `note=`：dispatcher 把 LLM 给的 user answer 直接落入 step row。
- `_PLAN_MODE_INSTRUCTION`：加入 reengage rule，引导 LLM 在 system prompt 阶段就看到这一约束。
- 新增 `find_blocked_steps(plan)` 与 `user_response_for_blocked_block(plan)`：当 active plan 含 blocked step 时，向 system message 注入 `<user_response_for_blocked>` 块，明确告诉 LLM「把本轮 user 文本视作对 blocked step 的回答」。

### WS `backend/src/fae/api/ws.py`

- `_run_stream`：在 `<active_plan>` 之后拼接 `<user_response_for_blocked>` 块，让 blocked 上下文直达 LLM。
- 新增入站消息 `plan_step_input`（拆出独立 helper `_handle_plan_step_input` 便于单测）：
  - `kind=answer` + 目标 blocked → `unblock_step(note=input_text)`
  - `kind=answer` + 目标 pending → `append_step_note(input_text)`
  - `kind=abort` + 任意 blocked/pending → `cancel_step(note=input_text)`
  - 错误时返回 `bad_request` / `not_found` / `not_blocked` / `plan_step_input_failed`。
- 出站新增 `plan_step_input_ack` 帧：含 `plan` 与 `step` payload，FE 用其覆盖本地 plan state。
- 协议 docstring（顶部）已同步更新。

### HTTP `backend/src/fae/api/plans.py`（新文件）

- `GET /api/plans/active?session_id=...` → `{plan: PlanPayload | null, session_id}`。
- `POST /api/plans/{plan_id}/abandon` → 弃用 active plan，让新 plan 可被同 session 创建。
- 错误：404（plan 不存在）、409（plan 非 active）、503（store 不可用）。

## SDK `sdk/typescript/src/{types.ts,ws-chat.ts}`

- `WsServerMessage` 增加 `plan_step_input_ack` 帧。
- `WsClientMessage` 增加 `plan_step_input` 出站消息。
- `StreamHandlers` 增加 `onPlanStepInputAck`。
- `WsChatClient` 增加 `sendPlanStepInput(planId, stepIndex, inputText, kind, sessionId?)`。

## FE `ui/src/{components/voice/PlanPanel.tsx, hooks/useVoiceSession.ts, lib/ws-chat.ts, app/page.tsx}`

- `lib/ws-chat.ts` 导出 `fetchActivePlan(sessionId)` 与 `abandonPlan(planId)`；`WsChatClient` 暴露 `sendPlanStepInput`。
- `hooks/useVoiceSession.ts`：
  - `loadSession(sid)` 在清空 plan 之后立即 `fetchActivePlan(sid)` 重新拉取并填充 `activePlan`，实现「切 session 即看到计划」。
  - 暴露 `provideStepInput(planId, stepIndex, text, kind)` 与 `abandonActivePlan(planId)`。
  - WS handler 路由 `plan_step_input_ack` → 覆盖本地 plan。
- `PlanPanel`：
  - 顶部新增 `n 项阻塞` 红色徽章 + 「放弃计划」按钮。
  - 每个 blocked step 渲染红色边框与红色「!」图标，并新增两个动作：
    - 「补一条说明」：展开内联 textarea，提交后调 `provideStepInput(kind=answer)`。
    - 「取消这一步」：直接调 `provideStepInput(kind=abort)`。
- `app/page.tsx` 把 `provideStepInput` / `abandonActivePlan` 注入 PlanPanel。

## 测试

新增 / 调整：

- `backend/tests/test_plans_reengage.py`（18 例）：
  - `unblock_step(note=)` 覆盖与保留旧 note 两种行为
  - `append_step_note` 不改 status、保留旧 note
  - `cancel_step` 覆盖 note
  - `find_blocked_steps` 仅返回 blocked；completed plan 永远空
  - `user_response_for_blocked_block` 含 blocked 步骤的 `step_index` 与 `last_block_reason`
  - `_handle_plan_step_input` 三种 happy path（answer on blocked / abort / answer on pending）以及错误路径（completed 拒绝、bad kind 拒绝）
- `backend/tests/test_plan_api.py`（4 例）：GET active 三态、POST abandon 200/404。
- 既有 `tests/test_plans.py` / `tests/test_plan_tools.py` 全部 29 例通过。
- 后端整体 579 例通过，覆盖率 78.94%（>78% 阈值）。
- FE：`pnpm typecheck` / `pnpm lint` / `pnpm build` 均通过。

## 验收

按 `doc/TODO.md` 维护规则对齐：

- 用户在阻塞状态下用 PlanPanel 按钮输入补充说明 → 当轮即可看到 step 转 pending 并保留其答案作为 note → 后续 turn LLM 直接 `claim/complete`。
- 用户选择「取消这一步」→ step 进入 cancelled 并附 abort 原因。
- 用户刷新页面或切 session → PlanPanel 在用户未发消息前即渲染 active plan（含 blocked 行的视觉区分）。
- 后端日志层面无 LLM「忽略 blocked 直接推进下一条」的情况（因为 system 块 + tool description 都强制 unblock 在前）。
- 「放弃计划」可正常释放，让新的 multi-step 请求触发新的 plan。

## 仍未覆盖（保留给下一阶段）

- Plan 手动编辑（修改 step title / acceptance）
- Plan 重排序（变更 step 顺序）
- Telegram / 外部 channel 接收 blocked 通知与回填（见 `doc/TODO.md:178` 外部 channel 闭环）
- 评测 harness：blocked reengage 的离线回归（见 `doc/TODO.md:142` Context Engineering 集成评测）