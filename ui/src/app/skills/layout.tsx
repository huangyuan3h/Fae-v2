"use client";

import { AppNav } from "@/components/AppNav";

export default function SkillsLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <main className="mx-auto min-h-screen w-full max-w-3xl px-4 pb-16 pt-10">
      <header className="mb-6">
        <AppNav className="mb-4 justify-start" />
        <h1
          className="mt-3 text-3xl font-extrabold tracking-tight text-[var(--ink)] md:text-4xl"
          style={{ fontFamily: "var(--font-display)" }}
        >
          Skills
        </h1>
        <p className="mt-1 text-sm text-[var(--ink-soft)]">
          Markdown 剧本：按场景触发，注入到对话 prompt。
        </p>
      </header>
      <div>{children}</div>
    </main>
  );
}
