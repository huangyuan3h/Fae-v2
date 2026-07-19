"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FormEvent, useState } from "react";

import {
  createSchedule,
  deleteSchedule,
  listSchedules,
  patchSchedule,
  triggerSchedule,
  type ScheduleJob,
} from "@/lib/schedules-api";

function formatTs(ts: number | null): string {
  if (ts == null) return "—";
  try {
    return new Date(ts * 1000).toLocaleString();
  } catch {
    return String(ts);
  }
}

export default function SchedulesPage() {
  const qc = useQueryClient();
  const listQ = useQuery({ queryKey: ["schedules"], queryFn: listSchedules });
  const [text, setText] = useState("明早8点提醒吃维生素");
  const [error, setError] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);

  const createM = useMutation({
    mutationFn: () => createSchedule({ text }),
    onSuccess: () => {
      setMsg("已创建");
      setError(null);
      void qc.invalidateQueries({ queryKey: ["schedules"] });
    },
    onError: (e: Error) => setError(e.message),
  });

  const onCreate = (e: FormEvent) => {
    e.preventDefault();
    createM.mutate();
  };

  const jobs = listQ.data?.jobs ?? [];

  return (
    <div className="space-y-8">
      <section>
        <h2 className="mb-2 text-sm font-semibold text-[var(--ink)]">自然语言创建</h2>
        <form onSubmit={onCreate} className="flex flex-col gap-2 sm:flex-row">
          <input
            value={text}
            onChange={(e) => setText(e.target.value)}
            className="min-w-0 flex-1 rounded-full border border-black/10 bg-white/70 px-4 py-3 text-sm outline-none focus:border-[var(--accent)]"
            placeholder="例如：每天9点喝水 / 明天15点开会"
          />
          <button
            type="submit"
            disabled={createM.isPending}
            className="rounded-full px-5 py-3 text-sm font-semibold text-white"
            style={{ background: "var(--accent)" }}
          >
            创建
          </button>
        </form>
        <p className="mt-2 text-xs text-[var(--ink-soft)]">
          调度器：
          {listQ.data?.scheduler_enabled ? "运行中" : "未启用（SCHEDULER_ENABLED）"}
        </p>
        {error && <p className="mt-2 text-sm text-[var(--danger)]">{error}</p>}
        {msg && <p className="mt-2 text-sm text-[var(--accent)]">{msg}</p>}
      </section>

      <section>
        <h2 className="mb-3 text-sm font-semibold text-[var(--ink)]">任务列表</h2>
        {listQ.isLoading && (
          <p className="text-sm text-[var(--ink-soft)]">加载中…</p>
        )}
        {listQ.isError && (
          <p className="text-sm text-[var(--danger)]">
            {(listQ.error as Error).message}
          </p>
        )}
        <ul className="space-y-3">
          {jobs.map((job) => (
            <JobRow
              key={job.id}
              job={job}
              onChanged={() => void qc.invalidateQueries({ queryKey: ["schedules"] })}
            />
          ))}
        </ul>
        {!listQ.isLoading && jobs.length === 0 && (
          <p className="text-sm text-[var(--ink-soft)]">暂无任务</p>
        )}
      </section>
    </div>
  );
}

function JobRow({
  job,
  onChanged,
}: {
  job: ScheduleJob;
  onChanged: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const run = async (fn: () => Promise<unknown>) => {
    setBusy(true);
    setErr(null);
    try {
      await fn();
      onChanged();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <li className="rounded-2xl border border-black/10 bg-white/50 px-4 py-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <p className="font-medium text-[var(--ink)]">
            {job.title}
            {job.builtin && (
              <span className="ml-2 text-xs text-[var(--ink-soft)]">内置</span>
            )}
            {!job.enabled && (
              <span className="ml-2 text-xs text-[var(--danger)]">已暂停</span>
            )}
          </p>
          <p className="mt-1 text-xs text-[var(--ink-soft)]">
            {job.kind}
            {job.cron ? ` · cron ${job.cron}` : ""}
            {job.run_at ? ` · at ${formatTs(job.run_at)}` : ""}
            {" · 下次 "}
            {formatTs(job.next_run)}
          </p>
          {job.body && job.body !== job.title && (
            <p className="mt-1 text-xs text-[var(--ink-soft)]">{job.body}</p>
          )}
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            disabled={busy}
            onClick={() => run(() => triggerSchedule(job.id))}
            className="rounded-full border border-black/10 px-3 py-1 text-xs"
          >
            立即触发
          </button>
          <button
            type="button"
            disabled={busy}
            onClick={() =>
              run(() => patchSchedule(job.id, { enabled: !job.enabled }))
            }
            className="rounded-full border border-black/10 px-3 py-1 text-xs"
          >
            {job.enabled ? "暂停" : "启用"}
          </button>
          <button
            type="button"
            disabled={busy}
            onClick={() => run(() => deleteSchedule(job.id))}
            className="rounded-full border border-black/10 px-3 py-1 text-xs text-[var(--danger)]"
          >
            {job.builtin ? "禁用" : "删除"}
          </button>
        </div>
      </div>
      {err && <p className="mt-2 text-xs text-[var(--danger)]">{err}</p>}
    </li>
  );
}
