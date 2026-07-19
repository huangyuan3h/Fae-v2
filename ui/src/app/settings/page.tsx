"use client";

import Link from "next/link";
import { useState } from "react";

import { ModelsPanel } from "@/components/settings/ModelsPanel";
import { VoicePanel } from "@/components/settings/VoicePanel";

type Tab = "models" | "voice";

export default function SettingsPage() {
  const [tab, setTab] = useState<Tab>("models");

  return (
    <main className="mx-auto min-h-screen w-full max-w-3xl px-4 pb-16 pt-10">
      <header className="mb-6">
        <Link
          href="/"
          className="text-sm text-[var(--ink-soft)] underline-offset-2 hover:underline"
        >
          ← FAE
        </Link>
        <h1
          className="mt-3 text-3xl font-extrabold tracking-tight text-[var(--ink)] md:text-4xl"
          style={{ fontFamily: "var(--font-display)" }}
        >
          Settings
        </h1>
        <p className="mt-1 text-sm text-[var(--ink-soft)]">
          模型与语音选项；密钥仅保存在本机浏览器。
        </p>
      </header>

      <nav className="mb-8 flex flex-wrap gap-2 border-b border-black/10 pb-4">
        {(
          [
            { id: "models" as const, label: "模型" },
            { id: "voice" as const, label: "语音" },
          ] as const
        ).map((item) => {
          const active = tab === item.id;
          return (
            <button
              key={item.id}
              type="button"
              onClick={() => setTab(item.id)}
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
        <Link
          href="/memory"
          className="rounded-full border border-black/10 px-3 py-1.5 text-sm text-[var(--ink-soft)]"
        >
          记忆 →
        </Link>
        <Link
          href="/skills"
          className="rounded-full border border-black/10 px-3 py-1.5 text-sm text-[var(--ink-soft)]"
        >
          Skills →
        </Link>
      </nav>

      {tab === "models" ? <ModelsPanel /> : <VoicePanel />}
    </main>
  );
}
