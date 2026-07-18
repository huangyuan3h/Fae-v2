"use client";

import { FormEvent, useState } from "react";

import { AgentSettings } from "@/components/voice/AgentSettings";
import { ChatTranscript } from "@/components/voice/ChatTranscript";
import { MicButton } from "@/components/voice/MicButton";
import { VoiceOrb } from "@/components/voice/VoiceOrb";
import { useVoiceSession } from "@/hooks/useVoiceSession";

export default function HomePage() {
  const {
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
  } = useVoiceSession();
  const [draft, setDraft] = useState("");

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    const text = draft;
    setDraft("");
    void sendText(text);
  };

  return (
    <main className="mx-auto flex min-h-screen w-full max-w-3xl flex-col items-center px-4 pb-10 pt-12">
      <header className="mb-8 text-center">
        <h1
          className="text-5xl font-extrabold tracking-tight text-[var(--ink)] md:text-6xl"
          style={{ fontFamily: "var(--font-display)" }}
        >
          FAE
        </h1>
        <p className="mt-2 max-w-md text-sm text-[var(--ink-soft)]">
          说话或打字。浏览器语音识别 + 流式回复 + 语音播报。
        </p>
      </header>

      <VoiceOrb state={orb} />

      <div className="mt-8 flex flex-wrap items-center justify-center gap-3">
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

      <ChatTranscript lines={lines} partial={partial} />

      <form
        onSubmit={onSubmit}
        className="mx-auto mt-4 flex w-full max-w-xl gap-2 px-4"
      >
        <input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder="文字回退输入…"
          className="min-w-0 flex-1 rounded-full border border-black/10 bg-white/70 px-4 py-3 text-sm outline-none focus:border-[var(--accent)]"
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
        <p className="mt-3 max-w-xl px-4 text-center text-sm text-[var(--danger)]">
          {error}
        </p>
      )}

      <details className="mt-8 w-full max-w-xl">
        <summary className="cursor-pointer px-4 text-sm text-[var(--ink-soft)]">
          Agent 设置
          {sessionId ? ` · session ${sessionId.slice(0, 8)}` : ""}
          {` · ${mode}`}
        </summary>
        <AgentSettings
          config={config}
          onChange={setConfig}
          preferDaily={preferDaily}
          onPreferDailyChange={setPreferDaily}
          mode={mode}
        />
      </details>
    </main>
  );
}
