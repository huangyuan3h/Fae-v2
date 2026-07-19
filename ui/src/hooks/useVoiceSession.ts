"use client";

import type { DailyCall } from "@daily-co/daily-js";
import { useCallback, useEffect, useRef, useState } from "react";

import {
  type AgentConfig,
  DEFAULT_CONFIG,
  loadConfig,
  saveConfig,
  backendHttpBase,
} from "@/lib/config";
import { joinDailyRoom, leaveDailyRoom } from "@/lib/daily-session";
import {
  CONFIG_CHANGED_EVENT,
  syncActiveConfig,
} from "@/lib/models";
import { formatNetworkError } from "@/lib/network-error";
import { createVoiceSession } from "@/lib/pipecat-client";
import { speakAssistant } from "@/lib/qwen-tts";
import {
  BrowserSTT,
  speechSupported,
  stopSpeaking,
} from "@/lib/speech";
import { toSpeakableText } from "@/lib/speakable";
import { stripThinking } from "@/lib/strip-thinking";
import {
  loadPreferDaily,
  PREFER_DAILY_CHANGED_EVENT,
  savePreferDaily,
} from "@/lib/voice-prefs";
import { ChatAbortedError, WsChatClient } from "@/lib/ws-chat";

export type OrbState = "idle" | "listening" | "thinking" | "speaking";
export type TransportMode = "browser" | "daily";
export type TtsMode = "local-tts" | "qwen3-tts" | "browser" | "none";

export type ChatLine = {
  id: string;
  role: "user" | "assistant";
  content: string;
};

