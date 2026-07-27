"use client";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import type { ChatLine } from "@/hooks/useVoiceSession";
import { normalizeMarkdownForDisplay } from "@/lib/markdown-display";
import { isThinkingStreaming, stripThinking } from "@/lib/strip-thinking";

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

export function ChatTranscript({
  lines,
  partial,
}: {
  lines: ChatLine[];
  partial: string;
}) {
  return (
    <div
      className="mx-auto flex w-full max-w-2xl flex-col gap-4 px-4 py-2 text-left"
      data-testid="chat-transcript"
    >
      {lines.map((line) => {
        const visible =
          line.role === "assistant"
            ? normalizeMarkdownForDisplay(stripThinking(line.content))
            : line.content;
        const thinking =
          line.role === "assistant" && isThinkingStreaming(line.content);
        const isUser = line.role === "user";
        const isSystem = line.role === "system";
        return (
          <div
            key={line.id}
            data-testid={`chat-line-${line.role}`}
            className={
              isUser
                ? "flex justify-end"
                : isSystem
                  ? "mx-auto w-full max-w-md"
                  : "flex justify-start"
            }
          >
            <div
              className={
                isUser
                  ? "rounded-2xl rounded-br-sm bg-[var(--accent)] px-4 py-2.5 text-[15px] leading-relaxed text-white shadow-sm"
                  : isSystem
                    ? "rounded-xl bg-black/[0.04] px-3 py-1.5 text-[13px] text-[var(--ink-soft)]"
                    : "max-w-full rounded-2xl rounded-bl-sm bg-white/75 px-4 py-2.5 text-[15px] leading-relaxed text-[var(--ink)] shadow-sm ring-1 ring-black/[0.06]"
              }
            >
              <span
                className="mb-1 block text-[10px] font-semibold uppercase tracking-[0.18em]"
                style={{
                  color: isUser
                    ? "rgba(255,255,255,0.7)"
                    : isSystem
                      ? "var(--ink-soft)"
                      : "var(--accent)",
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
          </div>
        );
      })}
      {partial ? (
        <div className="flex justify-end" data-testid="chat-line-partial">
          <div className="rounded-2xl rounded-br-sm bg-[var(--accent)]/60 px-4 py-2.5 text-[15px] leading-relaxed text-white opacity-80">
            <span
              className="mb-1 block text-[10px] font-semibold uppercase tracking-[0.18em]"
              style={{ color: "rgba(255,255,255,0.7)", fontFamily: "var(--font-display)" }}
            >
              你
            </span>
            {partial}
          </div>
        </div>
      ) : null}
    </div>
  );
}
