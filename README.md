# FAE-v2

> **F**ully **A**utonomous **E**cho · v2
> 一个有长期记忆、能主动 loop、可本地部署的语音 Agent。

## 文档

- 📐 **[ARCHITECTURE.md](./ARCHITECTURE.md)** — 完整架构文档（必读）
- 即将推出：`docs/design/`、`docs/api/`、`examples/`

## 核心能力

- 🎙️ **实时语音对话**（Qwen3-ASR + Qwen3-TTS，Apache 2.0）
- 🧠 **长期记忆**（Letta + 多层记忆架构）
- 🎯 **主动 loop**（APScheduler + 心跳）
- 🛠️ **Skills / Tools**（Markdown 编写，参考 Vercel Eve 风格）
- 🎨 **美观 UI**（Next.js 15 + shadcn/ui）

## 快速开始

```bash
# 克隆仓库
git clone https://github.com/huangyuan3h/Fae-v2.git
cd FAE-v2

# 安装依赖 + 下载模型
./deploy/scripts/setup.sh

# 一键启动
./deploy/scripts/start.sh

# 浏览器打开
open http://localhost:3000
```

> ⚠️ 项目仍在早期阶段，详见 [ARCHITECTURE.md](./ARCHITECTURE.md) 中的路线图。

## 许可证

Apache 2.0