"use client";

import { useState } from "react";

import { Badge, statusTone } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Surface } from "@/components/ui/Surface";
import type {
  ApprovalRequestMsg,
  ExecutionEvent,
  ExecutionMilestone,
  TurnExecution,
} from "@/hooks/useVoiceSession";

type ApprovalHandlers = {
  onApprove?: (
    approvalId: string,
    decision: { remember?: "session" | "always" | null; confirm?: boolean },
  ) => void;
  onDeny?: (approvalId: string, reason?: string) => void;
  onCancel?: (approvalId: string) => void;
};

const STATUS_LABEL: Record<ExecutionEvent["status"], string> = {
  running: "进行中",
  done: "完成",
  error: "失败",
  awaiting_approval: "等待确认",
  approved: "已批准",
  denied: "已拒绝",
  expired: "已过期",
  cancelled: "已取消",
};

const KIND_ICON: Record<ExecutionEvent["kind"], string> = {
  skill: "·",
  subagent: "↪",
  tool: "▶",
  approval: "⏸",
};

function milestoneStatusTone(status: ExecutionMilestone["status"]) {
  return statusTone(status);
}

export function ExecutionPanel({
  execution,
  approval,
}: {
  execution: TurnExecution | null;
  approval?: ApprovalHandlers;
}) {
  const [collapsed, setCollapsed] = useState(false);
  if (!execution || (execution.events.length === 0 && !execution.pendingApproval && !execution.errorMessage)) {
    return (
      <Surface
        tone="subtle"
        className="hidden flex-col gap-1 p-3 xl:flex"
        data-testid="execution-panel-empty"
      >
        <p className="text-xs font-semibold uppercase tracking-wider text-[var(--ink-soft)]">
          执行细节
        </p>
        <p className="text-xs text-[var(--ink-soft)]">
          助手回复时，工具与子代理会出现在这里。
        </p>
      </Surface>
    );
  }

  const hasPending = Boolean(execution.pendingApproval);
  const eventCount = execution.events.length;
  const headerTone = hasPending ? "warning" : "subtle";

  return (
    <Surface
      tone={headerTone}
      className="flex flex-col"
      data-testid="execution-panel"
    >
      <div className="flex items-center justify-between border-b border-black/5 px-3 py-2">
        <div className="flex items-center gap-2">
          <Badge tone={hasPending ? "warning" : "accent"} dot pulse={hasPending}>
            执行细节
          </Badge>
          {eventCount > 0 && (
            <span className="text-[11px] text-[var(--ink-soft)]">
              {eventCount} 个事件
            </span>
          )}
        </div>
        <button
          type="button"
          onClick={() => setCollapsed((v) => !v)}
          className="rounded-full px-2 py-0.5 text-[11px] text-[var(--ink-soft)] hover:bg-black/5"
          aria-expanded={!collapsed}
        >
          {collapsed ? "展开" : "收起"}
        </button>
      </div>
      {!collapsed && (
        <div className="flex flex-col gap-3 px-3 py-3">
          {execution.errorMessage && (
            <div className="rounded-lg border border-[var(--danger)]/30 bg-[var(--danger)]/8 px-3 py-2 text-xs text-[var(--danger)]">
              {execution.errorMessage}
            </div>
          )}
          {execution.milestones.length > 0 && (
            <div className="flex flex-col gap-1.5">
              <p className="text-[10px] font-semibold uppercase tracking-wider text-[var(--ink-soft)]">
                步骤
              </p>
              <div className="flex flex-col gap-1">
                {execution.milestones.slice(-3).map((m) => (
                  <div
                    key={m.id}
                    className="flex items-center gap-2 text-xs"
                  >
                    <Badge tone={milestoneStatusTone(m.status)} dot pulse={m.status === "running" || m.status === "awaiting_approval"}>
                      {STATUS_LABEL[m.status]}
                    </Badge>
                    <span className="text-[var(--ink)]">
                      {m.label.replace(/^[a-z]+:/, "")}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}
          {execution.pendingApproval && (
            <ApprovalCard
              approval={execution.pendingApproval}
              onApprove={approval?.onApprove}
              onDeny={approval?.onDeny}
              onCancel={approval?.onCancel}
            />
          )}
          {execution.events.length > 0 && (
            <div className="flex flex-col gap-1">
              <p className="text-[10px] font-semibold uppercase tracking-wider text-[var(--ink-soft)]">
                事件
              </p>
              <ul className="flex flex-col gap-1">
                {execution.events.map((e) => (
                  <EventRow key={e.id} event={e} />
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </Surface>
  );
}

function EventRow({ event }: { event: ExecutionEvent }) {
  const [open, setOpen] = useState(false);
  const hasDetail = Boolean(event.detail || event.preview);
  return (
    <li className="rounded-lg border border-black/[0.06] bg-white/55 px-2 py-1.5">
      <button
        type="button"
        onClick={() => hasDetail && setOpen((v) => !v)}
        className="flex w-full items-center gap-2 text-left text-xs"
        disabled={!hasDetail}
        aria-expanded={open}
      >
        <span
          className="grid h-5 w-5 shrink-0 place-items-center rounded-md font-mono text-[10px]"
          style={{
            background: "rgba(0,0,0,0.05)",
            color: "var(--ink-soft)",
          }}
        >
          {KIND_ICON[event.kind]}
        </span>
        <span className="flex-1 truncate text-[var(--ink)]">{event.name}</span>
        <Badge tone={statusTone(event.status)}>{STATUS_LABEL[event.status]}</Badge>
        {event.durationMs != null && (
          <span className="text-[10px] text-[var(--ink-soft)]">
            {Math.round(event.durationMs)}ms
          </span>
        )}
      </button>
      {open && hasDetail && (
        <pre className="mt-2 max-h-48 overflow-auto whitespace-pre-wrap break-words rounded-md bg-black/[0.04] p-2 text-[11px] text-[var(--ink-soft)]">
{event.detail || event.preview}
        </pre>
      )}
    </li>
  );
}

function ApprovalCard({
  approval,
  onApprove,
  onDeny,
  onCancel,
}: {
  approval: ApprovalRequestMsg;
  onApprove?: ApprovalHandlers["onApprove"];
  onDeny?: ApprovalHandlers["onDeny"];
  onCancel?: ApprovalHandlers["onCancel"];
}) {
  const [remember, setRemember] = useState<"session" | "always" | null>(null);
  return (
    <div
      className="flex flex-col gap-2 rounded-xl border border-amber-500/40 bg-amber-50/80 p-3"
      data-testid="execution-approval-card"
    >
      <div className="flex items-center gap-2">
        <Badge tone="warning" dot pulse>
          等待确认
        </Badge>
        <span className="font-mono text-xs text-[var(--ink)]">
          {approval.tool_name}
        </span>
      </div>
      {approval.arguments_summary && (
        <p className="text-xs text-[var(--ink-soft)]">
          {approval.arguments_summary}
        </p>
      )}
      <div className="flex flex-wrap items-center gap-1.5 text-[11px]">
        <label className="inline-flex items-center gap-1 text-[var(--ink-soft)]">
          <input
            type="checkbox"
            checked={remember === "session"}
            onChange={(e) =>
              setRemember(e.target.checked ? "session" : null)
            }
          />
          本会话
        </label>
        <div className="ml-auto flex flex-wrap gap-1.5">
          <Button size="sm" variant="primary" onClick={() => onApprove?.(approval.id, { remember })}>
            批准
          </Button>
          <Button size="sm" variant="danger" onClick={() => onDeny?.(approval.id)}>
            拒绝
          </Button>
          <Button size="sm" variant="ghost" onClick={() => onCancel?.(approval.id)}>
            取消
          </Button>
        </div>
      </div>
    </div>
  );
}