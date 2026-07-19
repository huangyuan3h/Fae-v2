/**
 * Remove model "thinking" / reasoning blocks from assistant text.
 * Handles complete tags, incomplete streams, and common markdown fences.
 */

const THINK_TAG =
  /<think(?:ing)?\b[^>]*>[\s\S]*?<\/think(?:ing)?>/gi;

const THINK_FENCE =
  /```(?:thinking|reasoning|thought)\s*\n[\s\S]*?```/gi;

const OPEN_THINK_TAG = /<think(?:ing)?\b[^>]*>/i;
const OPEN_THINK_FENCE = /```(?:thinking|reasoning|thought)\s*\n/i;

export function stripThinking(text: string): string {
  if (!text) return text;

  let out = text.replace(THINK_TAG, "").replace(THINK_FENCE, "");

  // Streaming: drop everything from an unclosed think opener onward.
  const tagOpen = out.search(OPEN_THINK_TAG);
  if (tagOpen >= 0) out = out.slice(0, tagOpen);

  const fenceOpen = out.search(OPEN_THINK_FENCE);
  if (fenceOpen >= 0) out = out.slice(0, fenceOpen);

  return out.replace(/^\s+/, "").replace(/\s+$/, "");
}

/** True while the model is still inside an unclosed thinking block. */
export function isThinkingStreaming(text: string): boolean {
  if (!text) return false;
  const withoutClosed = text
    .replace(THINK_TAG, "")
    .replace(THINK_FENCE, "");
  return (
    withoutClosed.search(OPEN_THINK_TAG) >= 0 ||
    withoutClosed.search(OPEN_THINK_FENCE) >= 0
  );
}
