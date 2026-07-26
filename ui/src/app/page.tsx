"use client";

import { useSearchParams } from "next/navigation";
import { FormEvent, Suspense, useEffect, useMemo, useState } from "react";

import { AppNav } from "@/components/AppNav";
import { ChatHistorySidebar } from "@/components/voice/ChatHistorySidebar";
import { AgentSteps } from "@/components/voice/AgentSteps";
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
  return (
    <Suspense fallback={<main className="p-8 text-sm text-[var(--ink-soft)]">加载中…</main>}>
      <HomeContent />
    </Suspense>
  );
}

function HomeContent() {
  const search = useSearchParams();
  const {

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
    pathLabel,
    ttsMode,
    activeSkills,
    skillScores,
    steps,
    lastVoiceDebug,
    historyNote,
    lastUsage,
    usageTotals,
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
  const [sidebarOpen, setSidebarOpen] = useState(false);
  // Gate browser-only output behind a post-mount flag so the server-rendered
  // HTML and the first client render stay identical. `speechSupported()`
  // returns `stt:false` on the server (no `window`) but `stt:true` in Chrome,
  // which would otherwise cause a hydration mismatch when the STT warning
  // appears/disappears between SSR and client.
  const [mounted, setMounted] = useState(false);
  const debug = search.get("debug") === "1";

  useEffect(() => {
    // Post-mount flip so browser-only output (e.g. the STT warning that
    // depends on `window.SpeechRecognition`) is only rendered after the
    // client has hydrated, eliminating SSR/CSR divergence on first paint.
    // eslint-disable-next-line react-hooks/set-state-in-effect -- intentional one-shot mount flag
    setMounted(true);
    const refresh = () => setActive(getActiveProfile());
    refresh();
    window.addEventListener(CONFIG_CHANGED_EVENT, refresh);
    return () => window.removeEventListener(CONFIG_CHANGED_EVENT, refresh);
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

  const usageLabel = useMemo(() => {
    if (!lastUsage) return null;
    const parts: string[] = [];
    if (lastUsage.prompt_tokens != null) {
      parts.push(`prompt ${lastUsage.prompt_tokens}`);
    }
    if (lastUsage.completion_tokens != null) {
      parts.push(`out ${lastUsage.completion_tokens}`);
    }
    if (lastUsage.cached_tokens != null && lastUsage.cached_tokens > 0) {
      const total = lastUsage.prompt_tokens ?? lastUsage.cached_tokens;
      const ratio = total > 0 ? Math.round((lastUsage.cached_tokens / total) * 100) : 0;
      parts.push(`cache ${lastUsage.cached_tokens} (${ratio}%)`);
    }
    return parts.length ? `tokens: ${parts.join(" / ")}` : null;
  }, [lastUsage]);

  const totalUsageLabel = useMemo(() => {
    if (!usageTotals) return null;
    const p = usageTotals.prompt_tokens ?? 0;
    const c = usageTotals.cached_tokens ?? 0;
    if (p === 0 && c === 0) return null;
    const ratio = p > 0 ? Math.round((c / p) * 100) : 0;
    return `累计 prompt ${p} / cache ${c} (${ratio}%)`;
  }, [usageTotals]);

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    const text = draft;
    setDraft("");
    void sendText(text);
  };

  const onComposerKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key !== "Enter" || e.shiftKey || e.nativeEvent.isComposing) return;
    e.preventDefault();
    e.currentTarget.form?.requestSubmit();
  };

  return (
    <main className="mx-auto flex min-h-[100dvh] w-full max-w-5xl gap-6 px-4 pt-8 sm:pt-12 lg:max-w-6xl">
      <div className="hidden w-72 shrink-0 lg:block">
        <div className="sticky top-6">
          <ChatHistorySidebar
            sessions={sessions}
            activeSessionId={sessionId}
            retentionDays={retentionDays}
            onSwitch={(id) => void switchSession(id)}
            onRename={(id, title) => void renameSession(id, title)}
            onPin={(id, pinned) => void pinSession(id, pinned)}
          />
        </div>
      </div>
      <div className="mx-auto flex min-w-0 max-w-3xl flex-1 flex-col items-center">
        {sidebarOpen && (
          <div className="mb-4 w-full lg:hidden">
            <ChatHistorySidebar
              sessions={sessions}
              activeSessionId={sessionId}
              retentionDays={retentionDays}
              onSwitch={(id) => {
                setSidebarOpen(false);
                void switchSession(id);
              }}
              onRename={(id, title) => void renameSession(id, title)}
              onPin={(id, pinned) => void pinSession(id, pinned)}
            />
          </div>
        )}
        <header className="mb-4 text-center sm:mb-8">
          <div className="flex items-center justify-center gap-2">
            <button
              type="button"
              onClick={() => setSidebarOpen((v) => !v)}
              className="rounded-full border border-black/15 bg-white/70 px-3 py-1 text-xs text-[var(--ink-soft)] lg:hidden"
              data-testid="chat-history-toggle"
            >
              {sidebarOpen ? "收起历史" : "历史会话"}
            </button>
          </div>
          <h1
            className="mt-2 text-4xl font-extrabold tracking-tight text-[var(--ink)] sm:text-5xl md:text-6xl"
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
            {historyNote ? ` · ${historyNote}` : ""}
          </p>
          {(usageLabel || totalUsageLabel) && (
            <p
              className="mt-1 hidden text-xs text-[var(--ink-soft)] sm:block"
              data-testid="usage-summary"
            >
              {usageLabel}
              {usageLabel && totalUsageLabel ? " · " : ""}
              {totalUsageLabel}
            </p>
          )}
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

        {mounted && !support.stt && (
          <p className="mt-3 text-xs text-[var(--ink-soft)]">
            当前环境无 Web Speech STT，请用文字输入（推荐 Chrome）。
          </p>
        )}

        <div className="flex w-full flex-1 flex-col">
          <AgentSteps steps={steps} />
          {(historyHasMore || loadingEarlier) && (
            <div className="mt-2 flex justify-center">
              <button
                type="button"
                onClick={() => void loadEarlier()}
                disabled={loadingEarlier}
                className="rounded-full border border-black/10 bg-white/70 px-3 py-1 text-xs text-[var(--ink-soft)] disabled:opacity-50"
                data-testid="chat-history-load-earlier"
              >
                {loadingEarlier ? "加载中…" : "加载更早的对话"}
              </button>
            </div>
          )}
          <ChatTranscript lines={lines} partial={partial} />
        </div>

        <form
          onSubmit={onSubmit}
          className="fae-composer sticky bottom-0 z-10 mx-auto mt-auto flex w-full max-w-xl items-end gap-2 border-t border-black/5 bg-[color-mix(in_srgb,var(--bg-0)_88%,transparent)] px-1 pt-3 backdrop-blur-md sm:px-4"
        >
          <textarea
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={onComposerKeyDown}
            rows={3}
            placeholder="输入消息… Enter 发送，Shift+Enter 换行"
            className="min-h-24 max-h-56 min-w-0 flex-1 resize-y rounded-2xl border border-black/10 bg-white/80 px-4 py-3 text-sm leading-6 outline-none focus:border-[var(--accent)]"
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
      </div>
    </main>
  );
}
