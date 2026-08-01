# Plan Mode · 手动编辑与重排序

> 2026-08 落地归档。承接 `doc/TODO.md:91-108` 的「Plan Mode · 手动编辑与重排序」。在 user-reengage（`doc/archive/PLAN_MODE_REENGAGE.md`）的基础上把 PlanPanel 从「只读 + 单向驱动」升级为「用户可参与结构」。

## 背景

`doc/TODO.md:91-108`：

- 状态：待开始
- 验收：
  1. 用户在不重启对话的前提下修订计划细节
  2. 重排序后 step index 与 note 持久化到 SQLite，跨 turn 与刷新可见
  3. LLM 下一轮拿到的 `<active_plan>` 与用户编辑后保持一致

之前 PlanStore 已具备 step claim/complete/block/unblock/cancel；FE PlanPanel 只渲染 + 弃用按钮 + blocked 行交互。但缺：

1. `edit_step(step_id, title=None, acceptance=None)` —— 改 title/acceptance 不改 status/note/idx
2. `reorder_step(step_id, new_index)` —— 改 idx 不改 status/note；schema 无 `(plan_id, idx)` UNIQUE，需事务内 swap
3. HTTP 端点 `PATCH /api/plans/{plan_id}/steps/{step_id}` 与 `POST /api/plans/{plan_id}/reorder`
4. SDK helper `editPlanStep / reorderPlanStep`
5. FE PlanPanel 就地编辑 title/acceptance UI + ↑/↓ 重排序按钮

## 范围

- `plans.py`：`edit_step` + `reorder_step`（3 步 swap 事务）
- `api/plans.py`：新增两个端点 + Pydantic schemas
- `ui/src/lib/ws-chat.ts`：`editPlanStep` / `reorderPlanStep` HTTP helper
- `ui/src/hooks/useVoiceSession.ts`：暴露 `editPlanStepField` / `reorderPlanStepBy`
- `ui/src/components/voice/PlanPanel.tsx`：就地编辑 title/acceptance + ↑/↓ 按钮
- `ui/src/app/page.tsx`：注入新回调

## 后端改动

### `backend/src/fae/plans.py`

**`edit_step(step_id, *, title=None, acceptance=None)`**：
- 拒绝 terminal step（completed / cancelled），抛 `InvalidPlanTransition`。
- 至少传入一个字段；空串视作「清空」。
- 只更新 title/acceptance，**不动 status / note / idx / timestamps**。
- 原子 SQL UPDATE，刷新 `plans.updated_at`。

**`reorder_step(step_id, new_index)`**：
- 0-based 范围校验 `0 <= new_index < N`；`new_index == old_idx` 直接 no-op 返回。
- 拒绝 terminal step。
- `BEGIN IMMEDIATE` 事务内三步：
  1. 把被移动 step 写到 `-1` 哨兵位
  2. 范围 shift：
     - `old_idx < new_index` → `idx > old_idx AND idx <= new_index` 减 1
     - `old_idx > new_index` → `idx >= new_index AND idx < old_idx` 加 1
  3. 把被移动 step 写到 `new_index`
- 不动 status / note / started_at / finished_at。

> **关键设计**：schema 无 `(plan_id, idx)` UNIQUE，所以「真 swap」必须事务内执行。`-1` 哨兵确保范围 UPDATE 不会回碰到被移动 step。SQLite WAL 串行化写者，并发 reorder 不会出现重复 idx。

### `backend/src/fae/api/plans.py`

新增：

```text
PATCH /api/plans/{plan_id}/steps/{step_id}
  body: { title?: string, acceptance?: string }
  → 200 {plan: ...}
  → 400 no_fields / bad_request
  → 404 plan_not_found / step_not_in_plan
  → 409 not_active / step_terminal

POST /api/plans/{plan_id}/reorder
  body: { step_id: string, new_index: int (0..10000) }
  → 200 {plan: ...}
  → 400 out_of_range
  → 404 plan_not_found / step_not_in_plan
  → 409 not_active / step_terminal
```

`StepEditBody` / `StepReorderBody` 用 Pydantic + Field 约束（顺手把同包 `plans.py` 从无 schema 的 `dict[str, Any]` 升级到 Pydantic，风格统一）。

### `ui/src/lib/ws-chat.ts`

```ts
export type StepEditPatch = { title?: string; acceptance?: string };
export async function editPlanStep(
  planId: string, stepId: string, patch: StepEditPatch
): Promise<PlanPayload>;
export async function reorderPlanStep(
  planId: string, stepId: string, newIndex: number
): Promise<PlanPayload>;
```

返回最新 plan；调用方负责 `setActivePlan(next)`。

### `ui/src/hooks/useVoiceSession.ts`

新增两个 callback：

```ts
const editPlanStepField = useCallback(
  async (planId, stepId, patch: StepEditPatch): Promise<boolean> => {
    try { setActivePlan(await editPlanStep(planId, stepId, patch)); return true; }
    catch { return false; }
  }, []);
const reorderPlanStepBy = useCallback(
  async (planId, stepId, newIndex): Promise<boolean> => { /* ... */ }, []);
```

