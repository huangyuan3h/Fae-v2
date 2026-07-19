import { stripThinking } from "@/lib/strip-thinking";

/**
 * Convert assistant markdown into plain text suitable for TTS.
 * Strips thinking blocks, headings markers, emphasis, lists, links, etc.
 */
export function toSpeakableText(text: string): string {
  let s = stripThinking(text);
  if (!s) return "";

  // Fenced / inline code → keep inner text only
  s = s.replace(/```[\w+-]*\n?([\s\S]*?)```/g, "$1");
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

  // Tables
  s = s.replace(/\|/g, " ");

  // Leftover markdown punctuation noise
  s = s.replace(/[*_~`#]/g, "");

  return s
    .replace(/[ \t]+\n/g, "\n")
    .replace(/\n{3,}/g, "\n\n")
    .replace(/[ \t]{2,}/g, " ")
    .trim();
}
