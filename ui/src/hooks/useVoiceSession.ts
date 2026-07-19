"use client";

import type { DailyCall } from "@daily-co/daily-js";
import { useCallback, useEffect, useRef, useState } from "react";

import { getMemorySessionId } from "@/lib/client-identity";
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
  ttsLanguageToSttLang,
} from "@/lib/speech";
import { toSpeakableText } from "@/lib/speakable";
import {
  loadTtsPrefs,
  TTS_PREFS_CHANGED_EVENT,
} from "@/lib/tts-prefs";

type TurnMetrics = {
  turnId: string;
  listenStartedAt: number | null;
  sttFinalAt: number | null;
  llmFirstTokenAt: number | null;
  ttsFirstByteAt: number | null;
  ttsFirstPlayAt: number | null;
  ttsServerMs: number | null;
};
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

export function useVoiceSession() {
  const [config, setConfigState] = useState<AgentConfig>(DEFAULT_CONFIG);
  const [orb, setOrb] = useState<OrbState>("idle");
  const [lines, setLines] = useState<ChatLine[]>([]);
  const [partial, setPartial] = useState("");
  const [error, setError] = useState<string | null>(null);
  // Stable memory bucket shared with proactive / consolidate (localStorage).
  const [sessionId] = useState(getMemorySessionId);
  const [voiceSessionId, setVoiceSessionId] = useState<string | null>(null);
  const [mode, setMode] = useState<TransportMode>("browser");
  // Browser path always uses local TTS when available; do not wait for first enqueue.
  const [ttsMode, setTtsMode] = useState<TtsMode>("local-tts");
  const [activeSkills, setActiveSkills] = useState<string[]>([]);
  const [skillScores, setSkillScores] = useState<Record<string, number>>({});
  const [lastVoiceDebug, setLastVoiceDebug] = useState<string | null>(null);
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
  /** User clicked 开始听写 — resume after assistant / interrupt. */
  const wantListeningRef = useRef(false);
  const metricsRef = useRef<TurnMetrics | null>(null);
  const modeRef = useRef<TransportMode>("browser");

  useEffect(() => {
    modeRef.current = mode;
  }, [mode]);

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
    client.setNotificationHandler((title, body, quiet, speak) => {
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
      if (speak && !quiet && body.trim()) {
        const clip = body.trim().slice(0, 120);
        void import("@/lib/qwen-tts").then(({ speakWithLocalTts }) =>
          speakWithLocalTts(clip).catch(() => {
            /* optional short TTS — ignore failures */
          }),
        );
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
    createVoiceSession({
      preferDaily: false,
      memorySessionId: memorySessionRef.current,
    })
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
    const speechAgg = speechAggRef.current;
    return () => {
      window.removeEventListener(CONFIG_CHANGED_EVENT, onConfigChanged);
      window.removeEventListener(
        PREFER_DAILY_CHANGED_EVENT,
        onPreferDailyChanged,
      );
      window.removeEventListener(TTS_PREFS_CHANGED_EVENT, onTtsPrefsChanged);
      stt.stop();
      speechAgg.reset();
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
        memorySessionId: memorySessionRef.current,
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

  const resumeListeningIfWanted = useCallback(() => {
    if (!wantListeningRef.current || modeRef.current === "daily") {
      setOrb("idle");
      return;
    }
    if (!support.stt) {
      setOrb("idle");
      return;
    }
    metricsRef.current = {
      turnId: `${Date.now()}`,
      listenStartedAt: performance.now(),
      sttFinalAt: null,
      llmFirstTokenAt: null,
      ttsFirstByteAt: null,
      ttsFirstPlayAt: null,
      ttsServerMs: null,
    };
    setOrb("listening");
    sttRef.current.start(
      (r) => {
        setPartial(r.transcript);
        if (r.isFinal && r.transcript.trim()) {
          setPartial("");
          if (metricsRef.current) {
            metricsRef.current.sttFinalAt = performance.now();
          }
          // Pause STT while assistant runs (avoid TTS feedback into mic).
          sttRef.current.pause();
          void sendTextRef.current(r.transcript.trim());
        }
      },
      (err) => {
        setError(err);
        wantListeningRef.current = false;
        setOrb("idle");
      },
      { lang: ttsLanguageToSttLang(loadTtsPrefs().language) },
    );
  }, [support.stt]);

  const sendTextRef = useRef<(text: string) => Promise<void>>(async () => {});

  const logTurnMetrics = useCallback((m: TurnMetrics) => {
    const sttMs =
      m.listenStartedAt != null && m.sttFinalAt != null
        ? Math.round(m.sttFinalAt - m.listenStartedAt)
        : null;
    const llmTtftMs =
      m.sttFinalAt != null && m.llmFirstTokenAt != null
        ? Math.round(m.llmFirstTokenAt - m.sttFinalAt)
        : null;
    const ttsFirstByteMs =
      m.sttFinalAt != null && m.ttsFirstByteAt != null
        ? Math.round(m.ttsFirstByteAt - m.sttFinalAt)
        : null;
    const ttsFirstPlayMs =
      m.sttFinalAt != null && m.ttsFirstPlayAt != null
        ? Math.round(m.ttsFirstPlayAt - m.sttFinalAt)
        : null;
    const e2eMs =
      m.sttFinalAt != null && m.ttsFirstPlayAt != null
        ? Math.round(m.ttsFirstPlayAt - m.sttFinalAt)
        : null;
    const summary = [
      sttMs != null ? `stt=${sttMs}ms` : null,
      llmTtftMs != null ? `llm_ttft=${llmTtftMs}ms` : null,
      ttsFirstPlayMs != null ? `tts_play=${ttsFirstPlayMs}ms` : null,
      e2eMs != null ? `e2e=${e2eMs}ms` : null,
    ]
      .filter(Boolean)
      .join(" · ");
    if (summary) setLastVoiceDebug(summary);
    console.debug("[fae.voice]", {
      turn_id: m.turnId,
      stt_ms: sttMs,
      llm_ttft_ms: llmTtftMs,
      tts_first_byte_ms: ttsFirstByteMs,
      tts_first_play_ms: ttsFirstPlayMs,
      tts_server_ms: m.ttsServerMs,
      e2e_ms: e2eMs,
    });
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

      const turnId = `${Date.now()}`;
      const metrics: TurnMetrics = {
        turnId,
        listenStartedAt: metricsRef.current?.listenStartedAt ?? null,
        sttFinalAt: metricsRef.current?.sttFinalAt ?? performance.now(),
        llmFirstTokenAt: null,
        ttsFirstByteAt: null,
        ttsFirstPlayAt: null,
        ttsServerMs: null,
      };
      metricsRef.current = metrics;

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
        onIdle: () => {
          // Browser path: stopSpeaking+WS cancel is the full interrupt story.
          // Resume continuous listen when the user still wants the mic on.
          resumeListeningIfWanted();
        },
        onFirstByte: (info) => {
          metrics.ttsFirstByteAt = performance.now();
          metrics.ttsServerMs = info.ttsMs;
        },
        onFirstPlay: () => {
          metrics.ttsFirstPlayAt = performance.now();
          logTurnMetrics(metrics);
        },
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

      // Idle soft-flush when LLM pauses mid-stream.
      speechAggRef.current.setOnSoftFlush(enqueueChunks);

      const assistantId = `${Date.now()}-a`;
      setLines((prev) => [
        ...prev,
        { id: assistantId, role: "assistant", content: "" },
      ]);

      try {
        setActiveSkills([]);
        setSkillScores({});
        await wsRef.current.chat(
          userText,
          config,
          {
            onSkills: (names, scores) => {
              setActiveSkills(names);
              setSkillScores(scores ?? {});
            },
            onSubagent: (ev) => {
              if (ev.phase === "start") {
                appendLine(
                  "system",
                  `子任务 ${ev.name || "subagent"} 进行中…`,
                );
                return;
              }
              const ok = ev.ok !== false;
              const clip = (ev.summary || "").trim().slice(0, 160);
              appendLine(
                "system",
                ok
                  ? `子任务 ${ev.name || "subagent"} 完成${clip ? `：${clip}` : ""}`
                  : `子任务 ${ev.name || "subagent"} 失败${clip ? `：${clip}` : ""}`,
              );
            },
            onToken: (token) => {
              if (metrics.llmFirstTokenAt == null) {
                metrics.llmFirstTokenAt = performance.now();
              }
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

        // Stream done — wait for queue drain via onIdle, or settle immediately.
        if (!queue.isBusy) resumeListeningIfWanted();
      } catch (e) {
        if (e instanceof ChatAbortedError) {
          speechAggRef.current.reset();
          queue.stop();
          // Interrupt path decides orb (resume listen vs idle).
          return;
        }
        setError(formatNetworkError(e, "chat / voice"));
        resumeListeningIfWanted();
      }
    },
    [
      appendLine,
      config,
      ensureTtsQueue,
      logTurnMetrics,
      resumeListeningIfWanted,
    ],
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
      // Text-input turns: mark STT final time as now for TTFT/e2e metrics.
      if (!metricsRef.current?.sttFinalAt) {
        metricsRef.current = {
          turnId: `${Date.now()}`,
          listenStartedAt: null,
          sttFinalAt: performance.now(),
          llmFirstTokenAt: null,
          ttsFirstByteAt: null,
          ttsFirstPlayAt: null,
          ttsServerMs: null,
        };
      }
      appendLine("user", trimmed);
      await runAssistant(trimmed);
    },
    [appendLine, dailyConnected, mode, runAssistant],
  );

  useEffect(() => {
    sendTextRef.current = sendText;
  }, [sendText]);

  const startBrowserListening = useCallback(() => {
    if (!support.stt) {
      setError("当前浏览器不支持语音识别，请用 Chrome，或改用文字输入");
      return;
    }
    setError(null);
    setPartial("");
    wantListeningRef.current = true;
    metricsRef.current = {
      turnId: `${Date.now()}`,
      listenStartedAt: performance.now(),
      sttFinalAt: null,
      llmFirstTokenAt: null,
      ttsFirstByteAt: null,
      ttsFirstPlayAt: null,
      ttsServerMs: null,
    };
    setOrb("listening");
    stopSpeaking();
    wsRef.current.cancel();

    sttRef.current.start(
      (r) => {
        setPartial(r.transcript);
        if (r.isFinal && r.transcript.trim()) {
          setPartial("");
          if (metricsRef.current) {
            metricsRef.current.sttFinalAt = performance.now();
          }
          // Pause STT while assistant runs (avoid TTS feedback into mic).
          sttRef.current.pause();
          void sendTextRef.current(r.transcript.trim());
        }
      },
      (err) => {
        setError(err);
        wantListeningRef.current = false;
        setOrb("idle");
      },
      { lang: ttsLanguageToSttLang(loadTtsPrefs().language) },
    );
  }, [support.stt]);

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
    wantListeningRef.current = false;
    sttRef.current.stop();
    setOrb("idle");
  }, [dailyConnected, disconnectDaily]);

  const interrupt = useCallback(() => {
    // Browser path: stop playback + WS cancel is the full interrupt.
    // Daily path also hits BargeInController via /api/voice/barge-in.
    speechAggRef.current.reset();
    ttsQueueRef.current?.stop();
    stopSpeaking();
    wsRef.current.cancel();
    sttRef.current.stop();
    if (modeRef.current === "daily" || dailyConnected) {
      void postBargeIn(voiceSessionRef.current ?? memorySessionRef.current);
      setOrb("listening");
      return;
    }
    // From speaking/thinking → auto resume continuous listen.
    wantListeningRef.current = true;
    startBrowserListening();
  }, [dailyConnected, postBargeIn, startBrowserListening]);

  const pathLabel =
    mode === "daily" || dailyConnected
      ? "Daily 全双工"
      : "浏览器 STT · 本机 TTS";

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
    pathLabel,
    activeSkills,
    skillScores,
    lastVoiceDebug,
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
