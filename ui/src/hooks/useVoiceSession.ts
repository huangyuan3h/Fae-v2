"use client";

import type { DailyCall } from "@daily-co/daily-js";
import { useCallback, useEffect, useEffectEvent, useRef, useState } from "react";

import {
  DEFAULT_MEMORY_SESSION_ID,
  getMemorySessionId,
  MEMORY_SESSION_KEY,
} from "@/lib/client-identity";
import {
  type AgentConfig,
  loadConfig,
  saveConfig,
  authHeaders,
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
import {
  ChatAbortedError,
  fetchChatHistory,
  fetchChatSessions,
  setChatSessionPinned,
  updateChatSessionTitle,
  WsChatClient,
  type ChatSessionSummary,
  type TokenUsage,
} from "@/lib/ws-chat";

export type OrbState = "idle" | "listening" | "thinking" | "speaking";
export type TransportMode = "browser" | "daily";
export type TtsMode = "local-tts" | "none";

export type ChatLine = {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  historyTurnId?: string;
  historyCreatedAt?: string;
};

export type ChatStep = {
  id: string;
  kind: "skill" | "subagent" | "tool";
  name: string;
  role: "primary" | "secondary";
  status: "available" | "running" | "done" | "error";
  detail?: string;
  score?: number;
};

function addOrUndef(base: number | undefined, delta: number | undefined): number | undefined {
  if (delta == null) return base;
  return (base ?? 0) + delta;
}

export function useVoiceSession() {
  const [config, setConfigState] = useState<AgentConfig>(() => syncActiveConfig());
  const [orb, setOrb] = useState<OrbState>("idle");
  const [lines, setLines] = useState<ChatLine[]>([]);
  const [partial, setPartial] = useState("");
  const [error, setError] = useState<string | null>(null);
  // Stable memory bucket shared with proactive / consolidate (localStorage).
  // Mutable so the user can switch sessions from the sidebar.
  const [sessionId, setSessionIdState] = useState<string>(DEFAULT_MEMORY_SESSION_ID);
  const [voiceSessionId, setVoiceSessionId] = useState<string | null>(null);
  const [mode, setMode] = useState<TransportMode>("browser");
  // Browser path always uses local TTS when available; do not wait for first enqueue.
  const [ttsMode, setTtsMode] = useState<TtsMode>("local-tts");
  const [activeSkills, setActiveSkills] = useState<string[]>([]);
  const [skillScores, setSkillScores] = useState<Record<string, number>>({});
  const [steps, setSteps] = useState<ChatStep[]>([]);
  const [lastVoiceDebug, setLastVoiceDebug] = useState<string | null>(null);
  // SSR-safe initial value: localStorage may be `true` on the client but the
  // server always returns `false` here. Reading the persisted flag inside a
  // post-mount effect avoids hydration mismatches if a future change ever
  // surfaces `preferDaily` into the DOM.
  const [preferDaily, setPreferDailyState] = useState<boolean>(false);
  const [dailyConnected, setDailyConnected] = useState(false);
  const [support] = useState(() => speechSupported());
  const [historyNote, setHistoryNote] = useState<string | null>(null);
  const [sessions, setSessions] = useState<ChatSessionSummary[]>([]);
  const [retentionDays, setRetentionDays] = useState(7);
  const [historyHasMore, setHistoryHasMore] = useState(false);
  const [loadingEarlier, setLoadingEarlier] = useState(false);
  const [lastUsage, setLastUsage] = useState<TokenUsage | null>(null);
  const [usageTotals, setUsageTotals] = useState<TokenUsage | null>(null);
  // Final transcript queued by the STT callback; consumed by an Effect so the
  // latest `sendText` is always used without mutating a Ref.
  const [pendingText, setPendingText] = useState<string | null>(null);

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
  const historyTurnIdsRef = useRef<Set<string>>(new Set());
  const historyLoadedRef = useRef(false);
  const oldestLoadedAtRef = useRef<string | null>(null);
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

  const reloadSessions = useCallback(async () => {
    try {
      const data = await fetchChatSessions();
      setSessions(data.sessions);
      if (data.retention_days) {
        setRetentionDays(data.retention_days);
      }
    } catch {
      /* ignore — sidebar is best-effort */
    }
  }, []);

  const applyHistoryPayload = useCallback(
    (
      payload: Awaited<ReturnType<typeof fetchChatHistory>>,
      mode: "replace" | "prepend",
    ) => {
      const restored: ChatLine[] = payload.turns.flatMap((turn) => {
        const key = `history-${turn.id}`;
        historyTurnIdsRef.current.add(turn.id);
        return [
          {
            id: `${key}-u`,
            role: "user" as const,
            content: turn.user_text,
            historyTurnId: turn.id,
            historyCreatedAt: turn.created_at,
          },
          {
            id: `${key}-a`,
            role: "assistant" as const,
            content: turn.assistant_text,
            historyTurnId: turn.id,
            historyCreatedAt: turn.created_at,
          },
        ];
      });
      if (restored.length > 0) {
        oldestLoadedAtRef.current =
          restored[0].historyCreatedAt ?? oldestLoadedAtRef.current;
      } else if (mode === "replace") {
        oldestLoadedAtRef.current = null;
      }
      historyLoadedRef.current = true;
      if (payload.retention_days) {
        setRetentionDays(payload.retention_days);
      }
      const retention = Math.max(1, payload.retention_days || 7);
      const totalLoaded = payload.turns.length;
      if (mode === "replace") {
        setHistoryHasMore(payload.has_more);
        setHistoryNote(
          totalLoaded > 0
            ? `已加载近 ${retention} 天内的 ${totalLoaded} 条对话`
            : null,
        );
        if (totalLoaded > 0) {
          setLines((prev) => {
            const existing = new Set(prev.map((line) => line.id));
            const additions = restored.filter((line) => !existing.has(line.id));
            return additions.length > 0 ? [...additions, ...prev] : prev;
          });
        }
      } else {
        setHistoryHasMore(payload.has_more);
        setLines((prev) => {
          const existing = new Set(prev.map((line) => line.id));
          const additions = restored.filter((line) => !existing.has(line.id));
          return additions.length > 0 ? [...additions, ...prev] : prev;
        });
      }
    },
    [],
  );

  const loadSession = useCallback(
    async (sid: string) => {
      historyLoadedRef.current = false;
      historyTurnIdsRef.current = new Set();
      oldestLoadedAtRef.current = null;
      setLines([]);
      setHistoryNote(null);
      setHistoryHasMore(false);
      try {
        const payload = await fetchChatHistory(sid, { limit: 50 });
        applyHistoryPayload(payload, "replace");
      } catch {
        setHistoryNote(null);
      }
      void reloadSessions();
    },
    [applyHistoryPayload, reloadSessions],
  );

  useEffect(() => {
    // Hydrate sessionId from localStorage on first mount.
    // eslint-disable-next-line react-hooks/set-state-in-effect -- one-shot localStorage hydration
    setSessionIdState(getMemorySessionId());
  }, []);

  useEffect(() => {
    // Initial / sessionId-change sync with backend history + sessions list.
    /* eslint-disable react-hooks/set-state-in-effect -- data sync, not cascading render */
    void reloadSessions();
    void loadSession(sessionId);
    /* eslint-enable react-hooks/set-state-in-effect */
  }, [sessionId, loadSession, reloadSessions]);

  const switchSession = useCallback(
    async (nextId: string) => {
      const target = (nextId || "").trim() || DEFAULT_MEMORY_SESSION_ID;
      if (target === sessionId) return;
      setSessionIdState(target);
      try {
        window.localStorage.setItem(MEMORY_SESSION_KEY, target);
      } catch {
        /* ignore */
      }
      await loadSession(target);
    },
    [sessionId, loadSession],
  );

  const loadEarlier = useCallback(async () => {
    const sid = memorySessionRef.current;
    const cursor = oldestLoadedAtRef.current;
    if (!cursor || loadingEarlier) return;
    setLoadingEarlier(true);
    try {
      const payload = await fetchChatHistory(sid, {
        limit: 50,
        before: cursor,
      });
      applyHistoryPayload(payload, "prepend");
    } catch {
      /* ignore */
    } finally {
      setLoadingEarlier(false);
    }
  }, [applyHistoryPayload, loadingEarlier]);

  const renameSession = useCallback(
    async (sid: string, title: string) => {
      try {
        const summary = await updateChatSessionTitle(sid, title);
        setSessions((prev) =>
          prev.map((s) =>
            s.session_id === summary.session_id ? summary : s,
          ),
        );
      } catch {
        /* ignore */
      }
    },
    [],
  );

  const pinSession = useCallback(async (sid: string, pinned: boolean) => {
    try {
      const summary = await setChatSessionPinned(sid, pinned);
      setSessions((prev) => {
        const next = prev.map((s) =>
          s.session_id === summary.session_id ? summary : s,
        );
        return next.sort((a, b) => {
          if (a.pinned !== b.pinned) return a.pinned ? -1 : 1;
          return b.last_activity_at.localeCompare(a.last_activity_at);
        });
      });
    } catch {
      /* ignore */
    }
  }, []);

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
    // First sync the SSR-safe default from localStorage so the UI matches the
    // user's last selection. Stays inside the effect so SSR/CSR agree on the
    // initial render before this re-render fires.
    // eslint-disable-next-line react-hooks/set-state-in-effect -- one-shot hydration sync
    setPreferDailyState(loadPreferDaily());
    void fetch(`${backendHttpBase()}/api/voice/status`, {
      headers: authHeaders(),
    })
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
        headers: { "Content-Type": "application/json", ...authHeaders() },
        body: JSON.stringify({ session_id: id }),
      });
    } catch {
      /* local stopSpeaking / WS cancel still applied */
    }
  }, []);

  const connectDaily = useCallback(async (): Promise<boolean> => {
    if (connectingDaily.current || dailyConnected) return dailyConnected;
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
    setLines((prev) => {
      if (
        historyLoadedRef.current &&
        historyTurnIdsRef.current.size > 0 &&
        prev.some((line) => historyTurnIdsRef.current.has(line.historyTurnId ?? ""))
      ) {
        const cutoff = prev.findIndex(
          (line) => line.historyTurnId && historyTurnIdsRef.current.has(line.historyTurnId),
        );
        const tail = cutoff >= 0 ? prev.slice(cutoff) : prev;
        const seenUser = new Set<string>();
        const filtered = tail.filter((line) => {
          if (line.role !== "user") return true;
          if (seenUser.has(line.content)) return false;
          seenUser.add(line.content);
          return true;
        });
        return [
          ...filtered,
          {
            id: `${Date.now()}-${Math.random()}`,
            role,
            content,
          },
        ];
      }
      return [
        ...prev,
        { id: `${Date.now()}-${Math.random()}`, role, content },
      ];
    });
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
          setPendingText(r.transcript.trim());
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
      // Browser Key optional — Core merges server DASHSCOPE / PROACTIVE_LLM_*.
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
              ? `${msg} — 请确认 :8880 TTS 服务已启动（doc/operations/LOCAL_TTS.md）`
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
        setSteps([]);
        await wsRef.current.chat(
          userText,
          config,
          {
            onSkills: (names, scores, lazyCatalog) => {
              setActiveSkills(names);
              setSkillScores(scores ?? {});
              const active = names.map((name, index) => ({
                id: `skill-active-${name}`,
                kind: "skill" as const,
                name,
                role: (index === 0 ? "primary" : "secondary") as
                  | "primary"
                  | "secondary",
                status: "done" as const,
                score: scores?.[name],
              }));
              const lazy = (lazyCatalog ?? [])
                .filter((name) => !names.includes(name))
                .map((name) => ({
                  id: `skill-lazy-${name}`,
                  kind: "skill" as const,
                  name,
                  role: "secondary" as const,
                  status: "available" as const,
                  detail: "按需加载",
                }));
              setSteps((prev) => [
                ...active,
                ...lazy,
                ...prev.filter((step) => step.kind !== "skill"),
              ]);
            },
            onSubagent: (ev) => {
              const id = `subagent-${ev.name || "subagent"}`;
              const detail =
                ev.phase === "start"
                  ? ev.task
                  : (ev.summary || ev.error || "").trim().slice(0, 500);
              setSteps((prev) => {
                const next: ChatStep = {
                  id,
                  kind: "subagent",
                  name: ev.name || "subagent",
                  role: "secondary",
                  status:
                    ev.phase === "start"
                      ? "running"
                      : ev.ok === false
                        ? "error"
                        : "done",
                  detail,
                };
                return [...prev.filter((step) => step.id !== id), next];
              });
            },
            onTool: (ev) => {
              const detail =
                ev.phase === "start"
                  ? ev.arguments
                  : (ev.result || "").slice(0, 2000);
              setSteps((prev) => {
                const next: ChatStep = {
                  id: `tool-${ev.id}`,
                  kind: "tool",
                  name: ev.name,
                  role: "secondary",
                  status:
                    ev.phase === "start"
                      ? "running"
                      : ev.ok
                        ? "done"
                        : "error",
                  detail,
                };
                return [
                  ...prev.filter((step) => step.id !== next.id),
                  next,
                ];
              });
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
            onDone: (info) => {
              speechAggRef.current.clearTimer();
              const leftover = speechAggRef.current.flush();
              if (leftover) enqueueChunks([leftover]);
              const usage = info?.usage ?? null;
              if (usage) {
                setLastUsage(usage);
                setUsageTotals((prev: TokenUsage | null) => {
                  const base: TokenUsage = prev ?? {
                    prompt_tokens: 0,
                    completion_tokens: 0,
                    total_tokens: 0,
                    cached_tokens: 0,
                  };
                  return {
                    prompt_tokens: addOrUndef(
                      base.prompt_tokens, usage.prompt_tokens,
                    ),
                    completion_tokens: addOrUndef(
                      base.completion_tokens, usage.completion_tokens,
                    ),
                    total_tokens: addOrUndef(
                      base.total_tokens, usage.total_tokens,
                    ),
                    cached_tokens: addOrUndef(
                      base.cached_tokens, usage.cached_tokens,
                    ),
                  };
                });
              }
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

  // Drain final transcripts queued by the STT callback. The STT onResult
  // callback cannot call sendText directly (it's invoked by the browser
  // outside any React Effect), so it enqueues a state update instead, and
  // this Effect invokes the latest sendText via the Effect Event wrapper on
  // the next microtask. The microtask hop keeps setState out of the
  // synchronous effect body so the react-hooks/set-state-in-effect rule is
  // satisfied, and the Effect Event lets us call the latest sendText without
  // re-firing the effect on every sendText identity change.
  const dispatchFinalText = useEffectEvent((text: string) => {
    void sendText(text);
  });

  useEffect(() => {
    if (!pendingText) return;
    const text = pendingText;
    queueMicrotask(() => {
      dispatchFinalText(text);
    });
  }, [pendingText]);

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
          setPendingText(r.transcript.trim());
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
    sessions,
    retentionDays,
    switchSession,
    renameSession,
    pinSession,
    historyHasMore,
    loadingEarlier,
    loadEarlier,
    voiceSessionId,
    mode,
    ttsMode,
    pathLabel,
    activeSkills,
    skillScores,
    steps,
    lastVoiceDebug,
    historyNote,
    lastUsage,
    usageTotals,
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
