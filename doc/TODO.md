# FAE-v2 TODO

> 本文件是未完成功能的唯一维护入口。已完成内容移入 `archive/`；设计方案放入 `design/`；当前架构与模块索引放入 `architect/`；运维文档放入 `operations/`。

## 维护规则

- 这里只记录尚未完成、需要持续关注的 feature。
- 每项必须包含状态、重要等级、收益程度、预计时间、改动量和可验证的验收条件。
- 开始开发时将状态改为「进行中」；完成并验证后，从本文件移除并写入 `archive/` 对应阶段记录。
- 设计细节写入 `design/`，本文件只保留目标、范围和验收条件。
- 优先级顺序：P0 阻塞项 → P1 高需求 → P2 体验增强 → Backlog 按需。

### 评估口径

| 维度 | 分级 | 说明 |
|---|---|---|
| 重要等级 | P0 / P1 / P2 | P0 阻塞发布或基础能力；P1 核心产品能力；P2 体验、质量或增强能力 |
| 收益程度 | 高 / 中 / 低 | 对核心使用频率、可用性、可靠性和用户体验的综合收益 |
| 预计时间 | 工作日 / 周 | 单人完成首个可验收版本的粗略估算，不含长期打磨 |
| 改动量 | 小 / 中 / 大 / 特大 | 涉及文件数量、跨端协作、数据模型和兼容性风险的综合估算 |

## 当前焦点

1. **Plan Mode · 手动编辑 / 重排序 / 外部 channel 闭环**：把 PlanPanel 升级为可编辑（修改 step title / acceptance、调整顺序），并让 Telegram / 外部 channel 能复用 blocked reengage（见 `doc/TODO.md:178`）。在 user-reengage（已归档）的基础上，把 plan 从「只读 + 单向驱动」升级为「用户可参与结构」。

## P0 · 文档与发布完整性

### 统一版本状态

- **状态**：已完成
  - 所有版本号统一到 0.6.0（README / pyproject.toml / package.json x2 / __init__.py / FastAPI app）
  - 补打缺失 Git tags：v0.4.0、v0.5.0、v0.6.0

### 文档自动校验

- **状态**：已完成
  - 扫描 29 个 Markdown 文件，所有相对链接有效
  - 修复 `doc/architect/ARCHITECTURE.md` Section 5 目录树（~25 个 aspirational 路径替换为实际结构）
  - Python `doc/...` 引用、模块导入路径全部有效

## P1 · 核心产品体验

### Agent 工作台式 FE 重构

- **状态**：已完成（归档见 `doc/archive/AGENT_WORKBENCH_FE.md`）

### Agent 工作台式 FE 视觉打磨 2.0

- **状态**：待开始
- **重要等级**：P1
- **收益程度**：高
- **预计时间**：1–2 周
- **改动量**：中
- **用户感受**：1.x 解决了信息层级（细分了三栏、去掉了居中巨标题），但视觉质感还不够 — 缺少呼吸感、动画过渡和细节高光，远未达到 Cursor / Codex / Linear 一类产品的「看得舒服」水准。
- **需求**：
  - 制定一组 design tokens（间距阶梯、半径梯度、阴影层级、动效曲线），并替换页面里的临时内联样式。
  - 给对话气泡、状态切换、审批审批通过 / 拒绝等关键事件补上轻微的 micro-animation（fade / scale / shimmer），避免突兀跳变。
  - 把 VoiceOrb / StatusChip 与背景融合做一次视觉提升（pending 时整页有微弱 glow，而不是孤立的小点）。
  - 重新打磨首页空状态（无历史对话时）：由 `Composition` 引导而非仅一个 textarea。
  - 给 macOS Safari 与 iOS Safari 做一次视觉走查，修复安全区、滚动橡皮筋、被 Safari 工具栏遮挡的 footer。
  - 补一组可复用的 Empty / Skeleton / Toast / Tooltip 原语，避免再次回到「页内拼样式」。
  - 视觉走查产出 before/after 截图与对比清单，并沉淀 1–2 套参考样式（Cursor、Linear、Claude）。
- **验收**：
  - 用户观感明显改善，给非团队成员看截图能立即感受到「专业产品」的气场。
  - 设计令牌、动画时长、空状态都成为可复用资源，后续添加新页面不再返工样式。
  - 桌面与移动端视觉走查通过，pnpm lint / typecheck / build 全部通过。

### 复杂任务 Plan Mode

- **状态**：已完成（归档见 `doc/archive/PLAN_MODE.md`）

### Plan Mode · 用户 blocked 接续

