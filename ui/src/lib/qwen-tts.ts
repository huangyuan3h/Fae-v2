import { backendHttpBase } from "@/lib/config";
import { formatNetworkError } from "@/lib/network-error";
import { chunkForTts, TTS_CHUNK_CHARS } from "@/lib/sentence-agg";

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

/** Pause/clear the current Audio element without touching the play queue. */
export function stopQwenTts(): void {
  if (currentAudio) {
    currentAudio.onended = null;
    currentAudio.onerror = null;
    currentAudio.ontimeupdate = null;
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

type QueuedClip = { id: number; url: string; audio?: HTMLAudioElement };

/**
 * Phrase-level WAV queue.
 * Core: Mac TTS synth is often slower than playback — buffer before start
 * and keep up to 4 in-flight short clips so play rarely underruns.
 */
export class TtsPlayQueue {
  private opts: TtsSpeakOpts;
  private readonly maxInflight: number;
  private readonly targetReady: number;
  /** Wait for this many ready clips before first audible play. */
  private readonly minStartReady: number;
  private pending: string[] = [];
  private ready = new Map<number, QueuedClip>();
  private nextId = 0;
  private playHead = 0;
  private inflight = 0;
  private playing = false;
  private started = false;
  private generation = 0;
  private onError: ((err: Error) => void) | null = null;
  private onIdle: (() => void) | null = null;
  private primed: HTMLAudioElement | null = null;

  constructor(
    opts: TtsSpeakOpts = {},
    // MLX server serializes gens (TTS_MAX_CONCURRENT=1); 2 in-flight HTTP is enough.
    maxInflight = 2,
    targetReady = 2,
    minStartReady = 2,
  ) {
    this.opts = opts;
    this.maxInflight = Math.max(1, Math.min(4, maxInflight));
    this.targetReady = Math.max(1, targetReady);
    this.minStartReady = Math.max(1, minStartReady);
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
    const chunks = chunkForTts(text, TTS_CHUNK_CHARS);
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
    this.inflight = 0;
    this.playing = false;
    this.started = false;
    this.primed = null;
    // Clear audio without going through stopAllLocalTts (would re-enter stop).
    if (currentAudio) {
      currentAudio.onended = null;
      currentAudio.onerror = null;
      currentAudio.ontimeupdate = null;
      currentAudio.pause();
      currentAudio.src = "";
      currentAudio = null;
    }
    if (currentUrl) {
      URL.revokeObjectURL(currentUrl);
      currentUrl = null;
    }
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

  /** How many ready clips sit ahead of the play head (including gaps as 0). */
  private readyAhead(): number {
    let n = 0;
    let id = this.playHead;
    while (this.ready.has(id)) {
      n += 1;
      id += 1;
    }
    return n;
  }

  private pumpSynth(): void {
    const gen = this.generation;
    // Never wait on playback — fill up to maxInflight whenever text is pending.
    while (this.inflight < this.maxInflight && this.pending.length > 0) {
      const text = this.pending.shift()!;
      const id = this.nextId;
      this.nextId += 1;
      this.inflight += 1;
      void fetchSpeakBlob(text, this.opts)
        .then((blob) => {
          if (gen !== this.generation) return;
          const url = URL.createObjectURL(blob);
          const audio = new Audio();
          audio.preload = "auto";
          audio.src = url;
          this.ready.set(id, { id, url, audio });
          this.pumpPlay();
          if (this.readyAhead() < this.targetReady) this.pumpSynth();
        })
        .catch((err) => {
          if (gen !== this.generation) return;
          const e = err instanceof Error ? err : new Error(String(err));
          this.onError?.(e);
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

  private pauseCurrentAudioOnly(): void {
    if (currentAudio) {
      currentAudio.onended = null;
      currentAudio.onerror = null;
      currentAudio.ontimeupdate = null;
      currentAudio.pause();
      currentAudio = null;
    }
    // Revoke previous url only — never the clip we are about to play.
    if (currentUrl) {
      URL.revokeObjectURL(currentUrl);
      currentUrl = null;
    }
  }

  private pumpPlay(): void {
    if (this.playing) {
      this.primeNext();
      return;
    }
    const clip = this.ready.get(this.playHead);
    if (!clip) return;

    // Buffer before first play so synth can stay ahead of realtime audio.
    // If the pipeline is drained (short reply), play with whatever we have.
    if (!this.started) {
      const ahead = this.readyAhead();
      const drained = this.pending.length === 0 && this.inflight === 0;
      if (ahead < this.minStartReady && !drained) return;
    }

    this.ready.delete(this.playHead);
    this.playHead += 1;

    if (!clip.url) {
      this.pumpPlay();
      this.maybeIdle();
      return;
    }

    this.started = true;
    this.playing = true;
    this.pauseCurrentAudioOnly();
    currentUrl = clip.url;
    const gen = this.generation;
    const audio = clip.audio ?? new Audio(clip.url);
    currentAudio = audio;
    this.primed = null;

    const finish = () => {
      if (gen !== this.generation) return;
      this.playing = false;
      if (currentUrl === clip.url) {
        URL.revokeObjectURL(clip.url);
        currentUrl = null;
        currentAudio = null;
      }
      this.pumpSynth();
      this.pumpPlay();
      this.maybeIdle();
    };

    audio.onended = finish;
    audio.onerror = () => {
      this.onError?.(new Error("Audio playback failed"));
      finish();
    };
    audio.ontimeupdate = () => {
      if (gen !== this.generation) return;
      if (!Number.isFinite(audio.duration) || audio.duration <= 0) return;
      const remaining = audio.duration - audio.currentTime;
      if (remaining < 0.15) this.primeNext();
    };

    void audio.play().catch((e) => {
      this.onError?.(e instanceof Error ? e : new Error(String(e)));
      finish();
    });

    // Keep synth pipeline full while this clip plays.
    this.pumpSynth();
    this.primeNext();
  }

  /** Pre-decode the next ready clip to shrink gap between plays. */
  private primeNext(): void {
    const next = this.ready.get(this.playHead);
    if (!next?.url || !next.audio) return;
    if (this.primed === next.audio) return;
    this.primed = next.audio;
    try {
      next.audio.load();
    } catch {
      /* ignore */
    }
  }

  private maybeIdle(): void {
    if (!this.isBusy) this.onIdle?.();
  }
}
