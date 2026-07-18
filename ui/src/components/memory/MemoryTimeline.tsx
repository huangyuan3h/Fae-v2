"use client";

import { useQuery } from "@tanstack/react-query";
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { fetchMemoryStats, fetchTimeline } from "@/lib/memory-api";

function dayKey(iso: string | null): string {
  if (!iso) return "unknown";
  return iso.slice(0, 10);
}

export function MemoryTimeline() {
  const timeline = useQuery({
    queryKey: ["memory", "timeline"],
    queryFn: fetchTimeline,
  });
  const stats = useQuery({
    queryKey: ["memory", "stats"],
    queryFn: fetchMemoryStats,
  });

  const points = timeline.data?.points ?? [];
  const byDay = new Map<string, { day: string; facts: number; events: number }>();
  for (const p of points) {
    const day = dayKey(p.at);
    const row = byDay.get(day) ?? { day, facts: 0, events: 0 };
    if (p.kind === "event") row.events += 1;
    else row.facts += 1;
    byDay.set(day, row);
  }
  const chartData = [...byDay.values()].sort((a, b) => a.day.localeCompare(b.day));

  return (
    <section className="space-y-6">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Stat label="Recall" value={stats.data?.recall_turns ?? "—"} />
        <Stat label="Events" value={stats.data?.events ?? "—"} />
        <Stat label="Archival" value={stats.data?.archival ?? "—"} />
        <Stat label="Sleeptime" value={stats.data?.sleeptime ?? "—"} />
      </div>

      <div className="h-64 w-full rounded-2xl border border-black/10 bg-white/50 p-3">
        {timeline.isLoading ? (
          <p className="p-4 text-sm text-[var(--ink-soft)]">加载时间线…</p>
        ) : chartData.length === 0 ? (
          <p className="p-4 text-sm text-[var(--ink-soft)]">
            还没有记忆点。先在主页聊几句（例如「我喜欢手冲咖啡」）。
          </p>
        ) : (
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={chartData}>
              <CartesianGrid stroke="rgba(0,0,0,0.06)" vertical={false} />
              <XAxis dataKey="day" tick={{ fontSize: 11 }} />
              <YAxis allowDecimals={false} tick={{ fontSize: 11 }} width={28} />
              <Tooltip />
              <Line
                type="monotone"
                dataKey="facts"
                name="事实"
                stroke="var(--accent)"
                strokeWidth={2}
                dot={false}
              />
              <Line
                type="monotone"
                dataKey="events"
                name="事件"
                stroke="#1f4e79"
                strokeWidth={2}
                dot={false}
              />
            </LineChart>
          </ResponsiveContainer>
        )}
      </div>

      <ol className="space-y-2">
        {points.slice(0, 24).map((p) => (
          <li
            key={`${p.kind}-${p.id}`}
            className="flex gap-3 border-b border-black/5 py-2 text-sm"
          >
            <time className="w-28 shrink-0 text-[var(--ink-soft)]">
              {p.at ? p.at.slice(0, 16).replace("T", " ") : "—"}
            </time>
            <span
              className="w-14 shrink-0 rounded-full px-2 py-0.5 text-center text-xs"
              style={{
                background: p.kind === "event" ? "#dfe8ff" : "var(--accent-soft)",
              }}
            >
              {p.kind}
            </span>
            <span className="min-w-0 flex-1">{p.label}</span>
          </li>
        ))}
      </ol>
    </section>
  );
}

function Stat({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="rounded-xl border border-black/10 bg-white/40 px-3 py-2">
      <div className="text-xs text-[var(--ink-soft)]">{label}</div>
      <div
        className="mt-1 text-lg font-semibold"
        style={{ fontFamily: "var(--font-display)" }}
      >
        {value}
      </div>
    </div>
  );
}
