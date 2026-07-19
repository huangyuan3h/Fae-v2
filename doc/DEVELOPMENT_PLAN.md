# FAE-v2 开发计划 · Personal Assistant（v2）

> **产品目标**：成为你的**个人助理**——能接各种各样的工具；在**任何时间、任何地点、多数情况下**帮你把任务搞定。  
> **架构原则**：**Agent Core 是产品**；Web UI / Telegram / 未来 App 都只是 **thin client**。  
> **工程原则**：代码在 GitHub 持续演进；**一键/快速部署**到本机或一台常驻机器；FE 可替换。

归档：已完成的 Phase 1～Q～5.2（至 stable `v0.2.0`）见  
[`doc/archive/DEVELOPMENT_PLAN_through_v0.2.md`](./archive/DEVELOPMENT_PLAN_through_v0.2.md)。

---

## 0. 诚实差距：离「随时随地个人助理」还差什么

### 0.1 目标拆解（验收语言）

| 目标说法 | 可检验含义 | 今天（v0.2） |
|---|---|---|
| **任何时间** | 服务常驻；主动 Loop / 日程能在无人打开浏览器时推送 | 本机进程依赖你开机；无可靠公网常驻默认路径 |
| **任何地点** | 手机 / Telegram / 外网能打到**同一** Agent Core + 同一记忆 | Telegram 可选；默认仍绑本机浏览器 + localStorage Key |
| **任何情况搞定任务** | 能调用**你的**工具（日历、邮件、文件、脚本、浏览器、第三方 API…）并回灌结果 | 工具面很窄（天气/日程/skill/subagent）；无通用工具运行时与权限模型 |
| **FE 只是壳** | Chat/Notify/Settings 经稳定 HTTP/WS API；换 client 不改 Core | API 已有雏形，但身份、配置、会话仍偏「单页应用约定」 |
| **快速部署** | `git pull` + 一份 compose/脚本 → 起 Core；CI 出可运行产物 | 有 Docker/脚本/CI 测后端；缺「发布即部署」与配置契约 |

**粗估**：骨架与体验首版约 **35～45%** 到「愿意天天用的本地助理」；到「真正随时随地 + 工具齐全」大约还在 **全程的 1/3 处**——后面主要是 **Core 可部署性、Channel 统一、Tool Runtime、身份与配置外置**，不是再堆 UI。

### 0.2 已有资产（不要推倒）

- 默认对话：浏览器 STT → `/ws/chat` → 本机 TTS；Daily 可选
- 记忆：embedded/remote Letta 路径 + recall/archival（质量首版）
- Skills + `run_subagent`（researcher/coder/reviewer）
- 主动 Loop + inbox / WS / desktop / Web Push / Telegram outbound
- Telegram inbound long-polling（共享 `session_id=default`）
- 最小 evals 进 CI；stable tag `v0.2.0`

### 0.3 最大结构性缺口

```text
今日：  [Browser UI] ──Key在浏览器──► [FastAPI on laptop]
              │                              │
              └──── Telegram（可选）──────────┘

目标：  [Any Client] ──token/session──► [Agent Core 常驻]
              │                              │
              │                    ┌─────────┴─────────┐
              │                    │ Tool Runtime      │
              │                    │ Memory · Loop     │
              │                    │ Channel adapters  │
              └────────────────────┴───────────────────┘
```

1. **Core 未「产品化部署」**：配置分裂（浏览器 Key vs 服务端 Key）；无标准「远程客户端连常驻 Core」故事。
2. **Client 契约弱**：缺稳定的「会话 / 身份 / 能力发现」API；UI 仍是主叙事。
3. **工具上限不够**：无统一 Tool Registry、权限分级、人机确认、连接器生命周期。
4. **「任何情况」不可承诺**：没有可靠执行环境（sandbox / 本机 agent worker）、失败重试与任务状态机。

---

## 1. 北极星与非目标

### 1.1 北极星（写进每次阶段验收）

> 我在外面用 Telegram（或手机壳）给 FAE 一句话；它用**同一套记忆与工具**办完事，并把结果推回来——**无需打开桌面浏览器**。

### 1.2 非目标（本计划默认不做）

- 多租户 SaaS / 商业化账号体系（个人助理 ≠ 平台）
- 「多智能体产品」叙事膨胀（subagent 保持工具级委派）
- 强绑某一家 WebRTC（LiveKit 仅在明确需要全双工时评估）
- 把 MCP 当唯一扩展面（可作为**一种**连接器，不是宗教）

---

## 2. 新阶段总览（P6 起）

| 阶段 | 名称 | 状态 | Demo-Ready |
|---|---|---|---|
| P0～P5.2 | 骨架 + 质量 + 多端首版 | 已归档 | `v0.2.0` |
| **P6** | **Core 常驻 & 快速部署** | ✅ 完成 | 一台机器 compose up → API 可用；GitHub Release `v0.3.0` |
| **P7** | **Client 契约 & 壳化** | **下一主线** | 任意 client 只依赖 OpenAPI/WS；Web 降级为参考壳 |
| **P8** | **Tool Runtime & 连接器** | 待开始 | 插件式工具 + 权限；接 3～5 个你真用的工具 |
| **P9** | **任务可靠性 & 主动助理** | 待开始 | 长任务状态、失败可追、外出也能闭环 |
| **P10** | **可选增强** | 按需 | 本地 ASR、更深语音、第二 channel、MCP 适配器 |

---

## 3. Phase 细节

### P6 · Core 常驻 & 快速部署 ✅

**为什么先做**：没有「常驻 Core」，「任何地点」和「FE 是壳」都是空话。

