import { stripThinking } from "@/lib/strip-thinking";

/**
 * Convert assistant markdown into plain text suitable for TTS.
 * Tables / code fences are dropped entirely (not read aloud).
 *
 * Also drops everything that makes spoken output unstable:
 *   - emoji + pictograph runs (forced laughters land here)
 *   - ASCII kaomoji / wavy punctuation / invisible Unicode
 *   - English laugh fillers (lol / lmao / haha / hehe / …)
 *
 * The mirror of this stripper lives at backend/src/fae/tts/speakable.py —
 * keep the two in sync when touching regex ranges.
 */

const EMOJI_RANGES =
  "[" +
  // Variation selectors + ZWJ ride along with their base emoji.
  "\u200d\uFE00-\uFE0F" +
  // Skin-tone modifiers.
  "\u{1F3FB}-\u{1F3FF}" +
  // Flags.
  "\u{1F1E0}-\u{1F1FF}" +
  // Misc symbols, pictographs, transport, arrows, etc.
  "\u{1F300}-\u{1F5FF}" +
  "\u{1F600}-\u{1F64F}" +
  "\u{1F680}-\u{1F6FF}" +
  "\u{1F700}-\u{1F7FF}" +
  "\u{1F800}-\u{1F8FF}" +
  "\u{1F900}-\u{1F9FF}" +
  "\u{1FA00}-\u{1FA6F}" +
  "\u{1FA70}-\u{1FAFF}" +
  "\u{1FB00}-\u{1FBFF}" +
  // ASCII-era pictographs / dingbats / misc technical.
  "\u2600-\u26FF" +
  "\u2700-\u27BF" +
  "\u2300-\u23FF" +
  "\u2B00-\u2BFF" +
  "\u2900-\u297F" +
  "]";

// Emoji run with ZWJ joiners. Matches one or more pictographs and any variation
// selectors / skin tones hanging off them. Replace with a single space to keep
// the surrounding word boundaries readable.
const EMOJI_RUN = new RegExp(`${EMOJI_RANGES}(?:${EMOJI_RANGES})*`, "gu");

// Invisible / bidi / formatting characters that survive naive strippers.
const INVISIBLE = /[\u200B-\u200F\u202A-\u202E\u2060-\u206F\uFEFF\u00AD]/g;
// ASCII + ASCII-parenthesised kaomoji the model occasionally emotes. Covers
// both Western faces (`:)` `;(` `=D`) and the parenthesised CJK-flavoured
// variants like `(^_^)`, `(*^▽^*)`, `(T_T)`. Emoji ranges already catch the
// pure-CJK ones (╯°□°).
const ASCII_KAOMOJI = new RegExp(
  "(?:" +
    "[:;=8][\\-o*']?[\\)\\]\\[\\(dDpP/\\\\{}|><*^@_~]+" +
    "|" +
    "[\\(\\[\\]]+[\\-_o*^~]?[_\\-^～~\\.\\\\]*" +
    "[\\\\^▽°´☆\\*][\\-_o*^~]?[\\)\\]\\[]+" +
    "|" +
    "[\\)\\]\\[\\(dDpP/\\\\{}|><*^@]+[\\-o*']?[:;=]" +
    ")",
  "g",
);
// English laugh + filler tokens, with optional trailing wave. Word-boundary
// anchored so we do not mutilate real words ("lolcat", "hahawehi" — rare but
// worth catching).
const FILLERS =
  /\b(?:lmao+|lol+|rofl+|haha+|hehe+|hihi+|x[dD]|omg|wtf|btw|idk|smh|fml|yolo|nvm|imo|imho|tbh)+\b[~～]?/gi;
// Excessive trailing / leading punctuation that drives singsong cadence.
const PUNCT_RUN = /([。！？!?~～.,，、；：])\1{1,}/g;
// Standalone wavy punctuation around words.
const WAVY = /\s*[~～]+\s*/g;

function dropEmoji(s: string): string {
  return s.replace(EMOJI_RUN, " ");
}

function normalizePunct(s: string): string {
  let out = s.replace(PUNCT_RUN, "$1");
  out = out.replace(/\u3000/g, " ");
  return out;
}

function collapse(s: string): string {
  return s
    .replace(/[ \t]{2,}/g, " ")
    .replace(/[ \t]+\n/g, "\n")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

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

  // Voice hygiene — applied after markdown cleanup so emoji hidden inside
  // fenced code blocks / table cells still get caught.
  s = dropEmoji(s);
  s = s.replace(INVISIBLE, " ");
  s = s.replace(ASCII_KAOMOJI, " ");
  s = s.replace(FILLERS, " ");
  s = s.replace(WAVY, " ");
  s = normalizePunct(s);
  s = collapse(s);
  return s;
}
