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
import { TtsPlayQueue } from "@/lib/qwen-tts";
import { SpeechChunkAggregator } from "@/lib/sentence-agg";
import {
  BrowserSTT,
  speechSupported,
  stopSpeaking,
} from "@/lib/speech";
import { toSpeakableText } from "@/lib/speakable";
import {
  loadTtsPrefs,
  TTS_PREFS_CHANGED_EVENT,
} from "@/lib/tts-prefs";
import {
  loadPreferDaily,
  PREFER_DAILY_CHANGED_EVENT,
  savePreferDaily,
} from "@/lib/voice-prefs";
import { showBrowserNotification } from "@/lib/notifications-api";
import { ChatAbortedError, WsChatClient } from "@/lib/ws-chat";

export type OrbState = "idle" | "listening" | "thinking" | "speaking";
export type TransportMode = "browser" | "daily";
export type TtsMode = "local-tts" | "none";

export type ChatLine = {
  id: string;
  role: "user" | "assistant" | "system";
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
  const speakableLenRef = useRef(0);
  const speechAggRef = useRef(new SpeechChunkAggregator());
  const ttsQueueRef = useRef<TtsPlayQueue | null>(null);
  const connectingDaily = useRef(false);
  const memorySessionRef = useRef(sessionId);
  const voiceSessionRef = useRef<string | null>(null);

  const ensureTtsQueue = useCallback(() => {
    const prefs = loadTtsPrefs();
    const opts = {
      voice: prefs.voice,
      speed: prefs.speed,
      language: prefs.language,
    };
    if (!ttsQueueRef.current) {
      ttsQueueRef.current = new TtsPlayQueue(opts);
    } else {
      ttsQueueRef.current.setOpts(opts);
    }
    return ttsQueueRef.current;
  }, []);

  useEffect(() => {
    memorySessionRef.current = sessionId;
  }, [sessionId]);

  useEffect(() => {
    voiceSessionRef.current = voiceSessionId;
  }, [voiceSessionId]);

  useEffect(() => {
    const client = wsRef.current;
    client.setNotificationHandler((title, body, quiet) => {
      setLines((prev) => [
        ...prev,
        {
          id: `${Date.now()}-n`,
          role: "system",
          content: `🔔 ${title}：${body}`,
        },
      ]);
      if (!quiet) {
        showBrowserNotification(title, body);
      }
    });
    void client.connect().catch(() => {
      /* chat will retry */
    });
    return () => client.setNotificationHandler(null);
  }, []);

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
    const onTtsPrefsChanged = () => {
      const prefs = loadTtsPrefs();
      ttsQueueRef.current?.setOpts({
        voice: prefs.voice,
        speed: prefs.speed,
        language: prefs.language,
      });
    };
    window.addEventListener(CONFIG_CHANGED_EVENT, onConfigChanged);
    window.addEventListener(PREFER_DAILY_CHANGED_EVENT, onPreferDailyChanged);
    window.addEventListener(TTS_PREFS_CHANGED_EVENT, onTtsPrefsChanged);

    const stt = sttRef.current;
    const ws = wsRef.current;
    return () => {
      window.removeEventListener(CONFIG_CHANGED_EVENT, onConfigChanged);
      window.removeEventListener(
        PREFER_DAILY_CHANGED_EVENT,
        onPreferDailyChanged,
      );
      window.removeEventListener(TTS_PREFS_CHANGED_EVENT, onTtsPrefsChanged);
      stt.stop();
      speechAggRef.current.reset();
      stopSpeaking();
      ttsQueueRef.current?.stop();
      ttsQueueRef.current = null;
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
      speakableLenRef.current = 0;
      speechAggRef.current.reset();
      stopSpeaking();
      const queue = ensureTtsQueue();
      queue.setHandlers({
        onError: (ttsErr) => {
          setTtsMode("none");
          const msg = ttsErr.message;
          setError(
            msg.includes("Cannot reach") || msg.includes("upstream")
              ? `${msg} — 请确认 :8880 TTS 服务已启动（doc/LOCAL_TTS.md）`
              : msg,
          );
        },
        onIdle: () => setOrb("idle"),
      });

      const enqueueChunks = (parts: string[]) => {
        for (const part of parts) {
          const plain = toSpeakableText(part);
          if (!plain) continue;
          setOrb("speaking");
          setTtsMode("local-tts");
          queue.enqueue(plain);
        }
      };

      // Idle soft-flush when LLM pauses mid-stream (400ms).
      speechAggRef.current.setOnSoftFlush(enqueueChunks);

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
              // Store raw stream (incl. <think>) so the transcript can show
              // "思考中…" instead of a blank ellipsis during long reasoning.
              const raw = assistantBuf.current;
              setLines((prev) =>
                prev.map((l) =>
                  l.id === assistantId ? { ...l, content: raw } : l,
                ),
              );

              try {
                const speakable = toSpeakableText(raw);
                if (speakable.length < speakableLenRef.current) {
                  speakableLenRef.current = speakable.length;
                  return;
                }
                const delta = speakable.slice(speakableLenRef.current);
                speakableLenRef.current = speakable.length;
                if (delta) enqueueChunks(speechAggRef.current.push(delta));
              } catch {
                /* TTS path must never break token display */
              }
            },
            onDone: () => {
              speechAggRef.current.clearTimer();
              const leftover = speechAggRef.current.flush();
              if (leftover) enqueueChunks([leftover]);
            },
            onError: (code, message) => {
              setError(`${code}: ${message}`);
            },
          },
          memorySessionRef.current,
        );

        // Stream done — wait for queue drain via onIdle, or idle immediately.
        if (!queue.isBusy) setOrb("idle");
      } catch (e) {
        if (e instanceof ChatAbortedError) {
          speechAggRef.current.reset();
          queue.stop();
          setOrb("idle");
          return;
        }
        setError(formatNetworkError(e, "chat / voice"));
        setOrb("idle");
      }
    },
    [config, ensureTtsQueue],
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
    speechAggRef.current.reset();
    ttsQueueRef.current?.stop();
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
