/** Browser Web Speech STT + fallback TTS helpers. */

import { stopQwenTts } from "@/lib/qwen-tts";

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
    tts: typeof window !== "undefined" && "speechSynthesis" in window,
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

export function speak(text: string, lang = "zh-CN"): Promise<void> {
  return new Promise((resolve, reject) => {
    if (!("speechSynthesis" in window)) {
      reject(new Error("speechSynthesis not supported"));
      return;
    }
    window.speechSynthesis.cancel();
    const utter = new SpeechSynthesisUtterance(text);
    utter.lang = lang;
    utter.onend = () => resolve();
    utter.onerror = () => resolve();
    window.speechSynthesis.speak(utter);
  });
}

export function stopSpeaking(): void {
  stopQwenTts();
  if (typeof window !== "undefined" && "speechSynthesis" in window) {
    window.speechSynthesis.cancel();
  }
}
