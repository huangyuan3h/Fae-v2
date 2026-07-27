"use client";

import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useState } from "react";

import { AppHeader } from "@/components/AppHeader";
import { Badge } from "@/components/ui/Badge";
import { ChatHistorySidebar } from "@/components/voice/ChatHistorySidebar";
import { ChatTranscript } from "@/components/voice/ChatTranscript";
import { Composer } from "@/components/voice/Composer";
import { ExecutionPanel } from "@/components/voice/ExecutionPanel";
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
    pathLabel,
    ttsMode,
    activeSkills,
    skillScores,
    turnExecutions,
    sendApprovalDecision,
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
  const [active, setActive] = useState<ModelProfile | null>(null);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [detailsOpen, setDetailsOpen] = useState(false);
  const [mounted, setMounted] = useState(false);
  const debug = search.get("debug") === "1";

  useEffect(() => {
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
    if (lastUsage.prompt_tokens != null) parts.push(`prompt ${lastUsage.prompt_tokens}`);
    if (lastUsage.completion_tokens != null) parts.push(`out ${lastUsage.completion_tokens}`);
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

  const lastAssistantLine = useMemo(() => {
    for (let i = lines.length - 1; i >= 0; i--) {
      if (lines[i].role === "assistant") return lines[i];
    }
    return null;
  }, [lines]);

  const currentExecution = useMemo(() => {
    if (!lastAssistantLine) return null;
    return turnExecutions[lastAssistantLine.id] ?? null;
  }, [lastAssistantLine, turnExecutions]);

  const sttSupported = mounted && support.stt;

  return (
    <>
      <AppHeader />
      <main className="mx-auto flex w-full max-w-7xl gap-4 px-4 py-4">
        <aside className="hidden w-64 shrink-0 lg:block">
          <div className="sticky top-16">
            <ChatHistorySidebar
              sessions={sessions}
              activeSessionId={sessionId}
              retentionDays={retentionDays}
              onSwitch={(id) => void switchSession(id)}
              onRename={(id, title) => void renameSession(id, title)}
              onPin={(id, pinned) => void pinSession(id, pinned)}
            />
          </div>
        </aside>

        <section className="flex min-w-0 flex-1 flex-col">
          <div className="mb-2 flex items-center justify-between gap-2 px-1">
            <div className="flex flex-wrap items-center gap-2 text-[11px] text-[var(--ink-soft)]">
              {skillLabel && (
                <Badge tone="accent" data-testid="active-skills">
                  本轮技能: {skillLabel}
                </Badge>
              )}
              {(pathLabel || active || sessionId || ttsMode) && (
                <span className="hidden sm:inline">
                  {[pathLabel, active?.name, sessionId ? `记忆:${sessionId}` : null, ttsMode]
                    .filter(Boolean)
                    .join(" · ")}
                </span>
              )}
            </div>
            <div className="flex items-center gap-2">
              {(usageLabel || totalUsageLabel) && (
                <button
                  type="button"
                  onClick={() => setDetailsOpen((v) => !v)}
                  className="rounded-full border border-black/10 bg-white/60 px-2.5 py-1 text-[11px] text-[var(--ink-soft)] hover:bg-white/80"
                  aria-expanded={detailsOpen}
                  data-testid="details-toggle"
                >
                  {detailsOpen ? "收起" : "详情"}
                </button>
              )}
            </div>
          </div>

          {detailsOpen && (usageLabel || totalUsageLabel) && (
            <div className="mb-2 rounded-xl border border-black/[0.06] bg-white/60 px-3 py-2 text-[11px] text-[var(--ink-soft)]">
              {usageLabel && (
                <p data-testid="usage-summary">{usageLabel}</p>
              )}
              {totalUsageLabel && <p>{totalUsageLabel}</p>}
              {historyNote && <p>{historyNote}</p>}
              {debug && (
                <p className="mt-1 font-mono text-[10px]" data-testid="voice-debug">
                  debug · orb={orb}
                  {lastVoiceDebug ? ` · ${lastVoiceDebug}` : " · (no turn metrics yet)"}
                </p>
              )}
            </div>
          )}

          {sidebarOpen && (
            <div className="mb-4 lg:hidden">
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

          <div className="flex w-full flex-1 flex-col">
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

          <Composer
            orb={orb}
            sttAvailable={sttSupported}
            micActive={orb === "listening" || dailyConnected}
            onStartMic={startListening}
            onStopMic={stopListening}
            onInterrupt={interrupt}
            onSubmit={(text) => void sendText(text)}
          />

          {error && (
            <p className="mx-auto mt-2 max-w-2xl px-2 pb-2 text-center text-sm text-[var(--danger)]" data-testid="composer-error">
              {error}
            </p>
          )}
        </section>

        <aside className="hidden w-72 shrink-0 xl:block">
          <div className="sticky top-16">
            <ExecutionPanel
              execution={currentExecution}
              approval={{
                onApprove: (approvalId, decision) => {
                  sendApprovalDecision(approvalId, {
                    action: "approve",
                    remember: decision.remember ?? null,
                  });
                },
                onDeny: (approvalId) =>
                  sendApprovalDecision(approvalId, { action: "deny", remember: null }),
                onCancel: (approvalId) =>
                  sendApprovalDecision(approvalId, { action: "cancel", remember: null }),
              }}
            />
          </div>
        </aside>
      </main>
    </>
  );
}