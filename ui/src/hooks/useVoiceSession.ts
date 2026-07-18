"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import {
  type AgentConfig,
  loadConfig,
  saveConfig,
} from "@/lib/config";
import { createVoiceSession } from "@/lib/pipecat-client";
import {
  BrowserSTT,
  speak,
  speechSupported,
  stopSpeaking,
} from "@/lib/speech";
import { WsChatClient } from "@/lib/ws-chat";

export type OrbState = "idle" | "listening" | "thinking" | "speaking";

export type ChatLine = {
  id: string;
  role: "user" | "assistant";
  content: string;
};

export function useVoiceSession() {
  const [config, setConfigState] = useState<AgentConfig>(DEFAULT_SAFE);
  const [orb, setOrb] = useState<OrbState>("idle");
  const [lines, setLines] = useState<ChatLine[]>([]);
  const [partial, setPartial] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [support, setSupport] = useState({ stt: false, tts: false });

  const wsRef = useRef(new WsChatClient());
  const sttRef = useRef(new BrowserSTT());
  const assistantBuf = useRef("");

  useEffect(() => {
    setConfigState(loadConfig());
    setSupport(speechSupported());
    createVoiceSession()
      .then((s) => setSessionId(s.sessionId))
      .catch(() => {
        /* backend optional at first paint */
      });
    const stt = sttRef.current;
    const ws = wsRef.current;
    return () => {
      stt.stop();
      stopSpeaking();
      ws.close();
    };
  }, []);

  const setConfig = useCallback((next: AgentConfig) => {
    setConfigState(next);
    saveConfig(next);
  }, []);

  const appendLine = useCallback((role: ChatLine["role"], content: string) => {
    setLines((prev) => [
      ...prev,
      { id: `${Date.now()}-${Math.random()}`, role, content },
    ]);
  }, []);

  const runAssistant = useCallback(
    async (userText: string) => {
      if (!config.apiKey.trim()) {
        setError("请先在下方填入 Agent API Key");
        return;
      }
      setError(null);
      setOrb("thinking");
      assistantBuf.current = "";
      const assistantId = `${Date.now()}-a`;
      setLines((prev) => [
        ...prev,
        { id: assistantId, role: "assistant", content: "" },
      ]);

      try {
        await wsRef.current.chat(userText, config, {
          onToken: (token) => {
            assistantBuf.current += token;
            const snapshot = assistantBuf.current;
            setLines((prev) =>
              prev.map((l) =>
                l.id === assistantId ? { ...l, content: snapshot } : l,
              ),
            );
          },
          onDone: () => {},
          onError: (code, message) => {
            setError(`${code}: ${message}`);
          },
        });

        const reply = assistantBuf.current.trim();
        if (reply && support.tts) {
          setOrb("speaking");
          await speak(reply);
        }
        setOrb("idle");
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
        setOrb("idle");
      }
    },
    [config, support.tts],
  );

  const sendText = useCallback(
    async (text: string) => {
      const trimmed = text.trim();
      if (!trimmed) return;
      appendLine("user", trimmed);
      await runAssistant(trimmed);
    },
    [appendLine, runAssistant],
  );

  const startListening = useCallback(() => {
    if (!support.stt) {
      setError("当前浏览器不支持语音识别，请用 Chrome，或改用文字输入");
      return;
    }
    setError(null);
    setPartial("");
    setOrb("listening");
    // Barge-in: stop any in-flight speech + generation.
    stopSpeaking();
    wsRef.current.cancel();

    sttRef.current.start(
      (r) => {
        setPartial(r.transcript);
        if (r.isFinal && r.transcript.trim()) {
          setPartial("");
          setOrb("idle");
          void sendText(r.transcript.trim());
        }
      },
      (err) => {
        setError(`STT: ${err}`);
        setOrb("idle");
      },
    );
  }, [sendText, support.stt]);

  const stopListening = useCallback(() => {
    sttRef.current.stop();
    if (orb === "listening") setOrb("idle");
  }, [orb]);

  const interrupt = useCallback(() => {
    stopSpeaking();
    wsRef.current.cancel();
    sttRef.current.stop();
    setOrb("idle");
  }, []);

  return {
    config,
    setConfig,
    orb,
    lines,
    partial,
    error,
    sessionId,
    support,
    sendText,
    startListening,
    stopListening,
    interrupt,
  };
}

const DEFAULT_SAFE: AgentConfig = {
  baseUrl: "https://dashscope.aliyuncs.com/compatible-mode/v1",
  apiKey: "",
  model: "qwen3-max",
};
