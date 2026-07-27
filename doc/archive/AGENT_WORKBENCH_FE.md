# Agent 工作台式 FE 重构 — 归档记录

**完成日期**：2026-07-26
**重要等级**：P1
**收益程度**：高
**改动量**：大
**范围**：本次合并完成了 `主线与执行细节分层` 的核心交付（ExecutionPanel 与 ChatTranscript 解耦）。

## 目标

解决主页面缺少设计感、信息分散的问题，让注意力集中在当前问题与执行过程。
同时实现「主线只呈现关键进展和调用结果，Subagent、Tool Call 等过程收纳到可展开详情区域」。

## 设计原则

- **视觉中心** = 当前对话 + 输入区 + 当前 Agent 输出
- **辅助区域**（默认不抢主内容）= 历史会话、工具/子代理/审批、统计与调试
- **复用优先** = 抽取 UI 原语，避免页面级临时样式拼接
- **响应式** = 桌面端三栏（历史 / 对话 / 执行），移动端历史与执行侧栏隐藏

## 新增组件

| 文件 | 角色 |
|------|------|
| `src/components/ui/Button.tsx` | primary/secondary/ghost/danger 按钮 |
| `src/components/ui/IconButton.tsx` | 圆形图标按钮（mic / interrupt / send） |
| `src/components/ui/Badge.tsx` | 状态徽章（含 `statusTone()` 状态→色调映射） |
| `src/components/ui/Surface.tsx` | 半透明卡片 + `Card` 高级变体 |
| `src/components/ui/index.ts` | 统一导出 |
| `src/components/AppHeader.tsx` | 紧凑 sticky 顶部条（FAE wordmark + AppNav） |
| `src/components/voice/StatusChip.tsx` | 替代原 VoiceOrb 的小状态指示 |
| `src/components/voice/Composer.tsx` | 统一输入区（status chip + textarea + mic/interrupt + send） |
| `src/components/voice/ExecutionPanel.tsx` | 右侧执行面板：milestones + approval card + 事件列表 |

## 重构与删除

| 文件 | 变更 |
|------|------|
| `src/app/page.tsx` | 重写为 `AppHeader` + 三栏布局（历史 / 对话 / 执行） |
| `src/components/voice/ChatTranscript.tsx` | 移除内联 `ExecutionView`；对话行改为气泡样式（用户右对齐/绿色，助手左对齐/白卡，系统居中/灰底） |
| `src/components/voice/VoiceOrb.tsx` | **删除**（功能由 `StatusChip` 接管） |
| `src/components/voice/ExecutionView.tsx` | **删除**（功能由 `ExecutionPanel` 接管） |

## 布局

```
┌───────────────────────────────────────────────────────────┐
│  AppHeader（sticky）:  F FAE    [对话] [记忆] [Skills] …   │
├───────────┬─────────────────────────────┬─────────────────┤
│           │ [技能 · 路径 · 记忆]   [详情] │                 │
│  历史会话 │                             │  执行细节        │
│  (lg+)    │   ChatTranscript            │  (xl+)           │
│           │   （用户/助手/系统 气泡）   │  - 步骤          │
│           │                             │  - 审批          │
│           │                             │  - 事件          │
│           │   Composer                  │                  │
│           │   (status chip + mic + send) │                  │
└───────────┴─────────────────────────────┴─────────────────┘
```

## 验收

- `pnpm lint` 通过
- `pnpm typecheck` 通过
- `pnpm build` 通过（10 个静态页全部成功生成）
- 开发服务器 SSR 返回 HTTP 200，新组件 `data-testid` 全部挂载：
  - `app-header` `chat-history-sidebar` `chat-transcript` `composer` `composer-textarea` `composer-send` `execution-panel-empty`
- 状态文案正确显示（"就绪" / "听写中" / "思考中" / "播放中"）
- AppNav 链接（对话/记忆/Skills/日程/Settings）正常渲染

## 后续可改进项

- UI 原语可继续扩展：`Tabs`、`Dialog`、`Toast`、`Tooltip`
- 增加 vitest + @testing-library/react 跑组件单元测试
- ExecutionPanel 当前只在 ≥xl 屏幕显示；移动端可加底部抽屉
- ChatTranscript 气泡可加发送/失败状态显示
- 思考流的 `思考中…` 可替换为带 shimmer 的 skeleton