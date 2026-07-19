/** Browser Web Speech STT helpers (recognition only — no speechSynthesis TTS). */

import { stopAllLocalTts } from "@/lib/qwen-tts";
import { loadTtsPrefs } from "@/lib/tts-prefs";

export type SttResult = {
  transcript: string;
  isFinal: boolean;
};

export type SttStartOptions = {
  /** BCP-47 language tag; defaults from TTS prefs language. */
  lang?: string;
};

type RecognitionCtor = new () => SpeechRecognition;

function getRecognitionCtor(): RecognitionCtor | null {
  if (typeof window === "undefined") return null;
  const w = window as Window &
    typeof globalThis & {
      webkitSpeechRecognition?: RecognitionCtor;
      SpeechRecognition?: RecognitionCtor;
    };
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null;
}

export function speechSupported(): { stt: boolean; tts: boolean } {
  return {
    stt: Boolean(getRecognitionCtor()),
    // Local TTS is server-side; browser speechSynthesis is not used.
    tts: true,
  };
}

/** Map Settings TTS language label → Web Speech BCP-47 tag. */
export function ttsLanguageToSttLang(language: string): string {
  const key = (language || "").trim().toLowerCase();
  if (key.startsWith("en") || key === "english") return "en-US";
  if (key.startsWith("ja") || key === "japanese") return "ja-JP";
  if (key.startsWith("ko") || key === "korean") return "ko-KR";
  return "zh-CN";
}

const STT_ERROR_ZH: Record<string, string> = {
  "not-allowed": "麦克风权限被拒绝，请在浏览器设置中允许后重试",
  "no-speech": "没有听到声音，请靠近麦克风再说一次",
  "audio-capture": "找不到麦克风，请检查设备连接",
  network: "语音识别网络错误，请检查网络后重试",
  aborted: "语音识别已取消",
  "service-not-allowed": "浏览器不允许语音识别服务",
  "bad-grammar": "语音识别配置错误",
  "language-not-supported": "当前浏览器不支持所选识别语言",
};

export function formatSttError(code: string): string {
  const key = (code || "").trim();
  return STT_ERROR_ZH[key] || `语音识别失败：${key || "unknown"}`;
}

export class BrowserSTT {
  private recognition: SpeechRecognition | null = null;
  /** Incremented on stop() so onend restart cannot resurrect a stopped session. */
  private generation = 0;
  private wantRunning = false;

  start(
    onResult: (r: SttResult) => void,
    onError?: (err: string) => void,
    options?: SttStartOptions,
  ): void {
    const Ctor = getRecognitionCtor();
    if (!Ctor) {
      onError?.("当前浏览器不支持语音识别，请用 Chrome");
      return;
    }

    this.stop();
    const gen = this.generation;
    this.wantRunning = true;

    const lang =
      options?.lang ||
      ttsLanguageToSttLang(loadTtsPrefs().language);

    const recognition = new Ctor();
    this.recognition = recognition;
    recognition.lang = lang;
    recognition.interimResults = true;
    recognition.continuous = true;

    recognition.onresult = (event: SpeechRecognitionEvent) => {
      let transcript = "";
      let isFinal = false;
      for (let i = event.resultIndex; i < event.results.length; i += 1) {
        transcript += event.results[i][0].transcript;
        if (event.results[i].isFinal) isFinal = true;
      }
      onResult({ transcript, isFinal });
    };

    recognition.onerror = (event: SpeechRecognitionErrorEvent) => {
      // `aborted` is expected when we stop() mid-session.
      if (event.error === "aborted") return;
      // Continuous mode fires `no-speech` often — ignore, session keeps running.
      if (event.error === "no-speech") return;
      this.wantRunning = false;
      onError?.(formatSttError(event.error));
    };

    const recAny = recognition as SpeechRecognition & {
      onend: ((this: SpeechRecognition, ev: Event) => void) | null;
    };
    recAny.onend = () => {
      if (gen !== this.generation || !this.wantRunning) return;
      // Browser ends continuous sessions periodically — restart while user wants mic on.
      try {
        recognition.start();
      } catch {
        /* InvalidStateError if already started */
      }
    };

    try {
      recognition.start();
    } catch (e) {
      this.wantRunning = false;
      onError?.(
        e instanceof Error ? e.message : formatSttError(String(e)),
      );
    }
  }

  /** Pause recognition without clearing wantRunning (e.g. while assistant speaks). */
  pause(): void {
    const rec = this.recognition;
    if (!rec) return;
    // Keep wantRunning; bump generation so onend won't restart this instance.
    this.generation += 1;
    try {
      (rec as SpeechRecognition & { onend: null }).onend = null;
      rec.stop();
    } catch {
      /* ignore */
    }
    this.recognition = null;
  }

  stop(): void {
    this.wantRunning = false;
    this.generation += 1;
    const rec = this.recognition;
    this.recognition = null;
    if (!rec) return;
    try {
      (rec as SpeechRecognition & { onend: null }).onend = null;
      rec.stop();
    } catch {
      /* ignore */
    }
  }

  get isWantRunning(): boolean {
    return this.wantRunning;
  }
}

/** Stop local TTS playback queue + audio (no browser speechSynthesis). */
export function stopSpeaking(): void {
  stopAllLocalTts();
}
