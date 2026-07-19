"use client";

import type { ChatLine } from "@/hooks/useVoiceSession";
import { stripThinking } from "@/lib/strip-thinking";

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
        const content =
          line.role === "assistant"
            ? stripThinking(line.content)
            : line.content;
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
            {content || "…"}
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
