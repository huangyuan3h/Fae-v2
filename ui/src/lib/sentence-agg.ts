/**
 * Accumulate streaming LLM tokens into speakable sentences.
 * Aligned with backend SentenceAggregator (CJK + Latin boundaries).
 */

const SENTENCE_END = /(?<=[。！？.!?…\n])/;

export class SentenceAggregator {
  private buf = "";

  push(token: string): string[] {
    if (!token) return [];
    this.buf += token;
    const parts = this.buf.split(SENTENCE_END);
    if (parts.length === 1) return [];
    const completed = parts.slice(0, -1).filter((p) => p.trim());
    this.buf = parts[parts.length - 1] ?? "";
    return completed;
  }

  flush(): string | null {
    const leftover = this.buf.trim();
    this.buf = "";
    return leftover || null;
  }

  reset(): void {
    this.buf = "";
  }

  get buffer(): string {
    return this.buf;
  }
}

/** Split oversized sentences so each chunk fits the TTS per-request cap. */
export function chunkForTts(text: string, maxChars = 120): string[] {
  const s = text.trim();
  if (!s) return [];
  if (s.length <= maxChars) return [s];

  const out: string[] = [];
  let rest = s;
  while (rest.length > maxChars) {
    const window = rest.slice(0, maxChars + 1);
    let cut = -1;
    for (const sep of ["。", "！", "？", "；", "\n", ". ", "! ", "? ", "，", ",", " "]) {
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
