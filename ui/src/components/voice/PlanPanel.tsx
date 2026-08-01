"use client";

import { useState } from "react";

import { Badge } from "@/components/ui/Badge";
import { Surface } from "@/components/ui/Surface";
import type {
  PlanPayload,
  PlanStepPayload,
  PlanStepStatus as PlanStepStatusType,
} from "@fae/client";

const STEP_STATUS_LABEL: Record<PlanStepStatusType, string> = {
  pending: "待开始",
  in_progress: "进行中",
  completed: "完成",
  blocked: "阻塞",
  cancelled: "已取消",
};

const STEP_STATUS_GLYPH: Record<PlanStepStatusType, string> = {
  pending: "○",
  in_progress: "▶",
  completed: "✓",
  blocked: "!",
  cancelled: "×",
};

function stepTone(status: PlanStepStatusType) {
  if (status === "completed") return "success" as const;
  if (status === "in_progress") return "accent" as const;
  if (status === "blocked") return "danger" as const;
  if (status === "cancelled") return "muted" as const;
  return "neutral" as const;
}

function progress(plan: PlanPayload) {
  const total = plan.steps.length;
  const done = plan.steps.filter((s) => s.status === "completed").length;
  const inProgress = plan.steps.filter((s) => s.status === "in_progress").length;
  const blocked = plan.steps.filter((s) => s.status === "blocked").length;
  return { total, done, inProgress, blocked };
}

export function PlanPanel({
  plan,
  suggested,
  onProvideStepInput,
  onAbandonPlan,
}: {
  plan: PlanPayload | null;
  suggested: boolean;
  onProvideStepInput?: (
    planId: string,
    stepIndex: number,
    inputText: string,
    kind: "answer" | "abort",
  ) => void;
  onAbandonPlan?: (planId: string) => void;
}) {
  const [collapsed, setCollapsed] = useState(false);

  if (!plan) {
    if (!suggested) {
      return (
        <Surface
          tone="subtle"
          className="hidden flex-col gap-1 p-3 xl:flex"
          data-testid="plan-panel-empty"
        >
          <p className="text-xs font-semibold uppercase tracking-wider text-[var(--ink-soft)]">
            计划
          </p>
          <p className="text-xs text-[var(--ink-soft)]">
            多步任务时，Agent 会先把计划显示在这里。
          </p>
        </Surface>
      );
    }
    return (
      <Surface
        tone="warning"
        className="hidden flex-col gap-1 p-3 xl:flex"
        data-testid="plan-panel-suggested"
      >
        <p className="text-xs font-semibold uppercase tracking-wider text-[var(--ink-soft)]">
          计划
        </p>
        <p className="text-xs text-[var(--ink)]">
          正在判断是否需要计划…
        </p>
      </Surface>
    );
  }

  const { total, done, inProgress, blocked } = progress(plan);
  const isActive = plan.status === "active";
  const isCompleted = plan.status === "completed";
  const headerTone = isCompleted ? "default" : isActive && inProgress > 0 ? "subtle" : "subtle";

  return (
    <Surface
      tone={headerTone}
      className="flex flex-col"
      data-testid="plan-panel"
    >
      <div className="flex items-center justify-between border-b border-black/5 px-3 py-2">
        <div className="flex items-center gap-2">
          <Badge
            tone={isCompleted ? "success" : "accent"}
            dot
            pulse={isActive && inProgress > 0}
          >
            计划
          </Badge>
          <span className="text-[11px] text-[var(--ink-soft)]">
            {done}/{total}
          </span>
          {blocked > 0 && (
            <Badge tone="danger" data-testid="plan-blocked-count">
              {blocked} 项阻塞
            </Badge>
          )}
        </div>
        <div className="flex items-center gap-1">
          {isActive && onAbandonPlan && (
            <button
              type="button"
              onClick={() => onAbandonPlan(plan.id)}
              className="rounded-full px-2 py-0.5 text-[11px] text-[var(--ink-soft)] hover:bg-black/5"
              data-testid="plan-abandon"
            >
              放弃计划
            </button>
          )}
          <button
            type="button"
            onClick={() => setCollapsed((v) => !v)}
            className="rounded-full px-2 py-0.5 text-[11px] text-[var(--ink-soft)] hover:bg-black/5"
            aria-expanded={!collapsed}
            data-testid="plan-panel-toggle"
          >
            {collapsed ? "展开" : "收起"}
          </button>
        </div>
      </div>
      {!collapsed && (
        <div className="flex flex-col gap-3 px-3 py-3">
          <div>
            <p className="text-[13px] font-semibold text-[var(--ink)]">
              {plan.title}
            </p>
            {plan.summary && (
              <p className="mt-1 text-[11px] text-[var(--ink-soft)]">
                {plan.summary}
              </p>
            )}
          </div>
          {plan.steps.length > 0 && (
            <ol className="flex flex-col gap-1.5">
              {plan.steps.map((step) => (
                <StepRow
                  key={step.id}
                  step={step}
                  planId={plan.id}
                  onProvideStepInput={onProvideStepInput}
                />
              ))}
            </ol>
          )}
        </div>
      )}
    </Surface>
  );
}