- [x] **配置外置**：服务端为唯一真相源（LLM / TTS / 记忆 / Telegram / tools）；浏览器 Key 仅作本地开发捷径；常驻路径见 `doc/DEPLOY.md`（Telegram/Loop 不需浏览器 Key；浏览器自动注入留给 P7）
- [x] **部署契约**：`docker-compose.core.yml` + `deploy/scripts/start-core.sh`；可选 profile `tts`；`.env.example` Always-on Core 块
- [x] **GitHub**：Release `v0.3.0` 附部署说明；CI 含 backend image build
- [x] **健康与就绪**：`GET /ready` 含 `memory` / `scheduler` / `telegram` / `proactive_llm`；memory down → 503
- [x] **远程访问最小集**：主推 Tailscale；附录 Cloudflare Tunnel（`doc/DEPLOY.md`）

**验收（M6）**：笔记本休眠时，云端或家里常驻机上的 Core 仍响应 Telegram；新机器按 `doc/DEPLOY.md` 30 分钟内起得来。

---

### P7 · Client 契约 & 壳化 ← 下一主线

**为什么**：FE 必须可替换；否则永远困在 Next 页。

- [ ] **稳定 API 面**（版本前缀或明确兼容策略）：
  - 对话：HTTP chat + WS stream（已有）
  - 记忆 / skills / schedules / notifications（已有，需契约测试）
  - **能力发现**：`GET /api/capabilities`（channels、tools、modes）
- [ ] **会话与身份（个人级）**：`session_id` / device binding；可选简单 token（不是完整 OAuth 平台）
- [ ] **Web UI 降级为 Reference Client**：只消费公开 API；去掉「必须本机」假设
- [ ] **Client SDK（薄）**：TypeScript 一小包（connect / chat / onNotification），Telegram 已是第二 client 样板

**验收（M7）**：用 curl + Telegram 完成「对话 → 记忆 → 提醒」全链路；Web 关掉也不影响 Core。

---

### P8 · Tool Runtime & 连接器

**为什么**：这是「各种各样工具」的真正上限。

- [ ] **统一 Tool Registry**：name / schema / 权限级（Safe / Caution / Sensitive / Dangerous）/ timeout
- [ ] **执行与确认**：Sensitive+ 需 client 确认或预授权；结果结构化回灌 memory
- [ ] **内置连接器优先（按你个人清单排序，示例）**：
  - 本机/服务器文件系统（沙箱根目录）
  - Shell（Dangerous，默认关）
  - 日历 / 邮件（OAuth 或应用密码）
  - HTTP 通用 webhook
  - （可选）MCP client 作为连接器一种
- [ ] **Skill 只编排，不发明工具**：playbook 调用 registry 内工具；与 `run_subagent` 同级扩展

**验收（M8）**：至少 3 个真实个人工具可调用；危险操作有确认；结果第二天仍能 recall。

---

### P9 · 任务可靠性 & 主动助理

- [ ] 任务状态机：queued / running / needs_input / done / failed
- [ ] 长任务可查进度；失败可重试；主动 Loop 引用任务而非罐头句
- [ ] 外出通道：Telegram（已有）+ 至少一个可靠推送（Push 或 IM）默认可用
- [ ] 审计日志：谁在何时调了什么工具（本地文件即可）

**验收（M9）**：出差一天，只靠手机 IM：提醒到达、回一句写入记忆、委托一项工具任务并收到结果。

---

### P10 · 按需增强

- 本地 ASR / 更好语音
- Slack 或其他 channel
- LiveKit 全双工
- 多设备高级同步

不阻塞 P6～P9。

---

## 4. 工具接入原则（写给未来的自己）

1. **先 Registry，后 MCP**：MCP 是适配器，不是架构中心。
2. **权限默认拒绝**：新工具默认 Sensitive；显式降级到 Safe。
3. **结果可记忆**：工具输出要能 `archival` / fact，否则「助理」隔天失忆。
4. **Client 无关**：工具确认协议走 API，不绑 React 组件。

---

## 5. 部署与 GitHub 节奏

| 节奏 | 做法 |
|---|---|
| 日常 | `init`/`main` PR；CI（backend pytest + UI build）必须绿 |
| 阶段完成 | tag `v0.3.0` / `v0.4.0`…；CHANGELOG 一节；Release 附 compose 说明 |
| 机器 | 一台常驻（家用 NUC / 小 VPS / 现有 Mac mini）跑 Core；笔记本只做开发 client |
| 网络 | 优先 Tailscale/私有隧道；公网 webhook 按需 |

---

## 6. 近期执行顺序（建议）

1. **P7** Client 契约 & Web 壳化 ← 当前主线
2. **P8** 按你真实工具清单接连接器（先 3 个最高频）
3. **P9** 任务可靠性，闭环「外出一天」
4. P10 按痛点插入

---

## 7. 里程碑

| ID | 验收 | 状态 |
|---|---|---|
| M0～M5.2 | 见归档计划 / `v0.2.0` | 完成 |
| **M6** | 常驻 Core + 快速部署 + 远程 Telegram 闭环 | ✅ `v0.3.0` |
| **M7** | 无 Web 也可完整使用（API + 至少一 IM client） | 下一主线 |
| **M8** | ≥3 个个人真实工具 + 权限 | 待定 |
| **M9** | 外出一天仅靠手机办完提醒/记忆/一工具任务 | 待定 |

---

**最后更新**：2026-07-19（P6 / M6 完成）  
**关联**：[`ARCHITECTURE.md`](./ARCHITECTURE.md) · [`DEPLOY.md`](./DEPLOY.md) · [`archive/DEVELOPMENT_PLAN_through_v0.2.md`](./archive/DEVELOPMENT_PLAN_through_v0.2.md) · [`../CHANGELOG.md`](../CHANGELOG.md) · [`../README.md`](../README.md)
