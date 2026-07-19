"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";

import { AppNav } from "@/components/AppNav";
import { ChatTranscript } from "@/components/voice/ChatTranscript";
import { MicButton } from "@/components/voice/MicButton";
import { VoiceOrb } from "@/components/voice/VoiceOrb";
import { useVoiceSession } from "@/hooks/useVoiceSession";
import {
  CONFIG_CHANGED_EVENT,
  getActiveProfile,
  type ModelProfile,
} from "@/lib/models";

export default function HomePage() {
  const {
    lines,
    partial,
    error,
    sessionId,
    voiceSessionId,
    pathLabel,
    ttsMode,
    activeSkills,
    skillScores,
    lastVoiceDebug,
    dailyConnected,
    support,
    sendText,
    startListening,
    stopListening,
    interrupt,
    orb,
  } = useVoiceSession();
  const [draft, setDraft] = useState("");
  const [active, setActive] = useState<ModelProfile | null>(null);
  const [debug, setDebug] = useState(false);

  useEffect(() => {
    const refresh = () => setActive(getActiveProfile());
    refresh();
    window.addEventListener(CONFIG_CHANGED_EVENT, refresh);
    return () => window.removeEventListener(CONFIG_CHANGED_EVENT, refresh);
  }, []);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    setDebug(params.get("debug") === "1");
  }, []);

  const skillLabel = useMemo(() => {
    if (activeSkills.length === 0) return null;
    return activeSkills
      .map((name) => {
        const score = skillScores[name];
        return score != null ? `${name}(${score.toFixed(2)})` : name;
      })
      .join(", ");
  }, [activeSkills, skillScores]);

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    const text = draft;
    setDraft("");
    void sendText(text);
  };

  return (
    <main className="mx-auto flex min-h-[100dvh] w-full max-w-3xl flex-col items-center px-4 pt-8 sm:pt-12">
      <header className="mb-4 text-center sm:mb-8">
        <h1
          className="text-4xl font-extrabold tracking-tight text-[var(--ink)] sm:text-5xl md:text-6xl"
          style={{ fontFamily: "var(--font-display)" }}
        >
          FAE
        </h1>
        <p className="mt-2 hidden max-w-md text-sm text-[var(--ink-soft)] sm:block">
          说话或打字。默认路径：浏览器听写 + 流式回复 + 本机 TTS（不依赖 Daily）。
        </p>
        <p className="mt-1 text-xs text-[var(--ink-soft)] sm:hidden">
          说话或打字 · 本机 TTS
        </p>
        <AppNav className="mt-3 sm:mt-4" />
        {skillLabel && (
          <p className="mt-2 text-xs text-[var(--accent)]" data-testid="active-skills">
            本轮技能：{skillLabel}
          </p>
        )}
        <p className="mt-2 hidden text-xs text-[var(--ink-soft)] sm:block">
          {pathLabel}
          {active ? ` · ${active.name}` : ""}
          {sessionId ? ` · 记忆:${sessionId}` : ""}
          {ttsMode ? ` · ${ttsMode}` : ""}
        </p>
        {debug && (
          <p
            className="mt-2 rounded-lg bg-black/[0.04] px-3 py-2 font-mono text-[11px] text-[var(--ink-soft)]"
            data-testid="voice-debug"
          >
            debug · orb={orb}
            {voiceSessionId ? ` · voice=${voiceSessionId.slice(0, 8)}` : ""}
            {lastVoiceDebug ? ` · ${lastVoiceDebug}` : " · (no turn metrics yet)"}
          </p>
        )}
        {orb === "speaking" && (
          <p className="mt-2 text-xs text-[var(--ink-soft)]">
            正在合成 / 播放本机语音（长回复可能需十几秒）…
          </p>
        )}
      </header>

      <div className="scale-75 sm:scale-100">
        <VoiceOrb state={orb} />
      </div>

      <div className="mt-4 flex flex-wrap items-center justify-center gap-3 sm:mt-8">
        <MicButton
          active={orb === "listening" || dailyConnected}
          onStart={startListening}
          onStop={stopListening}
        />
        {(orb === "speaking" || orb === "thinking") && (
          <button
            type="button"
            onClick={interrupt}
            className="rounded-full border border-black/15 bg-white/60 px-4 py-3 text-sm text-[var(--ink)]"
          >
            打断
          </button>
        )}
      </div>

      {!support.stt && (
        <p className="mt-3 text-xs text-[var(--ink-soft)]">
          当前环境无 Web Speech STT，请用文字输入（推荐 Chrome）。
        </p>
      )}

      <div className="flex w-full flex-1 flex-col">
        <ChatTranscript lines={lines} partial={partial} />
      </div>

      <form
        onSubmit={onSubmit}
        className="fae-composer sticky bottom-0 z-10 mx-auto mt-auto flex w-full max-w-xl gap-2 border-t border-black/5 bg-[color-mix(in_srgb,var(--bg-0)_88%,transparent)] px-1 pt-3 backdrop-blur-md sm:px-4"
      >
        <input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder="文字回退输入…"
          className="min-w-0 flex-1 rounded-full border border-black/10 bg-white/80 px-4 py-3 text-sm outline-none focus:border-[var(--accent)]"
        />
        <button
          type="submit"
          className="rounded-full px-5 py-3 text-sm font-semibold text-white"
          style={{ background: "var(--accent)" }}
        >
          发送
        </button>
      </form>

      {error && (
        <p className="mt-2 max-w-xl px-4 pb-2 text-center text-sm text-[var(--danger)]">
          {error}
        </p>
      )}
    </main>
  );
}
