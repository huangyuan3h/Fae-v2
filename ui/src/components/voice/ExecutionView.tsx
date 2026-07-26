"use client";

import { useMemo, useState } from "react";

import type {
  ApprovalRequestMsg,
  ExecutionEvent,
  TurnExecution,
} from "@/hooks/useVoiceSession";

type ExecutionViewProps = {
  execution: TurnExecution;
  onApprove?: (
    approvalId: string,
    decision: { remember?: "session" | "always" | null; confirm?: boolean },
  ) => void;
  onDeny?: (approvalId: string, reason?: string) => void;
  onCancel?: (approvalId: string) => void;
};

const STATUS_DOT: Record<ExecutionEvent["status"], string> = {
  running: "bg-[var(--accent)] animate-pulse",
  done: "bg-emerald-500",
  error: "bg-[var(--danger)]",
  awaiting_approval: "bg-amber-500 animate-pulse",
  approved: "bg-emerald-500",
  denied: "bg-[var(--danger)]",
  expired: "bg-[var(--danger)]",
  cancelled: "bg-black/30",
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

const KIND_GLYPH: Record<ExecutionEvent["kind"], string> = {
  skill: "·",
  subagent: "↪",
  tool: "▶",
  approval: "⏸",
};

export function ExecutionView({
  execution,
  onApprove,
  onDeny,
  onCancel,
}: ExecutionViewProps) {
  const [expanded, setExpanded] = useState(false);
  const lastMilestone = execution.milestones[execution.milestones.length - 1];
  const summary = useMemo(() => {
    if (lastMilestone) {
      const dot = STATUS_DOT[lastMilestone.status];
      return { dot, status: STATUS_LABEL[lastMilestone.status] };
    }
    if (execution.errorMessage) {
      return { dot: STATUS_DOT.error, status: "失败" };
    }
    return null;
  }, [lastMilestone, execution.errorMessage]);
  if (!execution.milestones.length && !execution.pendingApproval && !execution.errorMessage) {
    return null;
  }

  return (
    <div
      className="mt-2 rounded-2xl border border-black/10 bg-white/55 px-4 py-2.5"
      data-testid={`execution-view`}
    >
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 text-xs">
        {execution.milestones.slice(-3).map((m) => {
          const dot = STATUS_DOT[m.status];
          const label = `${m.label.replace(/^[a-z]+:/, "")} · ${STATUS_LABEL[m.status]}`;
          return (
            <span
              key={m.id}
              className="inline-flex items-center gap-1.5 rounded-full bg-black/[0.04] px-2 py-0.5"
            >
              <span className={`h-1.5 w-1.5 rounded-full ${dot}`} />
              <span className="text-[var(--ink)]">{label}</span>
            </span>
          );
        })}
        {execution.pendingApproval && (
          <ApprovalCard
            approval={execution.pendingApproval}
            onApprove={onApprove}
            onDeny={onDeny}
            onCancel={onCancel}
          />
        )}
        {execution.errorMessage && (
          <span className="rounded-full bg-[var(--danger)]/10 px-2 py-0.5 text-[var(--danger)]">
            {execution.errorMessage}
          </span>
        )}
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          className="ml-auto rounded-full border border-black/10 bg-white/70 px-2.5 py-0.5 text-[11px] text-[var(--ink-soft)] hover:bg-black/5"
          aria-expanded={expanded}
        >
          {expanded ? "收起细节" : `细节 ${execution.events.length}`}
        </button>
      </div>
      {summary && !execution.pendingApproval && !lastMilestone && (
        <span className="inline-flex items-center gap-1.5 text-xs">
          <span className={`h-1.5 w-1.5 rounded-full ${summary.dot}`} />
          <span className="text-[var(--ink-soft)]">{summary.status}</span>
        </span>
      )}
      {expanded && (
        <div className="mt-3 space-y-2">
          {execution.events.length === 0 ? (
            <p className="text-xs text-[var(--ink-soft)]">
              还没有工具或子代理事件 — 等待模型选择下一步动作。
            </p>
          ) : (
            execution.events.map((e) => <EventRow key={e.id} event={e} />)
          )}
        </div>
      )}
    </div>
  );
}

function EventRow({ event }: { event: ExecutionEvent }) {
  return (
    <details className="rounded-lg bg-black/[0.025] px-3 py-2 text-xs">
      <summary className="flex cursor-pointer list-none items-center gap-2">
        <span className={`h-1.5 w-1.5 rounded-full ${STATUS_DOT[event.status]}`} />
        <span className="text-[var(--ink-soft)] font-mono">
          {KIND_GLYPH[event.kind]}
        </span>
        <span className="font-medium text-[var(--ink)]">{event.name}</span>
        <span className="rounded-full bg-white/70 px-2 py-0.5 text-[10px] text-[var(--ink-soft)]">
          {STATUS_LABEL[event.status]}
        </span>
        {event.durationMs != null && (
          <span className="text-[10px] text-[var(--ink-soft)]">
            {Math.round(event.durationMs)}ms
          </span>
        )}
        {event.errorCode && (
          <span className="rounded bg-[var(--danger)]/10 px-1.5 py-0.5 text-[10px] text-[var(--danger)]">
            {event.errorCode}
          </span>
        )}
      </summary>
      {(event.detail || event.preview) && (
        <pre className="mt-2 max-h-48 overflow-auto whitespace-pre-wrap break-words rounded-md bg-black/[0.04] p-2 text-[11px] text-[var(--ink-soft)]">
{event.detail || event.preview}
        </pre>
      )}
    </details>
  );
}

function ApprovalCard({
  approval,
  onApprove,
  onDeny,
  onCancel,
}: {
  approval: ApprovalRequestMsg;
  onApprove?: ExecutionViewProps["onApprove"];
  onDeny?: ExecutionViewProps["onDeny"];
  onCancel?: ExecutionViewProps["onCancel"];
}) {
  const [remember, setRemember] = useState<"session" | "always" | null>(null);
  return (
    <div
      className="flex flex-1 flex-wrap items-center gap-2 rounded-xl border border-amber-500/30 bg-amber-50/70 px-2.5 py-1.5"
      data-testid="execution-approval-card"
    >
      <span className="text-[var(--ink)]">
        等待您确认 <span className="font-mono">{approval.tool_name}</span>
      </span>
      <span className="text-[var(--ink-soft)]">
        {approval.arguments_summary}
      </span>
      <span className="ml-auto flex flex-wrap items-center gap-1.5 text-[11px]">
        <label className="inline-flex items-center gap-1">
          <input
            type="checkbox"
            checked={remember === "session"}
            onChange={(e) =>
              setRemember(e.target.checked ? "session" : null)
            }
          />
          本会话
        </label>
        <button
          type="button"
          onClick={() => onApprove?.(approval.id, { remember })}
          className="rounded-md bg-emerald-500 px-2.5 py-1 font-semibold text-white"
        >
          批准
        </button>
        <button
          type="button"
          onClick={() => onDeny?.(approval.id)}
          className="rounded-md bg-[var(--danger)] px-2.5 py-1 font-semibold text-white"
        >
          拒绝
        </button>
        <button
          type="button"
          onClick={() => onCancel?.(approval.id)}
          className="rounded-md border border-black/15 px-2.5 py-1 text-[var(--ink)]"
        >
          取消
        </button>
      </span>
    </div>
  );
}
