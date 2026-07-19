"use client";

import { AppNav } from "@/components/AppNav";

export default function SchedulesLayout({
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
          日程
        </h1>
        <p className="mt-1 text-sm text-[var(--ink-soft)]">
          定时提醒、每日问候与主动 Loop 任务。
        </p>
      </header>
      <div>{children}</div>
    </main>
  );
}
