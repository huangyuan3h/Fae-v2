"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense } from "react";

import { AppNav } from "@/components/AppNav";
import { ModelsPanel } from "@/components/settings/ModelsPanel";
import { NotificationsPanel } from "@/components/settings/NotificationsPanel";
import { PersonaPanel } from "@/components/settings/PersonaPanel";
import { ProfilePanel } from "@/components/settings/ProfilePanel";
import { VoicePanel } from "@/components/settings/VoicePanel";

type Tab = "persona" | "profile" | "models" | "voice" | "notifications";

const TABS: Tab[] = ["persona", "profile", "models", "voice", "notifications"];

function SettingsInner() {
  const search = useSearchParams();
  const router = useRouter();
  const queryTab = search.get("tab");
  const tab: Tab = (TABS as string[]).includes(queryTab ?? "")
    ? (queryTab as Tab)
    : "persona";

  return (
    <main className="mx-auto min-h-screen w-full max-w-3xl px-4 pb-16 pt-10">
      <header className="mb-6">
        <AppNav className="mb-4 justify-start" />
        <h1
          className="mt-3 text-3xl font-extrabold tracking-tight text-[var(--ink)] md:text-4xl"
          style={{ fontFamily: "var(--font-display)" }}
        >
          Settings
        </h1>
        <p className="mt-1 text-sm text-[var(--ink-soft)]">
          Reference Client：密钥可选；常驻 Core 用服务端{" "}
          <code className="text-[11px]">DASHSCOPE</code> /{" "}
          <code className="text-[11px]">PROACTIVE_LLM_*</code>。见{" "}
          <code className="text-[11px]">doc/operations/DEPLOY.md</code>。
        </p>
      </header>

      <nav className="mb-8 flex flex-wrap gap-2 border-b border-black/10 pb-4">
        {(
          [
            { id: "persona" as const, label: "人设" },
            { id: "profile" as const, label: "重要信息" },
            { id: "models" as const, label: "模型" },
            { id: "voice" as const, label: "语音" },
            { id: "notifications" as const, label: "通知" },
          ] as const
        ).map((item) => {
          const active = tab === item.id;
          return (
            <button
              key={item.id}
              type="button"
              onClick={() => router.replace(`/settings?tab=${item.id}`)}
              className="rounded-full px-3 py-1.5 text-sm transition"
              style={{
                background: active ? "var(--accent)" : "transparent",
                color: active ? "#fff" : "var(--ink-soft)",
                border: active ? "none" : "1px solid rgba(0,0,0,0.1)",
              }}
            >
              {item.label}
            </button>
          );
        })}
      </nav>

      {tab === "persona" && <PersonaPanel />}
      {tab === "profile" && <ProfilePanel />}
      {tab === "models" && <ModelsPanel />}
      {tab === "voice" && <VoicePanel />}
      {tab === "notifications" && <NotificationsPanel />}
    </main>
  );
}

export default function SettingsPage() {
  return (
    <Suspense fallback={<main className="p-8 text-sm text-[var(--ink-soft)]">加载中…</main>}>
      <SettingsInner />
    </Suspense>
  );
}
