"use client";

import { MemoryNav } from "@/components/memory/MemoryNav";
import { QueryProvider } from "@/providers/QueryProvider";

export default function MemoryLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <QueryProvider>
      <main className="mx-auto min-h-screen w-full max-w-3xl px-4 pb-16 pt-10">
        <header className="mb-6">
          <h1
            className="text-3xl font-extrabold tracking-tight text-[var(--ink)] md:text-4xl"
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
    </QueryProvider>
  );
}
