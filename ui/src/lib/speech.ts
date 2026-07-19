/** Browser Web Speech STT helpers (recognition only — no speechSynthesis TTS). */

import { stopAllLocalTts } from "@/lib/qwen-tts";

export type SttResult = {
  transcript: string;
  isFinal: boolean;
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

export class BrowserSTT {
  private recognition: SpeechRecognition | null = null;

  start(onResult: (r: SttResult) => void, onError?: (err: string) => void): void {
    const Ctor = getRecognitionCtor();
    if (!Ctor) {
      onError?.("SpeechRecognition not supported in this browser");
      return;
    }
    const recognition = new Ctor();
    this.recognition = recognition;
    recognition.lang = "zh-CN";
    recognition.interimResults = true;
    recognition.continuous = false;

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
      onError?.(event.error);
    };
    recognition.start();
  }

  stop(): void {
    this.recognition?.stop();
    this.recognition = null;
  }
}

/** Stop local TTS playback queue + audio (no browser speechSynthesis). */
export function stopSpeaking(): void {
  stopAllLocalTts();
}
