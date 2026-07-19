import { backendHttpBase } from "@/lib/config";
import { formatNetworkError } from "@/lib/network-error";
import { chunkForTts } from "@/lib/sentence-agg";

let currentAudio: HTMLAudioElement | null = null;
let currentUrl: string | null = null;
let activeQueue: TtsPlayQueue | null = null;

export type TtsSpeakOpts = {
  voice?: string;
  speed?: number;
  language?: string;
};

export type TtsStatus = {
  backend: string;
  configured: boolean;
  embedded?: boolean;
  natural_speech?: boolean;
  model: string;
  voice: string;
  language?: string;
  speed?: number;
  hint: string;
  url?: string | null;
  speech_url?: string | null;
  sample_rate?: number;
};

export type TtsVoiceInfo = {
  id: string;
  name: string;
  language: string;
};

export type TtsVoicesResponse = {
  voices: TtsVoiceInfo[];
  languages: string[];
  source: string;
  defaults: { voice: string; language: string; speed: number };
};

export async function fetchTtsStatus(): Promise<TtsStatus> {
  const res = await fetch(`${backendHttpBase()}/api/tts/status`);
  if (!res.ok) throw new Error(`TTS status HTTP ${res.status}`);
  return (await res.json()) as TtsStatus;
}

export async function fetchTtsVoices(): Promise<TtsVoicesResponse> {
  const res = await fetch(`${backendHttpBase()}/api/tts/voices`);
  if (!res.ok) throw new Error(`TTS voices HTTP ${res.status}`);
  return (await res.json()) as TtsVoicesResponse;
}

/** Stop any in-flight local TTS playback (current Audio element only). */
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

/** Stop playback queue and current audio. */
export function stopAllLocalTts(): void {
  if (activeQueue) {
    activeQueue.stop();
    return;
  }
  stopQwenTts();
}

async function fetchSpeakBlob(
  text: string,
  opts: TtsSpeakOpts = {},
): Promise<Blob> {
  const trimmed = text.trim();
  if (!trimmed) throw new Error("empty TTS text");

  const body: Record<string, string | number> = { text: trimmed };
  if (opts.voice) body.voice = opts.voice;
  if (opts.speed != null) body.speed = opts.speed;
  if (opts.language) body.language = opts.language;

  let res: Response;
  try {
    res = await fetch(`${backendHttpBase()}/api/tts/speak`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  } catch (err) {
    throw new Error(formatNetworkError(err, "/api/tts/speak"));
  }

  if (!res.ok) {
    let message = `TTS HTTP ${res.status}`;
    try {
      const errBody = (await res.json()) as {
        detail?: { message?: string; upstream?: string } | string;
      };
      if (typeof errBody.detail === "string") message = errBody.detail;
      else if (errBody.detail?.message) {
        message = errBody.detail.upstream
          ? `${errBody.detail.message} (upstream ${errBody.detail.upstream})`
          : errBody.detail.message;
      }
    } catch {
      /* keep default */
    }
    throw new Error(message);
  }

  return res.blob();
}

/**
 * Synthesize via FAE → local TTS and play a single clip.
 * Stops any queue / prior playback first (Settings preview).
 */
export async function speakWithLocalTts(
  text: string,
  opts: TtsSpeakOpts = {},
): Promise<void> {
  const trimmed = text.trim();
  if (!trimmed) return;

  stopAllLocalTts();

  const blob = await fetchSpeakBlob(trimmed, opts);
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

type QueuedClip = { id: number; url: string };

/**
 * Sentence-level WAV queue: prefetch 1–2 clips while the current one plays.
 */
export class TtsPlayQueue {
  private opts: TtsSpeakOpts;
  private readonly maxInflight: number;
  private pending: string[] = [];
  private ready = new Map<number, QueuedClip>();
  private nextId = 0;
  private playHead = 0;
  private synthHead = 0;
  private inflight = 0;
  private playing = false;
  private generation = 0;
  private onError: ((err: Error) => void) | null = null;
  private onIdle: (() => void) | null = null;

  constructor(opts: TtsSpeakOpts = {}, maxInflight = 2) {
    this.opts = opts;
    this.maxInflight = Math.max(1, Math.min(2, maxInflight));
    activeQueue = this;
  }

  setOpts(opts: TtsSpeakOpts): void {
    this.opts = opts;
  }

  setHandlers(handlers: {
    onError?: (err: Error) => void;
    onIdle?: () => void;
  }): void {
    this.onError = handlers.onError ?? null;
    this.onIdle = handlers.onIdle ?? null;
  }

  enqueue(text: string): void {
    const chunks = chunkForTts(text, 120);
    if (!chunks.length) return;
    if (activeQueue !== this) activeQueue = this;
    for (const chunk of chunks) this.pending.push(chunk);
    this.pumpSynth();
  }

  stop(): void {
    this.generation += 1;
    this.pending = [];
    for (const clip of this.ready.values()) {
      URL.revokeObjectURL(clip.url);
    }
    this.ready.clear();
    this.nextId = 0;
    this.playHead = 0;
    this.synthHead = 0;
    this.inflight = 0;
    this.playing = false;
    stopQwenTts();
    if (activeQueue === this) activeQueue = null;
  }

  get isBusy(): boolean {
    return (
      this.playing ||
      this.inflight > 0 ||
      this.pending.length > 0 ||
      this.ready.size > 0
    );
  }

  private pumpSynth(): void {
    const gen = this.generation;
    while (this.inflight < this.maxInflight && this.pending.length > 0) {
      const text = this.pending.shift()!;
      const id = this.nextId;
      this.nextId += 1;
      this.inflight += 1;
      void fetchSpeakBlob(text, this.opts)
        .then((blob) => {
          if (gen !== this.generation) return;
          const url = URL.createObjectURL(blob);
          this.ready.set(id, { id, url });
          this.pumpPlay();
        })
        .catch((err) => {
          if (gen !== this.generation) return;
          const e = err instanceof Error ? err : new Error(String(err));
          this.onError?.(e);
          // Skip failed slot so later sentences can still play
          this.ready.set(id, { id, url: "" });
          this.pumpPlay();
        })
        .finally(() => {
          if (gen !== this.generation) return;
          this.inflight -= 1;
          this.pumpSynth();
          this.maybeIdle();
        });
    }
  }

  private pumpPlay(): void {
    if (this.playing) return;
    const clip = this.ready.get(this.playHead);
    if (!clip) return;

    this.ready.delete(this.playHead);
    this.playHead += 1;

    if (!clip.url) {
      this.pumpPlay();
      this.maybeIdle();
      return;
    }

    this.playing = true;
    stopQwenTts();
    currentUrl = clip.url;
    const gen = this.generation;

    const finish = () => {
      if (gen !== this.generation) return;
      this.playing = false;
      if (currentUrl === clip.url) {
        URL.revokeObjectURL(clip.url);
        currentUrl = null;
        currentAudio = null;
      }
      this.pumpPlay();
      this.pumpSynth();
      this.maybeIdle();
    };

    const audio = new Audio(clip.url);
    currentAudio = audio;
    audio.onended = finish;
    audio.onerror = () => {
      this.onError?.(new Error("Audio playback failed"));
      finish();
    };
    void audio.play().catch((e) => {
      this.onError?.(e instanceof Error ? e : new Error(String(e)));
      finish();
    });
  }

  private maybeIdle(): void {
    if (!this.isBusy) this.onIdle?.();
  }
}
