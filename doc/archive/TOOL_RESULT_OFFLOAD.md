# R5 · Tool-result Offload — 可恢复性收口

> 完成于 2026-07-26。原文 TODO entry 见 [`doc/TODO.md`](../TODO.md) 的"Tool Offload 可恢复性"（已删除）。

## 验收条件 vs. 落地

验收（TODO 原文）：大工具结果 offload 后，Agent 能可靠读取原文；过期文件会自动清理。

| TODO 原文条目 | 状态 | 实现 |
|---|---|---|
| 补齐 prompt preview | ✅ | `OffloadResult.to_prompt_replacement` 输出`<tool_offload tool=… path=… chars=… preview_chars=…/>`；`test_prompt_envelope_is_byte_stable` 钉住完整字节。`llm_turn._offloaded_tool_result_message` 套在外层 `<tool_result name=… offloaded="true" …>` 提示模型如何读回。 |
| 文件 GC | ✅ | `ToolOffloader.cleanup_expired(now=None)` 扫除超过 `tool_offload_ttl_s`（默认 24h）的 `.json`；lifespan 启动跑一次 `cleanup_expired()`；`tool_offload_cleanup_loop` 每 `tool_offload_cleanup_interval_s`（默认 5min）跑一次；shutdown 取消 task。 |
| 稳定路径 | ✅ | 文件名只带 `<safe_tool>-<safe_id>-<sha12>.json`（去掉了 `time.strftime`）。相同 content + tool + call_id 在任意进程下都落到同一文件路径。多次写入幂等覆盖（`os.replace`）。 |
| `read_file` 可达性 | ✅ | `safe_resolve` 接受 `extra_roots: tuple[str|Path, ...] = ()`；`dispatch_filesystem_tool` 透传。`llm_turn._dispatch_coding_tool` / `apply_lazy_skill_tool` / `stream_assistant_turn` / `api/__init__` (HTTP) / `api/ws.py` (WS) / `channels/bridge.py` (Telegram) 都把 `settings.tool_offload_dir` 串到 `extra_roots`。offload 文件不需要 `coding_workspace_root` 也能读回；其它 workspace 路径仍然过沙箱。 |

## 改动清单

```
backend/src/fae/config.py                 # +tool_offload_ttl_s +tool_offload_cleanup_interval_s
backend/src/fae/agent/tool_offload.py     # +cleanup_expired +ttl_s +tool_offload_cleanup_loop
                                          # drop wall-clock ts from filename
                                          # pin envelope shape in to_prompt_replacement
backend/src/fae/agent/llm_turn.py         # +tool_offload_dir kwarg through
                                          #   apply_lazy_skill_tool / stream_assistant_turn
                                          #   _dispatch_coding_tool
backend/src/fae/tools/safepath.py         # safe_resolve(..., extra_roots=())
backend/src/fae/tools/filesystem.py       # read_file schema updates + extra_roots passthrough
backend/src/fae/api/__init__.py           # +startup sweep +cleanup task +cancel on shutdown
backend/src/fae/api/ws.py                 # pass tool_offload_dir to stream_assistant_turn
backend/src/fae/channels/bridge.py        # pass tool_offload_dir to apply_lazy_skill_tool
backend/tests/test_tool_offload.py        # +byte_stable_across_processes +cleanup_expired_*
                                          # +cleanup_loop_runs_periodically_and_cancels
                                          # +read_file_round_trip +safe_resolve_extra_roots
                                          # +prompt_envelope_is_byte_stable
backend/tests/test_api.py                 # +test_lifespan_wires_tool_offloader_and_cleanup_task
                                          # +test_lifespan_disables_offload_when_settings_say_so
.env.example                              # +TOOL_OFFLOAD_TTL_S +TOOL_OFFLOAD_CLEANUP_INTERVAL_S
doc/design/CONTEXT_ENGINEERING.md         # R5 section rewritten; risk table updated
doc/TODO.md                               # Tool Offload entry → completed
```

## 设计取舍

- **`read_file` 用 extra_roots 而不是新工具**：少一个 tool schema，少向 prompt 注入一组定义。已有 `read_file` 已经会按路径读文件；引入额外 root 列表是最小的入口。空 / 不存在 / 不是目录的 extra_roots 静默跳过，调用方可以无条件把 settings 串下去。
- **TTL 用 mtime 而非文件名时间戳**：路径层去掉了时间戳后不能再从文件名反推生成时间，只能靠文件系统 mtime；这意味着构造 `clean_path` 时需要 `os.utime(..., (two_hours_ago, two_hours_ago))` 这样的手段来写过期测试。
- **TTL=0 视为关闭 GC**：与 `enabled=False` 行为对齐，避免"On 但永远不清理"的歧义状态。
- **路径幂等覆盖**：相同的 content 第二次写入会用 `os.replace` 覆盖第一次的文件；这是有意为之 — 同一 `(tool, call_id, content)` 本来就是同一份"事实"。
- **`tool_offload_cleanup_loop` 用 `asyncio.to_thread` 不需要**：单进程 + 小目录扫描足以，开线程只会增加出错面。生产大目录场景下迁移到 thread 也只是循环体里包一行。
- **`os.replace` + `.tmp` 而不是直接 `path.write_text`**：写中崩溃不会留下半截文件。

## 验证

- `uv run pytest`：**520 passed**（509 → 520，+11 新增），覆盖率 **79.70%**（≥ 78%）。
- 新增覆盖：
  - `test_offloader_path_is_byte_stable_across_processes`：两个独立 `ToolOffloader` 实例，相同 content → 相同 `Path.name`。
  - `test_prompt_envelope_is_byte_stable`：把 `to_prompt_replacement(...)` 的字面量锁死，将来谁动 cache_control 段会立刻炸红。
  - `test_cleanup_expired_removes_only_old_files` + `_skips_non_json_and_disabled` + `_handles_missing_dir`：TTL + 后缀过滤 + 目录不存在不崩。
  - `test_cleanup_loop_runs_periodically_and_cancels`：后台 loop cancel 是干净的，没有未捕获异常。
  - `test_read_file_can_pull_back_offloaded_payload`：end-to-end 写入 + 读回，验证 prompt → filesystem 的反馈环。
  - `test_read_file_offload_path_without_extra_root_is_rejected` + `test_safe_resolve_extra_root_silently_skips_invalid`：没有把无关路径意外放行。
  - `test_lifespan_wires_tool_offloader_and_cleanup_task` + `test_lifespan_disables_offload_when_settings_say_so`：lifespan 真启用 / 真关闭对应的状态。
- `pnpm lint && pnpm typecheck`：通过。

## 后续候选

- **offload 文件入 archival**：研究笔记 `archive/CONTEXT_ENGINEERING_RESEARCH_2026-07-26.md` 提到；当前 offload 仍然纯临时，长期意义不大。
- **`active offloaded files` system prompt 清单**：研究笔记提到让 agent 在 system 层看到当前所有活跃的 offload 路径，避免"忘记指针"。当前每次 `<tool_result>` 都内联 `<tool_offload path=…/>`，实际 prompt 仍是显式的，但未来若引入跨调用引用列表可以再加。
- **集成评测挂钩**：TODO 里"Context Engineering 集成评测"提到 `offload 后重读`作为评测用例；现在已有 `test_read_file_can_pull_back_offloaded_payload` 作为最小化单测，可以扩成真实 LLM 往返。
