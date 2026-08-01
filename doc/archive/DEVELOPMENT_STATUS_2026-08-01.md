# Development Status — 2026-08-01

> 本文归档 2026-08-01 TODO 整理时已完成的开发事项，并作为当前版本基线索引。后续未完成工作只在 [`../TODO.md`](../TODO.md) 维护。

## 当前发布基线

- FAE-v2 当前稳定版本为 `0.6.0`。
- README、Backend、UI、TypeScript SDK、Python 包和 FastAPI app 的版本号已统一。
- Git tags `v0.4.0`、`v0.5.0`、`v0.6.0` 已补齐。
- 29 个 Markdown 文件的相对链接曾完成一次性扫描和修复；持续 CI 校验仍作为后续工作维护。

## 已完成能力索引

| 能力 | 状态 | 归档记录 |
|---|---|---|
| Phase 1–5.2：语音、记忆、Skills、主动 Loop、PWA、Telegram、Subagents | 已完成首版 | [`DEVELOPMENT_PLAN_through_v0.2.md`](./DEVELOPMENT_PLAN_through_v0.2.md) |
| P6 常驻 Core、P7 thin client 契约 | 已完成 | [`DEVELOPMENT_PLAN_through_P7.md`](./DEVELOPMENT_PLAN_through_P7.md) |
| Agent 工作台 FE 重构 | 已完成 | [`AGENT_WORKBENCH_FE.md`](./AGENT_WORKBENCH_FE.md) |
| 主线与细节分层的 Agent 执行视图 | 已完成 | [`AGENT_EXECUTION_VIEW.md`](./AGENT_EXECUTION_VIEW.md) |
| Plan Mode MVP | 已完成 | [`PLAN_MODE.md`](./PLAN_MODE.md) |
| Plan Mode blocked 接续与刷新恢复 | 已完成 | [`PLAN_MODE_REENGAGE.md`](./PLAN_MODE_REENGAGE.md) |
| Plan Mode 手动编辑与重排序 | 已完成 | [`PLAN_MODE_EDIT.md`](./PLAN_MODE_EDIT.md) |
| Tool Registry | 已完成 | [`TOOL_REGISTRY.md`](./TOOL_REGISTRY.md) |
| Sensitive / Dangerous 操作审批 | 已完成 | [`SENSITIVE_OPS_APPROVAL.md`](./SENSITIVE_OPS_APPROVAL.md) |
| Tool Audit Log | 已完成 | [`TOOL_AUDIT_LOG.md`](./TOOL_AUDIT_LOG.md) |
| 可查询的 Agent Trace | 已完成 | [`AGENT_TRACE.md`](./AGENT_TRACE.md) |
| Tool Result Offload 可恢复性 | 已完成 | [`TOOL_RESULT_OFFLOAD.md`](./TOOL_RESULT_OFFLOAD.md) |
| Rolling Summary 生命周期 | 已完成 | [`ROLLING_SUMMARY_LIFECYCLE.md`](./ROLLING_SUMMARY_LIFECYCLE.md) |
| 持久 Task 状态机 | 已完成 | [`TASK_STATE_MACHINE.md`](./TASK_STATE_MACHINE.md) |
| Task 幂等、CAS、进度、重试与错误历史 | 已完成 | [`TASK_RELIABILITY.md`](./TASK_RELIABILITY.md) |
| 一键遗忘 | 已完成 | [`ONE_CLICK_FORGET.md`](./ONE_CLICK_FORGET.md) |
| Context Engineering R1–R6 基础实现 | 已完成首版 | [`CONTEXT_ENGINEERING_RESEARCH_2026-07-26.md`](./CONTEXT_ENGINEERING_RESEARCH_2026-07-26.md) |

## 状态判断

项目已具备个人 AI 助手所需的大部分基础积木，但尚未组成统一的后台工作系统：

- Plan、Task、Approval、Trace、Audit、Memory 与 Context Engineering 已分别落地。
- 当前 Subagent 仍在主工具循环内等待，Schedule、Connector 和 Subagent 尚未统一接入持久 worker。
- 当前 LLM usage 主要是进程级累计，尚不能验证前台约 10%、后台绝大多数 token 的目标。
- 真实个人连接器、外部 channel 的 `needs_input` 闭环、真实语音质量和生产级集成评测尚未完成。
- Agent 工作台已解决首轮信息层级，但后台任务中心、移动端主次体验、视觉一致性和声音系统仍需继续设计。

因此，下一阶段不再以增加零散功能数量为主，而是优先完成：token 归因与预算、可恢复后台工作平面、个人助手 Golden Path、真实声音与 UI 日常体验。
