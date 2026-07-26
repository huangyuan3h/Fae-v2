# 统一 Tool Registry

**状态**：已完成
**完成日期**：2026-07-26
**TODO 等级**：P1 / 高 / 1 周 / 大

## 已交付

### Phase 1 — schema + metadata 单一目录
- **单一真相**：`fae.tool_registry` 拥有工具的 OpenAI schema + 风险分级 + 批准/通道策略的统一目录。
- **`ToolSpec` 字段**：`name` / `risk_tier` / `group` / `schema` / `side_effects` / `requires_approval` / `needs_diff_preview` / `needs_double_confirm` / `default_ttl_s` / `double_confirm_window_s` / `default_timeout_s` / `channel_allowlist` / `output_kind` / `output_description`。
- **`register_tool(spec)` / `reset_registry()`**：
  - 注册是幂等的，会返回旧值供测试断言。
  - `reset_registry()` 通过冻结的 `_STATIC_SPECS` 快照保留出厂目录，只会清运行时动态注册项；之前会清空所有（包括内置）的 bug 已修。
- **静态目录由各 feature 模块一次性喂入**：`_build_static_catalog()` 在首访问时（`_ensure_built()`）惰性从 `tools/filesystem.py`、`tools/bash.py`、`tools/git.py`、`tools/weather.py`、`scheduler/tools.py`、`agent/subagents/tools.py`、`agent/skills_runtime.py` 拉取 `*_TOOLS` 常量，统一加上策略元数据。这是**唯一**声明风险等级 / timeout / 输出 kind 的地方。
- **发现/路由帮手**：
  - `groups()` / `specs_in_group(g)` / `group_for(name)`。
  - `iter_openai_schemas(group=None)`：按组列出 OpenAI schema。
  - `openai_schema_for(name)`：单工具 schema。
  - `specs_for_capabilities()`：暴露给 `/api/capabilities`，包含 `group`、`parameters`、`default_timeout_s`、`output_kind`、`output_description`。
- **CODING_GROUPS / is_coding_tool / resolve_timeout**：单一处决定"coding 组是什么"和"工具执行用几秒 timeout"，让 dispatcher 不再硬编码 `bash_timeout_s`/`git_timeout_s`。

### Phase 2 — 把 timeout 与输出类型挪到 spec
- **`default_timeout_s`**：写入 `run_bash=30.0` 与所有 git 工具（`20.0`）。
- **`resolve_timeout(name, override=None)`**：override > spec > `DEFAULT_TOOL_TIMEOUT_S(30.0)`。
- **`is_coding_tool(name)`**：判定工具是否属 `filesystem`/`bash`/`git`。
- **`_dispatch_coding_tool` 路径选择**：从基于硬编码 `in _FILESYSTEM_TOOL_NAMES` 改为 `group_for(tool_name)`；timeout 从 `resolve_timeout()` 取。
- **probe filter**：`apply_lazy_skill_tool` 中 `is_coding_tool(tc.name) and (...)` 组合。
- **`output_kind` / `output_description`**：为每个工具声明输出格式（`text`/`json`/`markdown`）与一句话描述，访问者能看见完整输入→输出契约。

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
- **Dispatch 没统一**：filesystem/bash/git 是 sync vs async + 不同 context；保留 per-domain 函数避免无谓抽象。`_dispatch_coding_tool` 入口仍按域分流，但允许列表、metadata、timeout 完全走 registry。
- **lazy build**：`_ensure_built` 模式避免循环依赖（`tool_registry ↔ skills_runtime → known_tools → tool_registry`），同时保留运行时动态 register 的能力。
- **timeout 在 spec 但允许 override**：`resolve_timeout(name, override=None)` 让全局设置（`coding_bash_timeout_s`/`coding_git_timeout_s`）依然是合法的覆盖路径；只是缺省值从 spec 自动选取，不再"必须"由 caller 提供。

## 验证

- `uv run pytest`：**509 passed**（494 + 15 新），覆盖率 **79.76%**（≥ 78%）。
- 新增测试覆盖（`tests/test_tool_registry.py`，11→26 项）：
  - Phase 1：group / specs_in_group / group_for / iter / schema round-trip / reset / static / params / capabilities group+params。
  - Phase 2：`coding_groups` / `is_coding_tool` / `resolve_timeout` precedence（override / spec / fallback）/ `default_timeout_s` in capabilities / `output_kind` for every tool / dynamic spec defaults to None / `output_description` non-empty。
- `pnpm lint && pnpm typecheck`：通过。

## 后续影响

- **真实个人连接器**（calendar / email / webhook / Telegram 等）的接入只需在 `tool_registry._build_static_catalog()` 添加一组 `_spec_from(...)`，无需修改 dispatcher 和 `_merge_tools`。
- **外部 channel 闭环**可以直接消费 `group_for(name)` 把工具按 channel 划类。
- **Plan Mode** 复杂任务可以查询 `specs_in_group(...)` 决定每个步骤允许/需要的工具集。
