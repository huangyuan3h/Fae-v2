import { backendHttpBase } from "@/lib/config";

let currentAudio: HTMLAudioElement | null = null;
let currentUrl: string | null = null;

export type TtsStatus = {
  backend: string;
  configured: boolean;
  model: string;
  voice: string;
  hint: string;
};

export async function fetchTtsStatus(): Promise<TtsStatus> {
  const res = await fetch(`${backendHttpBase()}/api/tts/status`);
  if (!res.ok) throw new Error(`TTS status HTTP ${res.status}`);
  return (await res.json()) as TtsStatus;
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
 * Synthesize via backend Qwen3-TTS and play the returned WAV.
 * Rejects if the server is not configured or synthesis fails.
 */
export async function speakWithQwenTts(text: string): Promise<void> {
  const trimmed = text.trim();
  if (!trimmed) return;

  stopQwenTts();

  const res = await fetch(`${backendHttpBase()}/api/tts/speak`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text: trimmed }),
  });

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