- **状态**：已完成（归档见 `doc/archive/PLAN_MODE_REENGAGE.md`）
- **重要等级**：P1
- **收益程度**：高
- **预计时间**：3–5 个工作日
- **改动量**：中
- **需求**：
  - 后端：`unblock_step(note=)` 覆盖 note；`append_step_note` 不改 status；Prompt 强约束 reengage rule；`<user_response_for_blocked>` 注入 system 块。
  - WS：新增入站 `plan_step_input`（answer / abort）与出站 `plan_step_input_ack`。
  - HTTP：新增 `GET /api/plans/active` 与 `POST /api/plans/{plan_id}/abandon`。
  - SDK：`WsClientMessage` / `WsServerMessage` 扩展 + `WsChatClient.sendPlanStepInput`。
  - FE：PlanPanel 在 blocked step 上加「补一条说明 / 取消这一步」按钮；`useVoiceSession.loadSession` 自动 `fetchActivePlan` 拉取；新方法 `provideStepInput` / `abandonActivePlan`。
- **验收**：
  - blocked step 在 PlanPanel 中显红、可被输入或一键取消，输入后转 pending 并保留 note。
  - 切 session / 刷新后无需先发 chat 即可看到 active plan。
  - 「放弃计划」可正确释放 plan 占位。
  - 后端 579 例测试通过；FE `pnpm typecheck/lint/build` 通过。

### Plan Mode · 手动编辑与重排序

- **状态**：待开始
- **重要等级**：P1
- **收益程度**：中
- **预计时间**：1–2 周
- **改动量**：中
- **用户感受**：当前 PlanPanel 仍为只读结构；若用户想细化任务或调整顺序必须新开对话，体感上「计划是我不能改的公告」而非「我们一起维护的清单」。
- **需求**：
  - 后端：新增 `edit_step(step_id, title=None, acceptance=None)` 与 `reorder_step(step_id, new_index)`；状态机不破坏现有约束（不允许把 completed / cancelled 步骤重排）。
  - HTTP：`PATCH /api/plans/{plan_id}/steps/{step_id}` 与 `POST /api/plans/{plan_id}/reorder`。
  - SDK：补齐对应类型与方法。
  - FE：PlanPanel 支持就地编辑 title / acceptance，长按拖拽或上/下箭头调整顺序。
  - LLM 看到用户改写后的 plan：`<active_plan>` 块每次 `plan_loaded` 与 step update 都重渲染。
- **验收**：
  - 用户可以在不重启对话的前提下修订计划细节。
  - 重排序后 step index 与 note 持久化到 SQLite，跨 turn 与刷新可见。
  - LLM 下一轮拿到的 `<active_plan>` 与用户编辑后保持一致。

### 主线与细节分层的 Agent 执行视图

- **状态**：已完成（归档见 `doc/archive/AGENT_EXECUTION_VIEW.md`）

## P1 · Tool Runtime 安全与产品化

### 统一 Tool Registry

- **状态**：已完成（归档见 `doc/archive/TOOL_REGISTRY.md`）

### Sensitive / Dangerous 操作确认

- **状态**：已完成（归档见 `doc/archive/SENSITIVE_OPS_APPROVAL.md`）

### 真实个人连接器

- **状态**：待开始
- **重要等级**：P1
- **收益程度**：高
- **预计时间**：2–4 周
- **改动量**：特大
- **需求**：按实际使用频率接入至少三个连接器，优先日历、邮件和通用 webhook。
- **验收**：至少三个真实个人工具可稳定调用，权限和失败状态清晰。

### 工具结果回灌记忆

- **状态**：待开始
- **重要等级**：P1
- **收益程度**：中
- **预计时间**：1–2 周
- **改动量**：中
- **需求**：定义哪些结果形成 fact、episodic event、archival artifact 或临时输出。
- **验收**：关键工具结果第二天仍可 recall，并保留来源信息。

## P1 · Context Engineering 正确性

### Rolling Summary 生命周期

- **状态**：已完成（归档见 `doc/archive/ROLLING_SUMMARY_LIFECYCLE.md`）
- **重要等级**：P1
- **收益程度**：中
- **预计时间**：3–5 个工作日
- **改动量**：中
- **需求**：
  - `RecallStore`：新增 `recall_summary_batches` 表 + `recall_turns.summary_batch_id` 列；提供 `peek_oldest_uncovered` / `commit_summary_batch` / `latest_batch` / `find_batch_by_fingerprint` 原子方法。
  - `RollingSummarizer`：按 `(session_id, ordered_turn_ids)` 算 fingerprint；命中已有 batch 返回 `skipped="already_committed"` 不调 LLM；新 batch 把上一轮 `summary_text` 注入 prompt；archival 用 deterministic `point_id`（UUID5）。
  - `MemoryCompactor`：`peek_oldest_uncovered` 跳过已被认领的 turn；作为 raw 兜底保留。
  - `LettaMemoryService.persist_turn`：顺序改为 summarizer → compactor。