function makeClientSessionId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return `local-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

export function useVoiceSession() {
  const [config, setConfigState] = useState<AgentConfig>(DEFAULT_CONFIG);
  const [orb, setOrb] = useState<OrbState>("idle");
  const [lines, setLines] = useState<ChatLine[]>([]);
  const [partial, setPartial] = useState("");
  const [error, setError] = useState<string | null>(null);
  // Stable client id for memory recall buckets (available before /api/voice/session).
  const [sessionId] = useState(makeClientSessionId);
  const [voiceSessionId, setVoiceSessionId] = useState<string | null>(null);
  const [mode, setMode] = useState<TransportMode>("browser");
  const [ttsMode, setTtsMode] = useState<TtsMode>("none");
  const [activeSkills, setActiveSkills] = useState<string[]>([]);
  const [preferDaily, setPreferDailyState] = useState(false);
  const [dailyConnected, setDailyConnected] = useState(false);
  const [support, setSupport] = useState({ stt: false, tts: false });

  const setPreferDaily = useCallback((v: boolean) => {
    setPreferDailyState(v);
    savePreferDaily(v);
  }, []);

  const wsRef = useRef(new WsChatClient());
  const sttRef = useRef(new BrowserSTT());
  const dailyRef = useRef<DailyCall | null>(null);
  const assistantBuf = useRef("");
  const connectingDaily = useRef(false);
  const memorySessionRef = useRef(sessionId);
  const voiceSessionRef = useRef<string | null>(null);

  useEffect(() => {
    memorySessionRef.current = sessionId;
  }, [sessionId]);

  useEffect(() => {
    voiceSessionRef.current = voiceSessionId;
  }, [voiceSessionId]);

  useEffect(() => {
    setConfigState(syncActiveConfig());
    setPreferDailyState(loadPreferDaily());
    setSupport(speechSupported());
    createVoiceSession({ preferDaily: false })
      .then((s) => {
        setVoiceSessionId(s.sessionId);
        setMode(s.mode);
      })
      .catch((err) => {
        // Surface connection issues early; chat/TTS will fail the same way.
        setError(formatNetworkError(err, "backend :8000"));
      });

    // Stale Daily preference (no server key) → clear so mic won't show Daily errors.
    void fetch(`${backendHttpBase()}/api/voice/status`)
      .then((r) => (r.ok ? r.json() : null))
      .then((st: { daily_configured?: boolean } | null) => {
        if (st && !st.daily_configured && loadPreferDaily()) {
          savePreferDaily(false);
          setPreferDailyState(false);
        }
      })
      .catch(() => {
        /* ignore */
      });

    const onConfigChanged = () => setConfigState(loadConfig());
    const onPreferDailyChanged = () => setPreferDailyState(loadPreferDaily());
    window.addEventListener(CONFIG_CHANGED_EVENT, onConfigChanged);
    window.addEventListener(PREFER_DAILY_CHANGED_EVENT, onPreferDailyChanged);

    const stt = sttRef.current;
    const ws = wsRef.current;
    return () => {
      window.removeEventListener(CONFIG_CHANGED_EVENT, onConfigChanged);
      window.removeEventListener(
        PREFER_DAILY_CHANGED_EVENT,
        onPreferDailyChanged,
      );
      stt.stop();
      stopSpeaking();
      ws.close();
      void leaveDailyRoom(dailyRef.current);
      dailyRef.current = null;
    };
  }, []);

  const setConfig = useCallback((next: AgentConfig) => {
    setConfigState(next);
    saveConfig(next);
  }, []);

  const postBargeIn = useCallback(async (id: string | null) => {
    if (!id) return;
    try {
      await fetch(`${backendHttpBase()}/api/voice/barge-in`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: id }),
      });
    } catch {
      /* local stopSpeaking / WS cancel still applied */
    }
  }, []);

  const connectDaily = useCallback(async (): Promise<boolean> => {
    if (connectingDaily.current || dailyConnected) return dailyConnected;
    if (!config.apiKey.trim()) {
      setError("Daily 模式仍需要在 Settings → 模型 中配置 API Key");
      return false;
    }
    connectingDaily.current = true;
    setError(null);
    setOrb("thinking");
    try {
      const session = await createVoiceSession({
        preferDaily: true,
        config,
      });
      setVoiceSessionId(session.sessionId);
      setMode(session.mode);
      if (session.mode !== "daily" || !session.roomUrl || !session.token) {
        // No Daily key / room — stay on browser STT + Qwen3-TTS. Do not alarm.
        setPreferDaily(false);
        setMode("browser");
        setOrb("idle");
        return false;
      }
      const call = await joinDailyRoom(session.roomUrl, session.token);
      dailyRef.current = call;
      setDailyConnected(true);
      setOrb("listening");
      call.on("left-meeting", () => {
        setDailyConnected(false);
        setOrb("idle");
      });
      return true;
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setOrb("idle");
      return false;
    } finally {
      connectingDaily.current = false;
    }
  }, [config, dailyConnected, setPreferDaily]);

  const disconnectDaily = useCallback(async () => {
    await leaveDailyRoom(dailyRef.current);
    dailyRef.current = null;
    setDailyConnected(false);
    setOrb("idle");
    setMode("browser");
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
        setError("请先在 Settings → 模型 中配置 API Key");
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
        setActiveSkills([]);
        await wsRef.current.chat(
          userText,
          config,
          {
            onSkills: (names) => setActiveSkills(names),
            onToken: (token) => {
              assistantBuf.current += token;
              const visible = stripThinking(assistantBuf.current);
              setLines((prev) =>
                prev.map((l) =>
                  l.id === assistantId ? { ...l, content: visible } : l,
                ),
              );
            },
            onDone: () => {},
            onError: (code, message) => {
              setError(`${code}: ${message}`);
            },
          },
          memorySessionRef.current,
        );

        const reply = toSpeakableText(assistantBuf.current);
        if (reply) {
          setOrb("speaking");
          try {
            const result = await speakAssistant(reply);
            setTtsMode(result.mode);
            if (
              result.mode === "browser" &&
              result.fallbackReason &&
              result.fallbackReason !== "embedded_stub"
            ) {
              setError(
                "本机 TTS 不可用，已用浏览器朗读。请启动真模型服务，或将 TTS_EMBED_STUB=true（开发 stub）。见 doc/LOCAL_TTS.md",
              );
            }
          } catch (ttsErr) {
            setError(formatNetworkError(ttsErr, "/api/tts/speak"));
          }
        }
        setOrb("idle");
      } catch (e) {
        if (e instanceof ChatAbortedError) {
          setOrb("idle");
          return;
        }
        setError(formatNetworkError(e, "chat / voice"));
        setOrb("idle");
      }
    },
    [config, support.tts],
  );

  const sendText = useCallback(
    async (text: string) => {
      const trimmed = text.trim();
      if (!trimmed) return;
      if (mode === "daily" && dailyConnected) {
        appendLine("user", trimmed);
        appendLine(
          "assistant",
          "（Daily 模式：请直接对着麦克风说话，Pipecat 管线会处理语音。）",
        );
        return;
      }
      appendLine("user", trimmed);
      await runAssistant(trimmed);
    },
    [appendLine, dailyConnected, mode, runAssistant],
  );

  const startBrowserListening = useCallback(() => {
    if (!support.stt) {
      setError("当前浏览器不支持语音识别，请用 Chrome，或改用文字输入");
      return;
    }
    setError(null);
    setPartial("");
    setOrb("listening");
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

  const startListening = useCallback(() => {
    if (preferDaily || mode === "daily") {
      void connectDaily().then((ok) => {
        if (!ok) startBrowserListening();
      });
      return;
    }
    startBrowserListening();
  }, [
    connectDaily,
    mode,
    preferDaily,
    startBrowserListening,
  ]);

  const stopListening = useCallback(() => {
    if (dailyConnected) {
      void disconnectDaily();
      return;
    }
    sttRef.current.stop();
    if (orb === "listening") setOrb("idle");
  }, [dailyConnected, disconnectDaily, orb]);

  const interrupt = useCallback(() => {
    stopSpeaking();
    wsRef.current.cancel();
    sttRef.current.stop();
    // Barge-in hits VoiceRuntime registry keyed by server voice session id.
    void postBargeIn(voiceSessionRef.current ?? memorySessionRef.current);
    setOrb(dailyConnected ? "listening" : "idle");
  }, [dailyConnected, postBargeIn]);

  return {
    config,
    setConfig,
    orb,
    lines,
    partial,
    error,
    sessionId,
    voiceSessionId,
    mode,
    ttsMode,
    activeSkills,
    preferDaily,
    setPreferDaily,
    dailyConnected,
    support,
    sendText,
    startListening,
    stopListening,
    interrupt,
  };
}
