# FAE-v2 TODO

> 本文件是未完成功能的唯一维护入口。已完成内容移入 `archive/`；设计方案放入 `design/`；当前架构与模块索引放入 `architect/`；运维文档放入 `operations/`。

## 维护规则

- 这里只记录尚未完成、需要持续关注的 feature。
- 每项必须包含状态、优先级和可验证的验收条件。
- 开始开发时将状态改为「进行中」；完成并验证后，从本文件移除并写入 `archive/` 对应阶段记录。
- 设计细节写入 `design/`，本文件只保留目标、范围和验收条件。
- 优先级顺序：P0 阻塞项 → P1 高需求 → P2 体验增强 → Backlog 按需。

## 当前焦点

**Tool Runtime 安全与产品化**：先完成统一 Registry、危险操作确认和审计，再扩展真实连接器。

## P0 · 文档与发布完整性

### 统一版本状态

- **状态**：待开始
- **需求**：统一 README、backend、UI、SDK、CHANGELOG 与 Git tag 的版本来源。
- **验收**：仓库内所有公开版本号一致，发布检查能发现版本漂移。

### 文档自动校验

- **状态**：待开始
- **需求**：检查 Markdown 相对链接、源码引用的 `doc/...` 路径及关键源码锚点。
- **验收**：CI 能阻止新增断链和引用未跟踪文档。

## P1 · Tool Runtime 安全与产品化

### 统一 Tool Registry

- **状态**：部分实现
- **已有**：文件读写、受限 Bash、只读 Git、天气、日程和 Subagent 工具。
- **待做**：统一管理 name、schema、权限级、timeout、read-only/mutating、确认策略、可用 channel 和结构化输出类型。
- **验收**：所有工具通过同一个 Registry 注册和发现，API 能返回完整工具元数据。

### Sensitive / Dangerous 操作确认

- **状态**：待开始
- **需求**：增加 API/WS 确认请求、客户端批准、session 预授权、拒绝和超时状态。
- **验收**：写文件、执行项目代码及其他高风险操作未经明确授权无法执行；协议不绑定 Web UI。

### 持久工具审计日志

- **状态**：待开始
- **需求**：记录 session、channel、工具名、参数摘要、结果或错误、耗时及批准状态。
- **验收**：重启后仍可按 session 查询工具调用历史，敏感值不会写入日志。

### 真实个人连接器

- **状态**：待开始
- **需求**：按实际使用频率接入至少三个连接器，优先日历、邮件和通用 webhook。
- **验收**：至少三个真实个人工具可稳定调用，权限和失败状态清晰。

### 工具结果回灌记忆

- **状态**：待开始
- **需求**：定义哪些结果形成 fact、episodic event、archival artifact 或临时输出。
- **验收**：关键工具结果第二天仍可 recall，并保留来源信息。

## P1 · Context Engineering 正确性

### Rolling Summary 生命周期

- **状态**：部分实现
- **需求**：统一触发条件，明确 compactor 与 summarizer 的执行顺序和归档所有权，避免重复摘要。
- **验收**：集成测试证明同一批 turns 不会重复摘要，关键事实不会丢失。

### Tool Offload 可恢复性

- **状态**：部分实现
- **需求**：补齐 prompt preview、文件 GC、稳定路径和 `read_file` 可达性。
- **验收**：大工具结果 offload 后，Agent 能可靠读取原文；过期文件会自动清理。

### Contextual Retrieval 完整接线

- **状态**：原型
- **需求**：传入真实 parent/reference 文档，并在向量 payload 中分离 original text、contextual prefix 和 embed text。
- **验收**：真实 Qdrant 路径不向用户展示内部 prefix，离线 eval 证明召回质量提升。

### 有效状态监控

- **状态**：部分实现
- **需求**：`/api/memory/stats` 区分 configured、instantiated、active 和 degraded/reason，而非只报告配置开关。
- **验收**：缺少 LLM Key 或依赖失败时，接口准确报告模块未生效及原因。

### Context Engineering 集成评测

- **状态**：待开始
- **需求**：覆盖摘要事实保留、context retrieval 召回提升、offload 后重读及真实 provider cache marker。
- **验收**：评测进入 CI 或可重复的离线 runner，并有明确通过阈值。

## P1 · 任务可靠性与主动助理

### 持久任务状态机

- **状态**：待开始
- **需求**：支持 queued、running、needs_input、done、failed、cancelled。
- **验收**：任务状态可持久化，服务重启后可恢复或明确失败。

### 长任务进度、重试与幂等

- **状态**：待开始
- **需求**：提供进度查询、失败重试、幂等键和错误审计。
- **验收**：重复请求不会产生重复副作用，失败任务可安全重试。

### 外部 channel 闭环

- **状态**：待开始
- **需求**：Proactive Loop 引用真实任务状态，Telegram 等外部 channel 能处理 `needs_input`。
- **验收**：只用手机可接收任务、补充输入并收到最终结果。

## P1 · 隐私与数据生命周期

### 一键遗忘

- **状态**：待开始
- **需求**：统一删除 facts、recall、archival、episodic 和 chat history。
- **验收**：用户可按 session 或全局删除数据，删除边界明确且可验证。

### 数据导出与来源

- **状态**：待开始
- **需求**：提供 JSON/JSONL 导出，并展示记忆和工具结果的 provenance。
- **验收**：用户可完整导出个人数据，每条长期数据可追溯来源。

## P2 · 可观测性与体验

### 结构化运行日志与延迟指标

- **状态**：待开始
- **需求**：统一 tool、skill、ASR、TTS 日志，统计端到端 P50/P95。
- **验收**：可按 session 定位慢点和失败阶段，不记录密钥或完整敏感内容。

### 真实语音 E2E

- **状态**：待开始
- **需求**：增加真实 TTS/ASR 路径验证，不只依赖 stub。
- **验收**：受控环境可重复完成语音输入到播放输出的端到端测试。

### 可查询的 Agent 执行轨迹

- **状态**：待开始
- **需求**：将临时 WS AgentSteps 升级为可查询的任务或审计视图。
- **验收**：刷新页面或重启服务后仍可查看关键执行步骤。

## Backlog · 按需评估

- 本地 ASR
- 第二 channel / Slack
- Daily 深化
- LiveKit 全双工
- 多设备高级同步
- 多用户
- 通用 MCP 适配器
- OAuth

---

**最后整理**：2026-07-26