- **验收**：
  - 同 hot 窗口连续两次 `maybe_summarize` 第二次 `skipped="already_committed"`，`provider.calls` 仍为 1，archival / batches 仍为 1 行。
  - 第二轮 prompt 含 `<previous_summary>` + 第一轮 `summary_text`，关键事实不丢。
  - compactor raw 归档文本中不含任何被 claim 的 turn id。
  - 后端 585 例测试通过，覆盖率 79.02%。

### Tool Offload 可恢复性

- **状态**：已完成（归档见 `doc/archive/TOOL_RESULT_OFFLOAD.md`）

### Contextual Retrieval 完整接线

- **状态**：原型
- **重要等级**：P1
- **收益程度**：中
- **预计时间**：1–2 周
- **改动量**：大
- **需求**：传入真实 parent/reference 文档，并在向量 payload 中分离 original text、contextual prefix 和 embed text。
- **验收**：真实 Qdrant 路径不向用户展示内部 prefix，离线 eval 证明召回质量提升。

### 有效状态监控

- **状态**：部分实现
- **重要等级**：P2
- **收益程度**：中
- **预计时间**：1–2 个工作日
- **改动量**：小
- **需求**：`/api/memory/stats` 区分 configured、instantiated、active 和 degraded/reason，而非只报告配置开关。
- **验收**：缺少 LLM Key 或依赖失败时，接口准确报告模块未生效及原因。

### Context Engineering 集成评测

- **状态**：待开始
- **重要等级**：P2
- **收益程度**：中
- **预计时间**：3–5 个工作日
- **改动量**：中
- **需求**：覆盖摘要事实保留、context retrieval 召回提升、offload 后重读及真实 provider cache marker。
- **验收**：评测进入 CI 或可重复的离线 runner，并有明确通过阈值。

## P1 · 任务可靠性与主动助理

### 持久任务状态机

- **状态**：已完成（归档见 `doc/archive/TASK_STATE_MACHINE.md`）

### 长任务进度、重试与幂等

- **状态**：待开始
- **重要等级**：P1
- **收益程度**：高
- **预计时间**：1–2 周
- **改动量**：大
- **需求**：提供进度查询、失败重试、幂等键和错误审计。
- **验收**：重复请求不会产生重复副作用，失败任务可安全重试。

### 外部 channel 闭环

- **状态**：待开始
- **重要等级**：P1
- **收益程度**：高
- **预计时间**：1–2 周
- **改动量**：大
- **需求**：Proactive Loop 引用真实任务状态，Telegram 等外部 channel 能处理 `needs_input`。
- **验收**：只用手机可接收任务、补充输入并收到最终结果。

## P1 · 隐私与数据生命周期

### 一键遗忘

- **状态**：已完成（归档见 `doc/archive/ONE_CLICK_FORGET.md`）

### 数据导出与来源

- **状态**：待开始
- **重要等级**：P1
- **收益程度**：中
- **预计时间**：3–5 个工作日
- **改动量**：中
- **需求**：提供 JSON/JSONL 导出，并展示记忆和工具结果的 provenance。
- **验收**：用户可完整导出个人数据，每条长期数据可追溯来源。

## P2 · 可观测性与体验

### 结构化运行日志与延迟指标

- **状态**：待开始
- **重要等级**：P2
- **收益程度**：中
- **预计时间**：3–5 个工作日
- **改动量**：中
- **需求**：统一 tool、skill、ASR、TTS 日志，统计端到端 P50/P95。
- **验收**：可按 session 定位慢点和失败阶段，不记录密钥或完整敏感内容。

### 真实语音 E2E

- **状态**：待开始
- **重要等级**：P2
- **收益程度**：中
- **预计时间**：1 周
- **改动量**：中
- **需求**：增加真实 TTS/ASR 路径验证，不只依赖 stub。
- **验收**：受控环境可重复完成语音输入到播放输出的端到端测试。

### 可查询的 Agent 执行轨迹

- **状态**：已完成（归档见 `doc/archive/AGENT_TRACE.md`）

## Backlog · 按需评估

- 本地 ASR（重要等级：P2；收益程度：中；预计时间：2–4 周；改动量：大）
- 第二 channel / Slack（重要等级：P2；收益程度：中；预计时间：1–2 周；改动量：大）
- Daily 深化（重要等级：P2；收益程度：低；预计时间：1–2 周；改动量：中）
- LiveKit 全双工（重要等级：P2；收益程度：低；预计时间：2–4 周；改动量：特大）
- 多设备高级同步（重要等级：P2；收益程度：中；预计时间：2–4 周；改动量：特大）
- 多用户（重要等级：P2；收益程度：低；预计时间：4–8 周；改动量：特大）
- 通用 MCP 适配器（重要等级：P2；收益程度：中；预计时间：2–4 周；改动量：大）
- OAuth（重要等级：P2；收益程度：低；预计时间：2–4 周；改动量：大）

---

**最后整理**：2026-08-01（追加 Rolling Summary 生命周期收口归档）
