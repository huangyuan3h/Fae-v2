import { stripThinking } from "@/lib/strip-thinking";

/**
 * Convert assistant markdown into plain text suitable for TTS.
 * Tables / code fences are dropped entirely (not read aloud).
 */
export function toSpeakableText(text: string): string {
  let s = stripThinking(text);
  if (!s) return "";

  // Repair collapsed tables before stripping so row detection works.
  s = s.replace(/\|\|/g, "|\n|");

  // Drop fenced code entirely (do not read source aloud).
  s = s.replace(/```[\w+-]*\n?[\s\S]*?```/g, "\n");

  // Drop GFM pipe tables (header + separator + body rows).
  s = s.replace(/(?:^|\n)(?:\|[^\n]*\|(?:\n|$))+/g, "\n");

  // Drop leftover single table-like lines
  s = s.replace(/^\s*\|.*\|\s*$/gm, "");

  // Inline code → keep inner text
  s = s.replace(/`([^`]+)`/g, "$1");

  // Images / links → alt or label
  s = s.replace(/!\[([^\]]*)\]\([^)]+\)/g, "$1");
  s = s.replace(/\[([^\]]+)\]\([^)]+\)/g, "$1");

  // Headings, blockquotes, hr
  s = s.replace(/^#{1,6}\s+/gm, "");
  s = s.replace(/^>\s?/gm, "");
  s = s.replace(/^[-*_]{3,}\s*$/gm, "");

  // Bold / italic / strikethrough
  s = s.replace(/\*\*\*([^*]+)\*\*\*/g, "$1");
  s = s.replace(/___([^_]+)___/g, "$1");
  s = s.replace(/\*\*([^*]+)\*\*/g, "$1");
  s = s.replace(/__([^_]+)__/g, "$1");
  s = s.replace(/~~([^~]+)~~/g, "$1");
  s = s.replace(/\*([^*\n]+)\*/g, "$1");
  s = s.replace(/_([^_\n]+)_/g, "$1");

  // Lists / numbered
  s = s.replace(/^\s*[-*+]\s+/gm, "");
  s = s.replace(/^\s*\d+\.\s+/gm, "");

  // Leftover pipes / markdown noise
  s = s.replace(/\|/g, " ");
  s = s.replace(/[*_~`#]/g, "");

  return s
    .replace(/[ \t]+\n/g, "\n")
    .replace(/\n{3,}/g, "\n\n")
    .replace(/[ \t]{2,}/g, " ")
    .trim();
}
