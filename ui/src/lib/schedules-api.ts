import { authHeaders, backendHttpBase } from "@/lib/config";

export type ScheduleJob = {
  id: string;
  kind: string;
  title: string;
  body: string;
  cron: string | null;
  run_at: number | null;
  enabled: boolean;
  builtin: boolean;
  meta: Record<string, unknown>;
  next_run: number | null;
  created_at: number;
  updated_at: number;
};

async function jsonOrThrow<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try {
      const body = (await res.json()) as { detail?: string | { message?: string } };
      if (typeof body.detail === "string") detail = body.detail;
      else if (body.detail && typeof body.detail === "object" && body.detail.message) {
        detail = body.detail.message;
      }
    } catch {
      /* keep */
    }
    throw new Error(detail);
  }
  return (await res.json()) as T;
}

function jsonHeaders(): HeadersInit {
  return { "Content-Type": "application/json", ...authHeaders() };
}

export function listSchedules() {
  return fetch(`${backendHttpBase()}/api/schedules`, {
    headers: authHeaders(),
  }).then((r) =>
    jsonOrThrow<{ jobs: ScheduleJob[]; scheduler_enabled: boolean }>(r),
  );
}

export function parseSchedule(text: string) {
  return fetch(`${backendHttpBase()}/api/schedules/parse`, {
    method: "POST",
    headers: jsonHeaders(),
    body: JSON.stringify({ text }),
  }).then((r) =>
    jsonOrThrow<{
      kind: string;
      title: string;
      body: string;
      cron: string | null;
      run_at: number | null;
    }>(r),
  );
}

export function createSchedule(payload: {
  text?: string;
  title?: string;
  body?: string;
  cron?: string;
  run_at?: number;
}) {
  return fetch(`${backendHttpBase()}/api/schedules`, {
    method: "POST",
    headers: jsonHeaders(),
    body: JSON.stringify(payload),
  }).then((r) => jsonOrThrow<ScheduleJob>(r));
}

export function patchSchedule(
  id: string,
  payload: { enabled?: boolean; title?: string; body?: string; cron?: string },
) {
  return fetch(`${backendHttpBase()}/api/schedules/${encodeURIComponent(id)}`, {
    method: "PATCH",
    headers: jsonHeaders(),
    body: JSON.stringify(payload),
  }).then((r) => jsonOrThrow<ScheduleJob>(r));
}

export function deleteSchedule(id: string) {
  return fetch(`${backendHttpBase()}/api/schedules/${encodeURIComponent(id)}`, {
    method: "DELETE",
    headers: authHeaders(),
  }).then((r) => jsonOrThrow<{ ok: boolean }>(r));
}

export function triggerSchedule(id: string) {
  return fetch(
    `${backendHttpBase()}/api/schedules/${encodeURIComponent(id)}/trigger`,
    { method: "POST", headers: authHeaders() },
  ).then((r) => jsonOrThrow<{ ok: boolean; id: string }>(r));
}

export type SchedulerStatus = {
  scheduler_enabled: boolean;
  session_id: string;
  now: number;
  last_activity_at: number | null;
  idle_seconds: number | null;
  outreach_idle_hours: number;
  next_eligible_in_seconds: number | null;
  last_outreach_at: number | null;
  outreach_count_today: number;
  outreach_day: string | null;
  proactive_enabled: boolean;
  proactive_llm_ready: boolean;
  unread_inbox: number;
};

export function getSchedulerStatus() {
  return fetch(`${backendHttpBase()}/api/scheduler/status`, {
    headers: authHeaders(),
  }).then((r) => jsonOrThrow<SchedulerStatus>(r));
}
