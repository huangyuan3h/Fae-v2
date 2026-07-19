"use client";

import { AppNav } from "@/components/AppNav";
import { MemoryNav } from "@/components/memory/MemoryNav";

export default function MemoryLayout({
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
          Memory
        </h1>
        <p className="mt-1 text-sm text-[var(--ink-soft)]">
          浏览事实、事件时间线，并语义检索长期记忆。
        </p>
      </header>
      <MemoryNav />
      <div className="mt-6">{children}</div>
    </main>
  );
}
