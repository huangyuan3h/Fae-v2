# 持久任务状态机

**状态**：已完成  
**完成日期**：2026-07-26  
**TODO 等级**：P1 / 高 / 1–2 周 / 大

## 已交付

- 显式状态图：``queued → running → done | failed | cancelled``，并允许 ``needs_input`` 中断 / 恢复；``failed | cancelled → queued``（retry +1 attempts）。非法转移被 ``assert_transition`` 阻断并通过 API 405/409 返回。
- 独立 SQLite ``TaskStore``（WAL），索引 ``status / session / kind`` + ``updated_at``；``payload`` 与 ``result`` 经 ``safe_json`` 脱敏，转换轨迹以 ``notes_json`` 列表形式持久化（``from / to / at / note``）。
- REST 表面（在 ``/api/tasks`` 命名空间下）：create / list / summary / get + ``claim`` / ``needs-input`` / ``provide-input`` / ``complete`` / ``fail`` / ``cancel`` / ``retry``，含 ``status`` / ``kind`` / ``session_id`` / ``before`` / ``limit`` 过滤分页。
- 启动恢复：lifespan 调用 ``recover_orphaned_running(into="needs_input", reason="service_restart")``，把上一次进程残留的 ``running`` 任务降级并写入 ``note=recovery: …``；用户可通过 ``provide-input`` 直接接续。
- 现有 ``cancel`` 对终态幂等（不抛异常），``retry`` 只能从 ``failed`` / ``cancelled`` 触发；``attempts`` 在 ``→ running`` 与 ``recovery`` 时均 +1，避免“看似第 0 次起步”造成重复副作用。
- 重复键：``Task.id`` 兼作幂等键，同一任务在重试间复用，便于下一阶段的“长任务进度、幂等与重试”复用。

## 主要入口

- `backend/src/fae/scheduler/tasks.py` — `TaskStore` / `Task` / `TaskUpdate` / `TaskStatus` / `assert_transition`。
- `backend/src/fae/api/tasks.py` — REST 路由（``/api/tasks`` 与 ``/api/tasks/{id}/{action}``）。
- `backend/src/fae/api/__init__.py` — lifespan 启动恢复；``app.state.task_store`` 初始化。
- `backend/src/fae/config.py` — ``task_db_path: ".data/fae-tasks.db"``。
- `backend/tests/test_task_store.py` + `backend/tests/test_task_api.py` — 24 项行为 + 边界测试。

## 验证

- `uv run pytest`：`452 passed`，覆盖率 **80.13%**（要求 ≥ 78%）。
- `pnpm lint && pnpm typecheck`：通过。
- 新增 24 项任务测试覆盖：转移合法性 / 完整生命周期（needs_input→running→done） / 失败重试 / 取消幂等 / 持久化重启 / 启动恢复 / 状态过滤 / 分页 / payload 脱敏 / 404/409 错误。

## 后续关联

- 可直接被 **外部 channel 闭环**（TODO P1 / 高 / 1–2 周 / 大）复用，让 Telegram 等 channel 通过 ``POST /api/tasks/{id}/provide-input`` 反哺任务。
- 为下一项 P1「长任务进度、幂等与重试」留出基础：`Task.id` 作为幂等键、`attempts` 已自增、`notes_json` 提供审计上下文。
