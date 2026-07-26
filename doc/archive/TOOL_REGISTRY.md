# 统一 Tool Registry

**状态**：已完成
**完成日期**：2026-07-26
**TODO 等级**：P1 / 高 / 1 周 / 大

## 已交付

- **单一目录**：`fae.tool_registry` 拥有工具的 OpenAI schema + 风险分级 + 批准/通道策略的统一真相。
- **`ToolSpec` 扩展**：在 P1 / "Sensitive Ops Approval" 已有基础上新增 `group` 与 `schema` 字段：
  - `group`：`filesystem` / `bash` / `git` / `weather` / `schedule` / `subagent` / `skill`。
  - `schema`：OpenAI `function` body（`{name, description, parameters}`），通过 `to_openai()` / `openai_schema_for()` 暴露。
- **`register_tool(spec)` / `reset_registry()`** 真正工作：
  - 注册是幂等的，会返回旧值供测试断言。
  - `reset_registry()` 现在通过冻结的 `_STATIC_SPECS` 快照保留出厂目录，只会清掉运行时动态注册项；之前会清空所有（包括内置）的 bug 已修。
- **静态目录由各 feature 模块一次性喂入**：`_build_static_catalog()` 在首访问时（`_ensure_built()`）惰性从 `tools/filesystem.py`、`tools/bash.py`、`tools/git.py`、`tools/weather.py`、`scheduler/tools.py`、`agent/subagents/tools.py`、`agent/skills_runtime.py` 各自拉取 `*_TOOLS` 常量，统一加上 `risk_tier / requires_approval / needs_diff_preview / side_effects / default_ttl_s` 等策略元数据。这是**唯一**声明风险等级的地方。
- **发现/路由帮手**：
  - `groups()` / `specs_in_group(g)` / `group_for(name)`。
  - `iter_openai_schemas(group=None)`：按组列出 OpenAI schema。
  - `openai_schema_for(name)`：单工具 schema。
  - `specs_for_capabilities()`：暴露给 `/api/capabilities`，新增 `group` 和 `parameters` 字段。
- **`_merge_tools` 走 registry**（`agent/llm_turn.py`）：原来 6 个硬编码 `if enabled: append *_TOOLS` 分支改为按 `iter_openai_schemas(group="filesystem")` 等按组查询，不再直接 import 单独的 `*_TOOLS` 常量；同时硬编码的 `_FILESYSTEM_TOOL_NAMES` / `_BASH_TOOL_NAMES` / `_GIT_TOOL_NAMES` / `_WEATHER_TOOL_NAMES` / `_SCHEDULE_TOOL_NAMES` 改为从 `specs_in_group()` 派生。
- **`known_tools()` lazy**：`fae.agent.known_tools._KNOWN_TOOL_NAMES` 从模块级 constant 改为可选，避免 `from fae.tool_registry import known_tool_names; _KNOWN_TOOL_NAMES=...` 触发 `_ensure_built()` 时击穿 `skills_runtime` 的部分加载状态。

## 主要入口

- `backend/src/fae/tool_registry.py`：核心。
  - `ToolSpec` / `_spec_from()` / `register_tool()` / `reset_registry()` / `known_tool_names()` / `static_tool_names()` / `get_spec()`。
  - `groups()` / `specs_in_group()` / `group_for()` / `iter_openai_schemas()` / `openai_schema_for()`。
  - `specs_for_capabilities()` / `diff_preview_for()` / `canonical_args_hash()`。
  - `EffectivePolicy` / `PolicyDecision` / `resolve_policy()`。
- `backend/src/fae/agent/llm_turn.py`：`_merge_tools` 改用 `iter_openai_schemas`，dispatch 允许列表改为从 `specs_in_group` 派生；dispatch 函数本身保留在 feature 模块。
- `backend/src/fae/agent/known_tools.py`：`known_tools()` / `refresh_known_tools()`；去掉 eager constant。
- `backend/src/fae/api/capabilities.py`：自动取到新增的 `group` / `parameters` 字段。

## 设计取舍

- **Schema 留在 feature 模块，不是 registry**：每个 feature 模块拥有自己的 `*_TOOLS` 列表与 dispatch 函数；registry 只在 `group` 维度声明策略。这样 schema 修改不必同时改两处。
- **Dispatch 没统一**：filesystem/bash/git 是 sync vs async + 不同 context；保留 per-domain 函数避免无谓抽象。`_dispatch_coding_tool` 入口仍按域分流，但允许列表与 metadata 完全走 registry。
- **lazy build**：`_ensure_built` 模式避免循环依赖（`tool_registry ↔ skills_runtime → known_tools → tool_registry`），同时保留运行时动态 register 的能力。

## 验证

- `uv run pytest`：**502 passed**（494 + 8 新），覆盖率 **79.75%**（≥ 78%）。
- 新增测试覆盖（`tests/test_tool_registry.py`，11→19 项）：
  - `groups_and_specs_in_group` — 7 个 group 全存在；filesystem / schedule 集合等于预期。
  - `group_for_known_and_unknown` — 已知与未知工具。
  - `iter_openai_schemas_group_filter` — 空 group / 单 group。
  - `openai_schema_for_round_trip` — 包含 `parameters.properties.path`。
  - `reset_registry_preserves_static_catalog` — 动态注册被清空，静态目录完整恢复。
  - `static_tool_names_matches_static_catalog` — 暴露的内置名字。
  - `spec_parameters_and_description_flow_back` — description / parameters 字段一致。
  - `specs_for_capabilities_includes_group_and_parameters` — `/api/capabilities` 字段对齐。
- `pnpm lint && pnpm typecheck`：通过。

## 后续影响

- **真实个人连接器**（calendar / email / webhook / Telegram 等）的接入只需在 `tool_registry._build_static_catalog()` 添加一组 `_spec_from(...)`，无需修改 dispatcher 和 `_merge_tools`。
- **外部 channel 闭环**可以直接消费 `group_for(name)` 把工具按 channel 划类。
- **Plan Mode** 复杂任务可以查询 `specs_in_group(...)` 决定每个步骤允许/需要的工具集。