function StepRow({
  step,
  planId,
  onProvideStepInput,
}: {
  step: PlanStepPayload;
  planId: string;
  onProvideStepInput?: (
    planId: string,
    stepIndex: number,
    inputText: string,
    kind: "answer" | "abort",
  ) => void;
}) {
  const [answerOpen, setAnswerOpen] = useState(false);
  const [answerDraft, setAnswerDraft] = useState("");
  const isBlocked = step.status === "blocked";
  const showActions = isBlocked && Boolean(onProvideStepInput);
  return (
    <li
      className={
        isBlocked
          ? "flex items-start gap-2 rounded-lg border border-[var(--danger)]/40 bg-[var(--danger)]/5 px-2 py-1.5 text-xs"
          : "flex items-start gap-2 rounded-lg border border-black/[0.06] bg-white/55 px-2 py-1.5 text-xs"
      }
      data-testid={`plan-step-${step.index}`}
    >
      <span
        className="grid h-5 w-5 shrink-0 place-items-center rounded-md font-mono text-[11px]"
        style={{
          background: "rgba(0,0,0,0.05)",
          color: isBlocked ? "var(--danger)" : "var(--ink-soft)",
        }}
        aria-hidden
      >
        {STEP_STATUS_GLYPH[step.status]}
      </span>
      <div className="flex-1 min-w-0">
        <div className="flex flex-wrap items-center gap-1.5">
          <span
            className={
              step.status === "completed"
                ? "line-through text-[var(--ink-soft)]"
                : "text-[var(--ink)]"
            }
          >
            {step.title}
          </span>
          <Badge tone={stepTone(step.status)}>{STEP_STATUS_LABEL[step.status]}</Badge>
        </div>
        {step.acceptance && (
          <p className="mt-0.5 text-[11px] text-[var(--ink-soft)]">
            验收：{step.acceptance}
          </p>
        )}
        {isBlocked && step.note && (
          <p className="mt-0.5 text-[11px] text-[var(--danger)]">
            原因：{step.note}
          </p>
        )}
        {showActions && (
          <div className="mt-1 flex flex-col gap-1.5">
            {!answerOpen ? (
              <div className="flex flex-wrap gap-1.5">
                <button
                  type="button"
                  onClick={() => setAnswerOpen(true)}
                  className="rounded-md border border-[var(--danger)]/40 px-2 py-0.5 text-[11px] text-[var(--danger)] hover:bg-[var(--danger)]/10"
                  data-testid={`plan-step-answer-${step.index}`}
                >
                  补一条说明
                </button>
                <button
                  type="button"
                  onClick={() => onProvideStepInput?.(planId, step.index, "", "abort")}
                  className="rounded-md border border-black/10 px-2 py-0.5 text-[11px] text-[var(--ink-soft)] hover:bg-black/5"
                  data-testid={`plan-step-cancel-${step.index}`}
                >
                  取消这一步
                </button>
              </div>
            ) : (
              <div className="flex flex-col gap-1">
                <textarea
                  value={answerDraft}
                  onChange={(e) => setAnswerDraft(e.target.value)}
                  placeholder="把缺失的信息告诉 Agent…"
                  rows={2}
                  className="w-full resize-none rounded-md border border-black/10 bg-white/80 px-2 py-1 text-[11px] text-[var(--ink)] outline-none focus:border-[var(--danger)]"
                  data-testid={`plan-step-answer-input-${step.index}`}
                />
                <div className="flex gap-1.5">
                  <button
                    type="button"
                    onClick={() => {
                      onProvideStepInput?.(
                        planId,
                        step.index,
                        answerDraft.trim(),
                        "answer",
                      );
                      setAnswerDraft("");
                      setAnswerOpen(false);
                    }}
                    disabled={!answerDraft.trim()}
                    className="rounded-md bg-[var(--danger)] px-2 py-0.5 text-[11px] text-white disabled:opacity-50"
                    data-testid={`plan-step-answer-send-${step.index}`}
                  >
                    发送
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      setAnswerDraft("");
                      setAnswerOpen(false);
                    }}
                    className="rounded-md border border-black/10 px-2 py-0.5 text-[11px] text-[var(--ink-soft)] hover:bg-black/5"
                  >
                    收起
                  </button>
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </li>
  );
}