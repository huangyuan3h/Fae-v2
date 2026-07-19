# FAE Core 常驻部署（P6）

用瘦栈 `docker-compose.core.yml` 在一台常驻机上跑 **Agent Core**（API + embedded 记忆 + 可选 Telegram / Loop）。  
全栈开发仍用根目录 `docker-compose.yml`（Letta remote + UI 等）。

浏览器 `/ws/chat` 自动使用服务端 Key 留给 **P7**；本阶段 Telegram / Loop **只认服务端 `.env`**。

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
| `DASHSCOPE_API_KEY` 或 `PROACTIVE_LLM_*` | Telegram / Loop 服务端模型 |
| `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` | 可选；私聊与主动推送 |

3. **启动**

```bash
./deploy/scripts/start-core.sh
# 等价：docker compose -f docker-compose.core.yml up -d --build
```

可选 TTS stub：`WITH_TTS_STUB=1 ./deploy/scripts/start-core.sh`  
（或 `docker compose -f docker-compose.core.yml --profile tts up -d --build`，并把 `VLLM_TTS_URL=http://tts:8880/v1` 写入 `.env`）

4. **就绪检查**

```bash
curl -s http://127.0.0.1:8000/ready | jq
```

期望：`status=ready`，`memory=ok`，有 Key 时 `proactive_llm=ok`；配好 Telegram 后 `telegram=ok`。

5. **Telegram 试聊**（若已配置）：私聊 Bot 一句 → 应有回复；重启容器后记忆仍在（named volume `fae-data`）。

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

个人助理优先私有网络，**不默认裸奔公网 webhook**。

1. 在常驻机与笔记本/手机安装 [Tailscale](https://tailscale.com/download)，加入同一 tailnet。
2. Core 默认监听 `0.0.0.0:8000`；在 tailnet 内用常驻机的 Tailscale IP：`http://100.x.y.z:8000`。
3. 可选：用 Tailscale ACL / serve 只把 `8000` 暴露给自己的设备；本机防火墙可拒绝非 tailnet 入站。
4. Telegram 走 Bot API long polling，**不需要**公网 HTTPS；笔记本休眠不影响常驻机上的 Core。

### 附录：Cloudflare Tunnel

若无 Tailscale：可用 `cloudflared tunnel` 把 `localhost:8000` 映到私有 hostname。仍建议加访问控制，勿把管理面裸奔到公网。

---

## `/ready` 字段含义

| 字段 | 含义 |
|---|---|
| `status` | `ready` 或 `degraded`（memory down） |
| `memory` / `letta` | `ok` / `down` / `off` / `skipped`（`letta` 兼容旧客户端） |
| `scheduler` | Loop：`ok` / `down` / `off`（`SCHEDULER_ENABLED`） |
| `telegram` | `ok` / `down` / `off` / `misconfigured`（缺 token/chat_id） |
| `proactive_llm` | 服务端 Key：`ok` / `misconfigured` |

HTTP：**memory=`down` → 503**；仅 Telegram misconfigured **不** 503（进程仍可服务其它通道）。

```bash
curl -sS -w '\nHTTP %{http_code}\n' http://127.0.0.1:8000/ready
```

---

## 常用运维

```bash
docker compose -f docker-compose.core.yml logs -f backend
docker compose -f docker-compose.core.yml restart backend
docker compose -f docker-compose.core.yml down    # 保留 volume
# 危险：连数据一起删
# docker compose -f docker-compose.core.yml down -v
```

OpenAPI：`http://127.0.0.1:8000/docs`

---

## 本阶段明确不做（P7+）

- 浏览器聊天自动注入服务端 Key、去掉 UI localStorage
- 默认全栈 compose 改为 embedded
- 真 Qwen3-TTS GPU 镜像强塞进 core compose（本机仍用 `scripts/tts/run.sh`）
- LiveKit / 公网裸奔 webhook
