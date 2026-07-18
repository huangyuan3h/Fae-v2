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
import { createVoiceSession } from "@/lib/pipecat-client";
import {
  BrowserSTT,
  speak,
  speechSupported,
  stopSpeaking,
} from "@/lib/speech";
import { ChatAbortedError, WsChatClient } from "@/lib/ws-chat";

export type OrbState = "idle" | "listening" | "thinking" | "speaking";
export type TransportMode = "browser" | "daily";

export type ChatLine = {
  id: string;
  role: "user" | "assistant";
  content: string;
};

export function useVoiceSession() {
  const [config, setConfigState] = useState<AgentConfig>(DEFAULT_CONFIG);
  const [orb, setOrb] = useState<OrbState>("idle");
  const [lines, setLines] = useState<ChatLine[]>([]);
  const [partial, setPartial] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [mode, setMode] = useState<TransportMode>("browser");
  const [preferDaily, setPreferDaily] = useState(false);
  const [dailyConnected, setDailyConnected] = useState(false);
  const [support, setSupport] = useState({ stt: false, tts: false });

  const wsRef = useRef(new WsChatClient());
  const sttRef = useRef(new BrowserSTT());
  const dailyRef = useRef<DailyCall | null>(null);
  const assistantBuf = useRef("");
  const connectingDaily = useRef(false);
  const sessionIdRef = useRef<string | null>(null);

  useEffect(() => {
    sessionIdRef.current = sessionId;
  }, [sessionId]);

  useEffect(() => {
    setConfigState(loadConfig());
    setSupport(speechSupported());
    createVoiceSession({ preferDaily: false })
      .then((s) => {
        setSessionId(s.sessionId);
        setMode(s.mode);
      })
      .catch(() => {
        /* backend optional at first paint */
      });
    const stt = sttRef.current;
    const ws = wsRef.current;
    return () => {
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

  const connectDaily = useCallback(async () => {
    if (connectingDaily.current || dailyConnected) return;
    if (!config.apiKey.trim()) {
      setError("Daily 模式仍需要 LLM API Key（DashScope / OpenAI-compatible）");
      return;
    }
    connectingDaily.current = true;
    setError(null);
    setOrb("thinking");
    try {
      const session = await createVoiceSession({
        preferDaily: true,
        config,
      });
      setSessionId(session.sessionId);
      setMode(session.mode);
      if (session.mode !== "daily" || !session.roomUrl || !session.token) {
        setError(session.detail || "服务端未启用 Daily，已保持浏览器模式");
        setOrb("idle");
        return;
      }
      const call = await joinDailyRoom(session.roomUrl, session.token);
      dailyRef.current = call;
      setDailyConnected(true);
      setOrb("listening");
      call.on("left-meeting", () => {
        setDailyConnected(false);
        setOrb("idle");
      });
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setOrb("idle");
    } finally {
      connectingDaily.current = false;
    }
  }, [config, dailyConnected]);

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
        if (e instanceof ChatAbortedError) {
          setOrb("idle");
          return;
        }
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

  const startListening = useCallback(() => {
    if (preferDaily || mode === "daily") {
      void connectDaily();
      return;
    }
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
  }, [connectDaily, mode, preferDaily, sendText, support.stt]);

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
    void postBargeIn(sessionIdRef.current);
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
    mode,
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
