"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FormEvent, useState } from "react";

import Link from "next/link";

import {
  createSchedule,
  deleteSchedule,
  listSchedules,
  parseSchedule,
  patchSchedule,
  triggerSchedule,
  type ScheduleJob,
} from "@/lib/schedules-api";

type ParsedDraft = {
  kind: string;
  title: string;
  body: string;
  cron: string | null;
  run_at: number | null;
};

function formatTs(ts: number | null): string {
  if (ts == null) return "—";
  try {
    return new Date(ts * 1000).toLocaleString();
  } catch {
    return String(ts);
  }
}

function toLocalInputValue(ts: number): string {
  const d = new Date(ts * 1000);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

export default function SchedulesPage() {
  const qc = useQueryClient();
  const listQ = useQuery({ queryKey: ["schedules"], queryFn: listSchedules });
  const [text, setText] = useState("明早8点提醒吃维生素");
  const [draft, setDraft] = useState<ParsedDraft | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);

  const parseM = useMutation({
    mutationFn: () => parseSchedule(text),
    onSuccess: (parsed) => {
      setDraft({
        kind: parsed.kind,
        title: parsed.title,
        body: parsed.body || text,
        cron: parsed.cron,
        run_at: parsed.run_at,
      });
      setError(null);
      setMsg("已解析，请确认后创建");
    },
    onError: (e: Error) => {
      setDraft(null);
      setError(e.message);
      setMsg(null);
    },
  });

  const createM = useMutation({
    mutationFn: (payload: ParsedDraft) =>
      createSchedule({
        title: payload.title,
        body: payload.body,
        cron: payload.cron ?? undefined,
        run_at: payload.run_at ?? undefined,
      }),
    onSuccess: () => {
      setMsg("已创建 — 到点后会出现在收件箱（Settings → 通知）");
      setError(null);
      setDraft(null);
      void qc.invalidateQueries({ queryKey: ["schedules"] });
      void qc.invalidateQueries({ queryKey: ["scheduler-status"] });
    },
    onError: (e: Error) => setError(e.message),
  });

  const onParse = (e: FormEvent) => {
    e.preventDefault();
    parseM.mutate();
  };

  const onConfirm = () => {
    if (!draft) return;
    createM.mutate(draft);
  };

  const jobs = listQ.data?.jobs ?? [];

  return (
    <div className="space-y-8">
      <section>
        <h2 className="mb-2 text-sm font-semibold text-[var(--ink)]">
          自然语言创建
        </h2>
        <form onSubmit={onParse} className="flex flex-col gap-2 sm:flex-row">
          <input
            value={text}
            onChange={(e) => setText(e.target.value)}
            className="min-w-0 flex-1 rounded-full border border-black/10 bg-white/70 px-4 py-3 text-sm outline-none focus:border-[var(--accent)]"
            placeholder="例如：每天9点喝水 / 明天早上八点开会 / 后天9点提醒"
          />
          <button
            type="submit"
            disabled={parseM.isPending}
            className="rounded-full px-5 py-3 text-sm font-semibold text-white"
            style={{ background: "var(--accent)" }}
          >
            解析
          </button>
        </form>
        <p className="mt-2 text-xs text-[var(--ink-soft)]">
          调度器：
          {listQ.data?.scheduler_enabled ? "运行中" : "未启用（SCHEDULER_ENABLED）"}
          。创建前先确认 kind / 时间 / 标题。
        </p>
        {error && <p className="mt-2 text-sm text-[var(--danger)]">{error}</p>}
        {msg && (
          <p className="mt-2 text-sm text-[var(--accent)]">
            {msg}{" "}
            <Link
              href="/settings?tab=notifications"
              className="underline"
            >
              去收件箱
            </Link>
          </p>
        )}

        {draft && (
          <div className="mt-4 space-y-3 rounded-2xl border border-black/10 bg-white/60 p-4 text-sm">
            <p className="font-medium text-[var(--ink)]">确认日程</p>
            <p className="text-xs text-[var(--ink-soft)]">
              {draft.kind === "cron"
                ? `将按 cron「${draft.cron ?? "—"}」重复提醒`
                : `将在本地时间 ${formatTs(draft.run_at)} 提醒一次`}
            </p>
            <label className="block space-y-1">
              <span className="text-xs text-[var(--ink-soft)]">kind</span>
              <input
                value={draft.kind}
                readOnly
                className="w-full rounded-lg border border-black/10 bg-black/[0.03] px-3 py-2"
              />
            </label>
            <label className="block space-y-1">
              <span className="text-xs text-[var(--ink-soft)]">title</span>
              <input
                value={draft.title}
                onChange={(e) =>
                  setDraft({ ...draft, title: e.target.value })
                }
                className="w-full rounded-lg border border-black/10 px-3 py-2 outline-none focus:border-[var(--accent)]"
              />
            </label>
            <label className="block space-y-1">
              <span className="text-xs text-[var(--ink-soft)]">body</span>
              <input
                value={draft.body}
                onChange={(e) => setDraft({ ...draft, body: e.target.value })}
                className="w-full rounded-lg border border-black/10 px-3 py-2 outline-none focus:border-[var(--accent)]"
              />
            </label>
            {draft.kind === "cron" ? (
              <label className="block space-y-1">
                <span className="text-xs text-[var(--ink-soft)]">cron</span>
                <input
                  value={draft.cron ?? ""}
                  onChange={(e) =>
                    setDraft({ ...draft, cron: e.target.value || null })
                  }
                  className="w-full rounded-lg border border-black/10 px-3 py-2 font-mono text-xs outline-none focus:border-[var(--accent)]"
                />
              </label>
            ) : (
              <label className="block space-y-1">
                <span className="text-xs text-[var(--ink-soft)]">run_at</span>
                <input
                  type="datetime-local"
                  value={
                    draft.run_at != null ? toLocalInputValue(draft.run_at) : ""
                  }
                  onChange={(e) => {
                    const ms = new Date(e.target.value).getTime();
                    setDraft({
                      ...draft,
                      run_at: Number.isNaN(ms) ? null : ms / 1000,
                    });
                  }}
                  className="w-full rounded-lg border border-black/10 px-3 py-2 outline-none focus:border-[var(--accent)]"
                />
                <span className="text-xs text-[var(--ink-soft)]">
                  {formatTs(draft.run_at)}
                </span>
              </label>
            )}
            <div className="flex flex-wrap gap-2 pt-1">
              <button
                type="button"
                disabled={createM.isPending}
                onClick={onConfirm}
                className="rounded-full px-5 py-2 text-sm font-semibold text-white"
                style={{ background: "var(--accent)" }}
              >
                确认创建
              </button>
              <button
                type="button"
                onClick={() => setDraft(null)}
                className="rounded-full border border-black/10 px-4 py-2 text-sm"
              >
                取消
              </button>
            </div>
          </div>
        )}
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
    <li className="rounded-2xl border border-black/10 bg-white/50 px-4 py-3 text-sm">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <p className="font-medium text-[var(--ink)]">
            {job.title}
            {job.builtin && (
              <span className="ml-2 text-xs text-[var(--ink-soft)]">内置</span>
            )}
            {!job.enabled && (
              <span className="ml-2 text-xs text-[var(--danger)]">已禁用</span>
            )}
          </p>
          <p className="text-xs text-[var(--ink-soft)]">
            {job.kind}
            {job.cron ? ` · ${job.cron}` : ""}
            {job.run_at != null ? ` · ${formatTs(job.run_at)}` : ""}
            {job.next_run != null ? ` · next ${formatTs(job.next_run)}` : ""}
          </p>
          {job.body && (
            <p className="mt-1 text-[var(--ink-soft)]">{job.body}</p>
          )}
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            disabled={busy}
            className="rounded-full border border-black/10 px-3 py-1 text-xs"
            onClick={() =>
              void run(() =>
                patchSchedule(job.id, { enabled: !job.enabled }),
              )
            }
          >
            {job.enabled ? "禁用" : "启用"}
          </button>
          <button
            type="button"
            disabled={busy}
            className="rounded-full border border-black/10 px-3 py-1 text-xs"
            onClick={() => void run(() => triggerSchedule(job.id))}
          >
            立即触发
          </button>
          {!job.builtin && (
            <button
              type="button"
              disabled={busy}
              className="rounded-full border border-black/10 px-3 py-1 text-xs text-[var(--danger)]"
              onClick={() => void run(() => deleteSchedule(job.id))}
            >
              删除
            </button>
          )}
        </div>
      </div>
      {err && <p className="mt-2 text-xs text-[var(--danger)]">{err}</p>}
    </li>
  );
}
