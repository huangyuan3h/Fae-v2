"use client";

import type { ChatStep } from "@/hooks/useVoiceSession";

const statusLabel: Record<ChatStep["status"], string> = {
  available: "待命",
  running: "进行中",
  done: "完成",
  error: "失败",
};

export function AgentSteps({ steps }: { steps: ChatStep[] }) {
  if (steps.length === 0) return null;
  const primary = steps.find((step) => step.role === "primary");
  const secondary = steps.filter((step) => step.id !== primary?.id);

  return (
    <details
      className="mx-auto mb-3 w-full max-w-xl rounded-2xl border border-black/10 bg-white/55 px-4 py-3"
      data-testid="agent-steps"
      open
    >
      <summary className="cursor-pointer list-none text-sm font-semibold text-[var(--ink)]">
        执行轨迹
        <span className="ml-2 text-xs font-normal text-[var(--ink-soft)]">
          {steps.length} 步
        </span>
      </summary>
      <div className="mt-3 space-y-2">
        {primary && <StepRow step={primary} />}
        {secondary.length > 0 && (
          <div className="ml-3 space-y-2 border-l border-black/10 pl-3">
            {secondary.map((step) => (
              <StepRow key={step.id} step={step} />
            ))}
          </div>
        )}
      </div>
    </details>
  );
}

function StepRow({ step }: { step: ChatStep }) {
  return (
    <details className="rounded-xl bg-black/[0.025] px-3 py-2">
      <summary className="flex cursor-pointer list-none items-center gap-2 text-sm">
        <span
          className={`h-2 w-2 rounded-full ${
            step.status === "error"
              ? "bg-[var(--danger)]"
              : step.status === "running"
                ? "animate-pulse bg-[var(--accent)]"
                : "bg-black/25"
          }`}
        />
        <span className="font-medium text-[var(--ink)]">{step.name}</span>
        <span className="rounded-full bg-white/70 px-2 py-0.5 text-[10px] text-[var(--ink-soft)]">
          {step.role === "primary" ? "主技能" : step.kind === "skill" ? "次技能" : step.kind}
        </span>
        <span className="ml-auto text-xs text-[var(--ink-soft)]">
          {statusLabel[step.status]}
          {step.score != null ? ` · ${step.score.toFixed(2)}` : ""}
        </span>
      </summary>
      {step.detail && (
        <pre className="mt-2 max-h-48 overflow-auto whitespace-pre-wrap break-words rounded-lg bg-black/[0.04] p-2 text-xs text-[var(--ink-soft)]">
          {step.detail}
        </pre>
      )}
    </details>
  );
}
