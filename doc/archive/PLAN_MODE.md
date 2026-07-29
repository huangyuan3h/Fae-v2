# 复杂任务 Plan Mode — 归档记录

**完成日期**：2026-07-26
**重要等级**：P1
**收益程度**：高
**改动量**：特大
**范围**：本次交付 MVP（自动识别 + create/claim/complete/block/cancel + 跨 turn 续推 + FE PlanPanel）。手动编辑 / 重排序 / blocked 用户接上交互留作下一阶段。

## 目标

让复杂任务像主流 Agent 产品一样：先列 Todo、再按状态机推进，跨 turn 可恢复；用户在右侧 PlanPanel 看到实时进度。

## 触发模式选择

按用户决策采用**自动识别**（每个 turn 前做轻量 LLM 判定，max_tokens=4），可通过 `plan_auto_detect_enabled` 配置关掉。Plan 工具常驻可用，模型可以主动调用。

## 后端架构

### 持久层
- `backend/src/fae/plans.py` — `PlanStore` (SQLite, WAL)
  - `plans` 表 + `plan_steps` 表
  - Plan 状态机：`active` | `completed` | `abandoned`
  - Step 状态机：`pending` → `in_progress` / `blocked` / `cancelled` / `completed`
  - `claim_step` 自动将上一个 `in_progress` 标记为 `completed`（last-write-wins）
  - 所有 step 终态时 plan 自动 `completed`
  - 创建新 plan 会自动 abandon 同 session 的旧 active plan
- `data_deletion.py` 已接入 clear() — 一键遗忘会同时清 plans

### Plan 工具
- `backend/src/fae/agent/plan_tools.py`
  - `UPDATE_PLAN_TOOL` OpenAI schema（6 个 action：create / claim / complete / block / unblock / cancel）
  - `dispatch_update_plan` 同步入口，分发到对应 store 方法
  - `PlanToolEvent` 事件：server → WS 层通知 FE
  - `active_plan_as_prompt_block(plan)` — 把活跃 plan 渲染成 `<active_plan>` XML 块注入 system prompt
  - `should_auto_plan(client, config, user_text)` — 轻量 LLM 判定（YES/NO），max_tokens=4
  - `inject_plan_directive(request)` — 给 system message 加上一段"先发计划再执行"的指令，幂等

### 协议层
- 工具常驻：`tool_registry.specs_in_group("plan")` 注册 update_plan，所有 chat 调用都能看到
- WS 新消息类型：
  - `plan_loaded {type, plan}` — 跨 turn 续推时一次性同步给 FE
  - `plan_suggested {type, user_text}` — 后端判定应该进入 Plan Mode 时给 FE 提示
  - `plan_created {type, plan_id, plan}` — LLM 发起新 plan
  - `plan_step_update {type, plan_id, plan, step}` — claim / block / unblock
  - `plan_step_completed {type, plan_id, plan, step}` — complete / cancel，自动判定 plan 是否 done
- SDK 同步：`sdk/typescript/src/types.ts` 新增 `PlanPayload`、`PlanStepPayload`、`PlanStatus`、`PlanStepStatus` 类型 + `StreamHandlers.onPlanLoaded/onPlanCreated/onPlanStepUpdate/onPlanStepCompleted/onPlanSuggested`

## 前端架构

### 新组件
- `ui/src/components/voice/PlanPanel.tsx`
  - 三态：`empty`（无 plan + 无建议）、`suggested`（后端判定需要计划）、`populated`（已有 plan）
  - 步骤行：图标（○ ▶ ✓ ! ×）+ 标题 + 状态徽章 + 验收条件 + 阻塞原因
  - 进度计数 `done/total`，徽章在 in_progress 时 pulse
  - 完成状态徽章在 done 时切换为 green
- 集成位置：`ui/src/app/page.tsx` 右侧 sidebar，PlanPanel 在 ExecutionPanel 上方

### Hook 状态
- `useVoiceSession` 暴露 `activePlan` 和 `planSuggested`
- 新增 WS 处理器：`onPlanLoaded`、`onPlanCreated`、`onPlanStepUpdate`、`onPlanStepCompleted`、`onPlanSuggested`
- 完成时 1.5s 后自动清空（让用户看一眼完成态）
- `loadSession` 时清空 plan 状态

## 用户视角（验收 1/2/5 满足）

| 场景 | 行为 |
|---|---|
| 多步任务 | 自动识别 → 模型被引导调用 `update_plan(create, ...)` → FE PlanPanel 显示计划 → 后续 step 自动推进 |
| 单步任务 | 自动识别返回 NO → 不进入 plan 模式 |
| 跨 turn | 上一个 turn 创建的 plan 持续存在，下一个 turn 开始时 `<active_plan>` 注入 prompt + FE 通过 `plan_loaded` 同步 |
| 完成 | 所有 step 终态时 plan 自动 complete，FE 显示完成态，1.5s 后清空 |
| blocked | Agent 调用 `update_plan(block, ...)` → FE 该步骤显示红色 + 原因 |
| 刷新 / 重启 | Plan 持久化在 SQLite，刷新页面 `/api/chat/history` 重新加载时同步给 FE |

## 未实现（Next Steps）

- ❌ 用户手动编辑 step 标题 / 验收条件（验收 3 的部分内容）
- ❌ 重排序 / 取消后续步骤（验收 3 的部分内容）
- ❌ 用户消息解 blocked 后自动 unblock（验收 4 的部分内容）
- ❌ Plan dedup / 复用：把已完成的 plan 存为 skill，下次相似任务直接 load

## 测试

- 22 个 backend 测试覆盖 `PlanStore` + `dispatch_update_plan` + auto-detect + directive 注入
- `data_deletion.py` 测试加上 plans 后全部通过
- Phase 4 regression 测试加上 `closed` 属性后通过
- 536 个 backend 测试 + UI build + lint 全部通过

## 验收对应

- ✅ 验收 1（多步任务先展示计划） — auto-detect 触发 → model 自动 publish
- ✅ 验收 2（执行期间 Todo 状态按顺序变化） — claim/complete/block/cancel 都有专用 action
- ⏳ 验收 3（用户修改 / 取消 / 重排序步骤） — 部分（取消已支持，编辑/重排序下一阶段）
- ⏳ 验收 4（刷新 / 重启后计划可恢复） — 持久化完成；FE 重连时再次 plan_loaded 同步（待 FE 端完善）
- ✅ 验收 5（最终回复汇总完成项 / 未完成项） — server side 已就位