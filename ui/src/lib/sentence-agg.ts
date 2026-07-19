/**
 * Hybrid speech chunker for stream-to-speak TTS.
 * Hard sentence ends first; soft comma / length cuts; idle soft-flush.
 */

const HARD_END = /(?<=[。！？.!?…\n])/;
const SOFT_CHARS = new Set(["，", "、", "；", ";", ":"]);
const SOFT_MIN_CHARS = 48;
const HARD_MAX_CHARS = 72;
const IDLE_FLUSH_MS = 400;
const IDLE_FLUSH_MIN_CHARS = 12;

export type SoftFlushHandler = (chunks: string[]) => void;

export class SpeechChunkAggregator {
  private buf = "";
  private timer: ReturnType<typeof setTimeout> | null = null;
  private onSoftFlush: SoftFlushHandler | null = null;

  setOnSoftFlush(handler: SoftFlushHandler | null): void {
    this.onSoftFlush = handler;
  }

  push(token: string): string[] {
    if (!token) return [];
    this.clearTimer();
    this.buf += token;
    const out = this.extract();
    this.scheduleSoftFlush();
    return out;
  }

  /** Force emit remaining buffer (stream done / interrupt cleanup). */
  flush(): string | null {
    this.clearTimer();
    const leftover = this.buf.trim();
    this.buf = "";
    return leftover || null;
  }

  reset(): void {
    this.clearTimer();
    this.buf = "";
  }

  clearTimer(): void {
    if (this.timer != null) {
      clearTimeout(this.timer);
      this.timer = null;
    }
  }

  get buffer(): string {
    return this.buf;
  }

  private scheduleSoftFlush(): void {
    this.clearTimer();
    if (this.buf.trim().length < IDLE_FLUSH_MIN_CHARS) return;
    this.timer = setTimeout(() => {
      this.timer = null;
      if (this.buf.trim().length < IDLE_FLUSH_MIN_CHARS) return;
      const chunk = this.flush();
      if (chunk) this.onSoftFlush?.([chunk]);
    }, IDLE_FLUSH_MS);
  }

  private extract(): string[] {
    const completed: string[] = [];
    while (this.buf.length > 0) {
      const hardParts = this.buf.split(HARD_END);
      if (hardParts.length > 1) {
        completed.push(...hardParts.slice(0, -1).filter((p) => p.trim()));
        this.buf = hardParts[hardParts.length - 1] ?? "";
        continue;
      }

      if (this.buf.length >= SOFT_MIN_CHARS) {
        const softCut = this.findSoftCut(this.buf);
        if (softCut > 0) {
          const piece = this.buf.slice(0, softCut).trim();
          if (piece) completed.push(piece);
          this.buf = this.buf.slice(softCut);
          continue;
        }
      }

      if (this.buf.length >= HARD_MAX_CHARS) {
        const cut = this.findLengthCut(this.buf, HARD_MAX_CHARS);
        const piece = this.buf.slice(0, cut).trim();
        if (piece) completed.push(piece);
        this.buf = this.buf.slice(cut);
        continue;
      }

      break;
    }
    return completed;
  }

  private findSoftCut(s: string): number {
    // Prefer a soft boundary in the second half so chunks stay substantive.
    const minIdx = Math.floor(SOFT_MIN_CHARS / 2);
    for (let i = s.length - 1; i >= minIdx; i -= 1) {
      if (SOFT_CHARS.has(s[i]!)) return i + 1;
    }
    return -1;
  }

  private findLengthCut(s: string, maxChars: number): number {
    const window = s.slice(0, maxChars);
    for (const sep of ["，", "、", "；", ";", ":", " ", ",", "\n"]) {
      const idx = window.lastIndexOf(sep);
      if (idx >= Math.floor(maxChars / 3)) return idx + sep.length;
    }
    return maxChars;
  }
}

/** @deprecated Use SpeechChunkAggregator — kept for hard sentence-only callers. */
export class SentenceAggregator extends SpeechChunkAggregator {}

/** Split oversized text so each chunk fits the TTS per-request cap. */
export function chunkForTts(text: string, maxChars = HARD_MAX_CHARS): string[] {
  const s = text.trim();
  if (!s) return [];
  if (s.length <= maxChars) return [s];

  const out: string[] = [];
  let rest = s;
  while (rest.length > maxChars) {
    const window = rest.slice(0, maxChars + 1);
    let cut = -1;
    for (const sep of [
      "。",
      "！",
      "？",
      "；",
      "\n",
      ". ",
      "! ",
      "? ",
      "，",
      "、",
      ",",
      " ",
    ]) {
      const idx = window.lastIndexOf(sep);
      if (idx >= Math.floor(maxChars / 3)) {
        cut = idx + sep.length;
        break;
      }
    }
    if (cut <= 0) cut = maxChars;
    out.push(rest.slice(0, cut).trim());
    rest = rest.slice(cut).trim();
  }
  if (rest) out.push(rest);
  return out.filter(Boolean);
}
