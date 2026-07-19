"use client";

import Link from "next/link";
import { QueryProvider } from "@/providers/QueryProvider";

export default function SkillsLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <QueryProvider>
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
            Skills
          </h1>
          <p className="mt-1 text-sm text-[var(--ink-soft)]">
            Markdown 剧本：按场景触发，注入到对话 prompt。
          </p>
          <nav className="mt-4 flex flex-wrap gap-3 text-sm">
            <Link
              href="/memory"
              className="text-[var(--accent)] underline-offset-2 hover:underline"
            >
              记忆
            </Link>
            <Link
              href="/settings"
              className="text-[var(--accent)] underline-offset-2 hover:underline"
            >
              Settings
            </Link>
          </nav>
        </header>
        <div>{children}</div>
      </main>
    </QueryProvider>
  );
}
