# FAE Core 常驻部署（P6）+ Client 契约（P7）

用瘦栈 `docker-compose.core.yml` 在一台常驻机上跑 **Agent Core**（API + embedded 记忆 + 可选 Telegram / Loop）。  
全栈开发仍用根目录 `docker-compose.yml`（Letta remote + UI 等）。

**P7**：浏览器 `/ws/chat` 与 `POST /api/chat` **默认使用服务端 LLM Key**（client 非空 `api_key` 可覆盖）。  
可选 `FAE_CLIENT_TOKEN`：设了之后 mutating API / WS 需要 Bearer 或 `?access_token=`；`/health` `/ready` `/api/capabilities` 仍公开。

API 兼容策略：不加 `/v1` 前缀；只增字段、不删既有路径。

---

## 30 分钟清单

1. **Clone**

```bash
git clone https://github.com/huangyuan3h/Fae-v2.git
cd Fae-v2
```

2. **配置 `.env`**

```bash
cp .env.example .env
```

填写 **Always-on Core** 块（至少）：

| 变量 | 说明 |
|---|---|
| `LETTA_MODE=embedded` | 记忆落在 volume `/app/.data` |
| `SCHEDULER_ENABLED=true` | 主动 Loop |
| `DASHSCOPE_API_KEY` 或 `PROACTIVE_LLM_*` | 服务端模型（Telegram / Loop / **浏览器 chat**） |
| `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` | 可选；私聊与主动推送 |
| `FAE_CLIENT_TOKEN` | 可选；Tailscale 暴露时建议开启 |

3. **启动**

```bash
./deploy/scripts/start-core.sh
# 等价：docker compose -f docker-compose.core.yml up -d --build
```

可选 TTS stub：`WITH_TTS_STUB=1 ./deploy/scripts/start-core.sh`

4. **就绪检查**

```bash
curl -s http://127.0.0.1:8000/ready | jq
curl -s http://127.0.0.1:8000/api/capabilities | jq
```

期望：`status=ready`，`memory=ok`，有 Key 时 `proactive_llm=ok` / `llm.server_configured=true`。

5. **curl 无浏览器 Key 对话**

```bash
curl -sS http://127.0.0.1:8000/api/chat \
  -H 'Content-Type: application/json' \
  -d '{"config":{"api_key":""},"messages":[{"role":"user","content":"我叫小明"}]}' | jq
# 若设了 FAE_CLIENT_TOKEN，加：-H "Authorization: Bearer $FAE_CLIENT_TOKEN"
```

6. **Telegram 试聊**（若已配置）：私聊 Bot → 回复；重启容器后记忆仍在（volume `fae-data`）。

---

## 对照：开发全栈 vs 常驻 Core

| | `docker-compose.yml` | `docker-compose.core.yml` |
|---|---|---|
| 用途 | 本机开发全栈 | 常驻 Agent Core |
| 记忆 | 常强制 remote Letta | 默认 **embedded** |
| 服务 | backend + letta + UI 等 | 仅 backend（+ 可选 TTS stub） |
| 数据 | 视 compose 而定 | volume `fae-data` → `/app/.data` |
| 重启 | 开发用 | `restart: unless-stopped` |

---

## Tailscale（推荐远程访问）

1. 常驻机与客户端加入同一 [Tailscale](https://tailscale.com/download) tailnet。
2. 用 Tailscale IP 访问 `:8000`。
3. 建议设置 `FAE_CLIENT_TOKEN`；UI 用 `NEXT_PUBLIC_FAE_CLIENT_TOKEN` 或 Settings → Models。
4. Telegram long polling **不需要**公网 HTTPS。

### 附录：Cloudflare Tunnel

可用 `cloudflared` 映 `localhost:8000`；勿裸奔公网管理面。

---

## `/ready` 与 `/api/capabilities`

| `/ready` 字段 | 含义 |
|---|---|
| `status` | `ready` 或 `degraded`（memory down → HTTP 503） |
| `memory` / `letta` | `ok` / `down` / `off` / `skipped` |
| `scheduler` | `ok` / `down` / `off` |
| `telegram` | `ok` / `down` / `off` / `misconfigured` |
| `proactive_llm` | `ok` / `misconfigured` |

`GET /api/capabilities`：channels / modes / tools / `llm.server_configured` / `auth.client_token_required`（不回传密钥）。

---

## 常用运维

```bash
docker compose -f docker-compose.core.yml logs -f backend
docker compose -f docker-compose.core.yml restart backend
docker compose -f docker-compose.core.yml down
```

OpenAPI：`http://127.0.0.1:8000/docs`  
薄 TS SDK：[`sdk/typescript`](../sdk/typescript)（`@fae/client`）

---

## 延后（P8+）

OAuth、`/v1` 前缀、完整 SDK REST 面、GPU TTS 进 core compose、LiveKit。
