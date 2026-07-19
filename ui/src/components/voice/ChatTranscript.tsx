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

export function ChatTranscript({
  lines,
  partial,
}: {
  lines: ChatLine[];
  partial: string;
}) {
  return (
    <div className="mx-auto flex w-full max-w-xl flex-col gap-3 px-4 py-2 text-left">
      {lines.map((line) => {
        const visible =
          line.role === "assistant"
            ? normalizeMarkdownForDisplay(stripThinking(line.content))
            : line.content;
        const thinking =
          line.role === "assistant" && isThinkingStreaming(line.content);
        return (
          <div
            key={line.id}
            className="text-[15px] leading-relaxed"
            style={{
              color: line.role === "user" ? "var(--ink)" : "var(--ink-soft)",
              fontFamily: "var(--font-body)",
            }}
          >
            <span
              className="mr-2 text-xs uppercase tracking-wider"
              style={{
                color: "var(--accent)",
                fontFamily: "var(--font-display)",
              }}
            >
              {line.role === "user" ? "你" : "FAE"}
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
