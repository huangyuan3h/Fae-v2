"use client";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import type {
  ChatLine,
  TurnExecution,
} from "@/hooks/useVoiceSession";
import { normalizeMarkdownForDisplay } from "@/lib/markdown-display";
import { isThinkingStreaming, stripThinking } from "@/lib/strip-thinking";
import { ExecutionView } from "./ExecutionView";

const mdClassName =
  "fae-md mt-1 block w-full " +
  "[&_h1]:mb-2 [&_h1]:mt-3 [&_h1]:text-lg [&_h1]:font-bold " +
  "[&_h2]:mb-2 [&_h2]:mt-3 [&_h2]:text-base [&_h2]:font-bold " +
  "[&_h3]:mb-1 [&_h3]:mt-2 [&_h3]:text-sm [&_h3]:font-semibold " +
  "[&_li]:my-0.5 [&_ol]:my-2 [&_ol]:list-decimal [&_ol]:pl-5 " +
  "[&_p]:my-1.5 [&_strong]:font-semibold [&_strong]:text-[var(--ink)] " +
  "[&_ul]:my-2 [&_ul]:list-disc [&_ul]:pl-5 " +
  "[&_hr]:my-3 [&_hr]:border-black/10 " +
  "[&_table]:my-3 [&_table]:w-full [&_table]:border-collapse [&_table]:text-sm " +
  "[&_th]:border [&_th]:border-black/15 [&_th]:bg-black/[0.04] [&_th]:px-2 [&_th]:py-1.5 [&_th]:text-left [&_th]:font-semibold " +
  "[&_td]:border [&_td]:border-black/10 [&_td]:px-2 [&_td]:py-1.5 " +
  "[&_pre]:my-2 [&_pre]:overflow-x-auto [&_pre]:rounded-md [&_pre]:bg-black/[0.04] [&_pre]:p-3 " +
  "[&_code]:text-[0.9em]";

function roleLabel(role: ChatLine["role"]): string {
  if (role === "user") return "你";
  if (role === "system") return "系统";
  return "FAE";
}

type ApprovalHandlers = {
  onApprove?: (
    approvalId: string,
    decision: { remember?: "session" | "always" | null; confirm?: boolean },
  ) => void;
  onDeny?: (approvalId: string) => void;
  onCancel?: (approvalId: string) => void;
};

export function ChatTranscript({
  lines,
  partial,
  turnExecutions,
  approval,
}: {
  lines: ChatLine[];
  partial: string;
  turnExecutions: Record<string, TurnExecution>;
  approval?: ApprovalHandlers;
}) {
  return (
    <div
      className="mx-auto flex w-full max-w-xl flex-col gap-3 px-4 py-2 text-left"
      data-testid="chat-transcript"
    >
      {lines.map((line) => {
        const visible =
          line.role === "assistant"
            ? normalizeMarkdownForDisplay(stripThinking(line.content))
            : line.content;
        const thinking =
          line.role === "assistant" && isThinkingStreaming(line.content);
        const isSystem = line.role === "system";
        const execution =
          line.role === "assistant" ? turnExecutions[line.id] : undefined;
        return (
          <div key={line.id} data-testid={`chat-line-${line.role}`}>
            <div
              className="text-[15px] leading-relaxed"
              style={{
                color: isSystem
                  ? "var(--ink-soft)"
                  : line.role === "user"
                    ? "var(--ink)"
                    : "var(--ink-soft)",
                fontFamily: "var(--font-body)",
                opacity: isSystem ? 0.9 : 1,
                background: isSystem ? "rgba(0,0,0,0.03)" : undefined,
                borderRadius: isSystem ? 12 : undefined,
                padding: isSystem ? "8px 12px" : undefined,
              }}
            >
              <span
                className="mr-2 text-xs uppercase tracking-wider"
                style={{
                  color: isSystem ? "var(--ink-soft)" : "var(--accent)",
                  fontFamily: "var(--font-display)",
                }}
              >
                {roleLabel(line.role)}
              </span>
              {line.role === "assistant" ? (
                visible ? (
                  <div className={mdClassName}>
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>
                      {visible}
                    </ReactMarkdown>
                  </div>
                ) : thinking ? (
                  <span className="opacity-70">思考中…</span>
                ) : (
                  "…"
                )
              ) : (
                line.content || "…"
              )}
            </div>
            {execution && (
              <ExecutionView
                execution={execution}
                onApprove={approval?.onApprove}
                onDeny={approval?.onDeny}
                onCancel={approval?.onCancel}
              />
            )}
          </div>
        );
      })}
      {partial ? (
        <div className="text-[15px] text-[var(--ink-soft)] opacity-70">
          <span
            className="mr-2 text-xs uppercase tracking-wider"
            style={{ color: "var(--accent)", fontFamily: "var(--font-display)" }}
          >
            你
          </span>
          {partial}
        </div>
      ) : null}
    </div>
  );
}
