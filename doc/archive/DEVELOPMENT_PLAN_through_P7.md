# FAE-v2 已完成计划归档 · P6–P7

> 本文件只记录已经完成并验收的阶段。未完成功能统一维护在 [`../TODO.md`](../TODO.md)。

## P6 · Core 常驻与快速部署

**状态**：完成  
**里程碑**：M6 / `v0.3.0`

- [x] 服务端配置外置；Telegram、主动 Loop 和浏览器 chat 可使用服务端 LLM Key。
- [x] 提供 `docker-compose.core.yml` 与 `deploy/scripts/start-core.sh`。
- [x] 提供 embedded memory 持久卷及可选 TTS stub。
- [x] `GET /ready` 覆盖 memory、scheduler、Telegram 和 proactive LLM 状态。
- [x] 建立 Tailscale 优先的远程访问方案。
- [x] CI 增加 backend image build。

**验收结果**：常驻 Core 可在没有 Web UI 的情况下通过 API 和 Telegram 工作；部署步骤见 [`../operations/DEPLOY.md`](../operations/DEPLOY.md)。

## P7 · Client 契约与壳化

**状态**：完成  
**里程碑**：M7 / `v0.4.0`

- [x] HTTP chat、WebSocket stream、memory、skills、schedules 和 notifications API 可供 thin client 使用。
- [x] `GET /api/capabilities` 提供能力发现。
- [x] 支持个人级 `session_id` 与可选 `FAE_CLIENT_TOKEN`。
- [x] Web UI 可在没有浏览器 LLM Key 时使用服务端配置。
- [x] 提供薄 TypeScript SDK [`sdk/typescript`](../../sdk/typescript)。

**验收结果**：curl 与 Telegram 可完成对话和记忆闭环，关闭 Web UI 不影响 Agent Core。

## 关联

- 更早阶段：[`DEVELOPMENT_PLAN_through_v0.2.md`](./DEVELOPMENT_PLAN_through_v0.2.md)
- 当前架构：[`../architect/ARCHITECTURE.md`](../architect/ARCHITECTURE.md)
- 当前待办：[`../TODO.md`](../TODO.md)
- 发布记录：[`../../CHANGELOG.md`](../../CHANGELOG.md)

---

**归档日期**：2026-07-26
