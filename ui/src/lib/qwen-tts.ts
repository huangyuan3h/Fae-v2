import { backendHttpBase } from "@/lib/config";
import { formatNetworkError } from "@/lib/network-error";
import { speak } from "@/lib/speech";

let currentAudio: HTMLAudioElement | null = null;
let currentUrl: string | null = null;

export type TtsStatus = {
  backend: string;
  configured: boolean;
  /** True when backend serves the tone stub (not real speech). */
  embedded?: boolean;
  natural_speech?: boolean;
  model: string;
  voice: string;
  hint: string;
  url?: string | null;
  sample_rate?: number;
};

export type SpeakAssistantResult = {
  mode: "local-tts" | "browser";
  /** Set when browser speech was used because local TTS was stub/unavailable. */
  fallbackReason?: string;
};

export async function fetchTtsStatus(): Promise<TtsStatus> {
  const res = await fetch(`${backendHttpBase()}/api/tts/status`);
  if (!res.ok) throw new Error(`TTS status HTTP ${res.status}`);
  return (await res.json()) as TtsStatus;
}

/**
 * Play assistant text via local TTS when a real server is up.
 * Embedded stub → browser speech (words, not beeps).
 * Unreachable local TTS → browser speech + fallbackReason.
 */
export async function speakAssistant(text: string): Promise<SpeakAssistantResult> {
  const trimmed = text.trim();
  if (!trimmed) return { mode: "browser" };

  let status: TtsStatus | null = null;
  try {
    status = await fetchTtsStatus();
  } catch {
    /* try local speak below */
  }

  // Only the embedded tone stub should skip /api/tts/speak on purpose.
  if (status?.embedded) {
    await speak(trimmed);
    return {
      mode: "browser",
      fallbackReason: "embedded_stub",
    };
  }

  try {
    await speakWithQwenTts(trimmed);
    return { mode: "local-tts" };
  } catch (err) {
    const reason = err instanceof Error ? err.message : String(err);
    await speak(trimmed);
    return { mode: "browser", fallbackReason: reason };
  }
}

/** Stop any in-flight Qwen3-TTS playback. */
export function stopQwenTts(): void {
  if (currentAudio) {
    currentAudio.pause();
    currentAudio.src = "";
    currentAudio = null;
  }
  if (currentUrl) {
    URL.revokeObjectURL(currentUrl);
    currentUrl = null;
  }
}

/**
 * Synthesize via backend local TTS and play the returned WAV.
 * Rejects if the server is not configured or synthesis fails.
 */
export async function speakWithQwenTts(text: string): Promise<void> {
  const trimmed = text.trim();
  if (!trimmed) return;

  stopQwenTts();

  let res: Response;
  try {
    res = await fetch(`${backendHttpBase()}/api/tts/speak`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: trimmed }),
    });
  } catch (err) {
    throw new Error(formatNetworkError(err, "/api/tts/speak"));
  }

  if (!res.ok) {
    let message = `TTS HTTP ${res.status}`;
    try {
      const body = (await res.json()) as {
        detail?: { message?: string } | string;
      };
      if (typeof body.detail === "string") message = body.detail;
      else if (body.detail?.message) message = body.detail.message;
    } catch {
      /* keep default */
    }
    throw new Error(message);
  }

  // Embedded stub returns a beep — not speech. Let callers fall back.
  if (res.headers.get("x-fae-tts-backend") === "local-embedded") {
    throw new Error("tts_stub_tone");
  }

  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  currentUrl = url;

  await new Promise<void>((resolve, reject) => {
    const audio = new Audio(url);
    currentAudio = audio;
    audio.onended = () => {
      stopQwenTts();
      resolve();
    };
    audio.onerror = () => {
      stopQwenTts();
      reject(new Error("Audio playback failed"));
    };
    void audio.play().catch((e) => {
      stopQwenTts();
      reject(e instanceof Error ? e : new Error(String(e)));
    });
  });
}