暴露在 hook 返回值。失败返回 `false`，调用方回滚 UI 草稿。

### `ui/src/components/voice/PlanPanel.tsx`

`StepRow` 升级：
- title 改为可点击 `<button>`（非 terminal 时显示 affordance）；点击切到 `<input>`，blur/Enter 提交，Esc 取消。`canEdit = status !== completed && status !== cancelled`。
- acceptance 行同步升级为可点击 → input 模式。
- 行尾新增 ↑ / ↓ 按钮（`canReorder` 时显示），点击调 `onReorderPlanStep(planId, stepId, stepIndex ± 1)`；边界禁用。
- terminal step 仍可读但不可编辑/重排。

### `ui/src/app/page.tsx`

注入 `editPlanStepField` / `reorderPlanStepBy` 到 `<PlanPanel />`。

## 测试

新增 `backend/tests/test_plans_edit_reorder.py`（30 例）：

**Store 层（21 例）**
- `test_edit_step_updates_title_and_acceptance`
- `test_edit_step_partial_title_only` / `test_edit_step_partial_acceptance_only`
- `test_edit_step_empty_string_clears_field`
- `test_edit_step_no_fields_raises`
- `test_edit_step_rejects_completed` / `test_edit_step_rejects_cancelled`
- `test_edit_step_unknown_step_raises`
- `test_edit_step_preserves_idx_and_note`（验收 2 基础）
- `test_edit_step_during_blocked_is_allowed`（与 reengage 兼容）
- `test_reorder_step_swap_two_adjacent` / `test_reorder_step_move_to_end` / `test_reorder_step_move_to_front`
- `test_reorder_step_same_index_is_noop`
- `test_reorder_step_out_of_range_raises`
- `test_reorder_step_rejects_completed` / `test_reorder_step_rejects_cancelled`
- `test_reorder_step_preserves_note`（验收 2）
- `test_reorder_step_unknown_step_raises`

**LLM 视图一致性（1 例）**
- `test_active_plan_block_reflects_edit_and_reorder`：edit + reorder 后 `active_plan_as_prompt_block(plan)` 含新 title 与新 idx（验收 3）。

**HTTP 层（8 例）**
- `test_http_edit_step_returns_updated_plan`
- `test_http_edit_step_rejects_completed` (409 step_terminal)
- `test_http_edit_step_no_fields_400`
- `test_http_edit_step_unknown_plan_404`
- `test_http_edit_step_step_not_in_plan_404`
- `test_http_reorder_step_returns_updated_plan`
- `test_http_reorder_step_out_of_range_400`
- `test_http_reorder_step_rejects_terminal` (409)
- `test_http_reorder_step_unknown_plan_404`
- `test_http_edit_then_reorder_round_trip`（编辑 → 重排 → `GET /active` 反映新 title 与新 idx，验收 1+2+3）

后端整体 **637** 例通过（+30），覆盖率 **79.11%**（>78% 阈值）。
FE：`pnpm typecheck` / `pnpm lint` / `pnpm build` 全部通过。

## 验收对齐

- ✅ **用户在不重启对话的前提下修订计划细节**：
  - HTTP `PATCH /api/plans/{plan_id}/steps/{step_id}` 接受 `{title, acceptance}` 任意子集。
  - FE PlanPanel 点击 title / 验收条件行 → 内联 input → blur 提交。
  - 失败回滚草稿（`editPlanStepField` 返回 `false` 时 `setTitleDraft(step.title)`）。

- ✅ **重排序后 step index 与 note 持久化到 SQLite，跨 turn 与刷新可见**：
  - `test_reorder_step_preserves_note`：note 不被移动操作清掉。
  - `test_http_edit_then_reorder_round_trip`：编辑 + 重排后 `GET /active` 反映新 title 与新 idx。
  - SQLite WAL 持久化，进程重启 / session 切换后 loadSession 通过 `fetchActivePlan` 重新拉取。

- ✅ **LLM 下一轮拿到的 `<active_plan>` 与用户编辑后保持一致**：
  - `test_active_plan_block_reflects_edit_and_reorder`：直接断言 `active_plan_as_prompt_block(refreshed)` 含新 title / 新 idx。
  - 机制层面：每次 chat turn `_run_stream` 重新读 `plan_store.to_dict(active_plan)` 并 emit `plan_loaded` 帧，prompt 块基于最新内存对象渲染（`plan_tools.py:283-305`）。

## 仍未覆盖（保留给后续）

- **拖拽重排序**：当前是 ↑/↓ 按钮。DnD 列入 P2 体验增强。
- **计划回滚 / 历史快照**：用户编辑 / 重排没有 undo。FE 可加 history list，但需求范围之外。
- **同时多端编辑冲突**：当前进程内锁 + SQLite WAL 串行化足够单进程；多 worker 部署需要 lease（与 Task reliability 同源问题）。