export type TtsPrefs = {
  voice: string;
  speed: number;
  language: string;
};

const STORAGE_KEY = "fae.ttsPrefs";
export const TTS_PREFS_CHANGED_EVENT = "fae:tts-prefs-changed";

export const DEFAULT_TTS_PREFS: TtsPrefs = {
  voice: "Vivian",
  speed: 1.2,
  language: "Chinese",
};

function clampSpeed(n: number): number {
  if (!Number.isFinite(n)) return DEFAULT_TTS_PREFS.speed;
  // UI slider range; API still accepts 0.25–4
  return Math.min(1.8, Math.max(0.8, Math.round(n * 20) / 20));
}

export function loadTtsPrefs(): TtsPrefs {
  if (typeof window === "undefined") return { ...DEFAULT_TTS_PREFS };
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return { ...DEFAULT_TTS_PREFS };
    const parsed = JSON.parse(raw) as Partial<TtsPrefs>;
    return {
      voice:
        typeof parsed.voice === "string" && parsed.voice.trim()
          ? parsed.voice.trim()
          : DEFAULT_TTS_PREFS.voice,
      speed: clampSpeed(
        typeof parsed.speed === "number" ? parsed.speed : DEFAULT_TTS_PREFS.speed,
      ),
      language:
        typeof parsed.language === "string" && parsed.language.trim()
          ? parsed.language.trim()
          : DEFAULT_TTS_PREFS.language,
    };
  } catch {
    return { ...DEFAULT_TTS_PREFS };
  }
}

export function saveTtsPrefs(prefs: Partial<TtsPrefs>): TtsPrefs {
  const next: TtsPrefs = {
    ...loadTtsPrefs(),
    ...prefs,
  };
  next.voice = next.voice.trim() || DEFAULT_TTS_PREFS.voice;
  next.language = next.language.trim() || DEFAULT_TTS_PREFS.language;
  next.speed = clampSpeed(next.speed);
  localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
  window.dispatchEvent(new Event(TTS_PREFS_CHANGED_EVENT));
  return next;
}
