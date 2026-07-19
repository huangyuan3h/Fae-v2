import { backendHttpBase } from "@/lib/config";

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

export function listSchedules() {
  return fetch(`${backendHttpBase()}/api/schedules`).then((r) =>
    jsonOrThrow<{ jobs: ScheduleJob[]; scheduler_enabled: boolean }>(r),
  );
}

export function parseSchedule(text: string) {
  return fetch(`${backendHttpBase()}/api/schedules/parse`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
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
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  }).then((r) => jsonOrThrow<ScheduleJob>(r));
}

export function patchSchedule(
  id: string,
  payload: { enabled?: boolean; title?: string; body?: string; cron?: string },
) {
  return fetch(`${backendHttpBase()}/api/schedules/${encodeURIComponent(id)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  }).then((r) => jsonOrThrow<ScheduleJob>(r));
}

export function deleteSchedule(id: string) {
  return fetch(`${backendHttpBase()}/api/schedules/${encodeURIComponent(id)}`, {
    method: "DELETE",
  }).then((r) => jsonOrThrow<{ ok: boolean }>(r));
}

export function triggerSchedule(id: string) {
  return fetch(
    `${backendHttpBase()}/api/schedules/${encodeURIComponent(id)}/trigger`,
    { method: "POST" },
  ).then((r) => jsonOrThrow<{ ok: boolean; id: string }>(r));
}
