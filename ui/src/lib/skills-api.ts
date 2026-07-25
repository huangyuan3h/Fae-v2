import { authHeaders, backendHttpBase } from "@/lib/config";

export type SkillListItem = {
  name: string;
  description: string;
  load_strategy: string;
  priority: number;
  enabled: boolean;
  requires_approval: boolean;
  cooldown_seconds: number;
  triggers: string[];
  last_triggered_at: number | null;
};

export type SkillDetail = SkillListItem & {
  body: string;
  raw_markdown: string;
  requires_tools: string[];
  max_context_tokens: number;
};

export type TestTriggerResult = {
  matches: { name: string; score: number }[];
  active: string[];
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

export function listSkills() {
  return fetch(`${backendHttpBase()}/api/skills`, {
    headers: authHeaders(),
  }).then((r) => jsonOrThrow<SkillListItem[]>(r));
}

export function getSkill(name: string) {
  return fetch(`${backendHttpBase()}/api/skills/${encodeURIComponent(name)}`, {
    headers: authHeaders(),
  }).then((r) => jsonOrThrow<SkillDetail>(r));
}

export function putSkill(name: string, markdown: string) {
  return fetch(`${backendHttpBase()}/api/skills/${encodeURIComponent(name)}`, {
    method: "PUT",
    headers: jsonHeaders(),
    body: JSON.stringify({ markdown }),
  }).then((r) => jsonOrThrow<SkillDetail>(r));
}

export function patchSkill(
  name: string,
  patch: { enabled?: boolean; requires_approval?: boolean },
) {
  return fetch(`${backendHttpBase()}/api/skills/${encodeURIComponent(name)}`, {
    method: "PATCH",
    headers: jsonHeaders(),
    body: JSON.stringify(patch),
  }).then((r) => jsonOrThrow<SkillListItem>(r));
}

export function testTrigger(text: string) {
  return fetch(`${backendHttpBase()}/api/skills/test-trigger`, {
    method: "POST",
    headers: jsonHeaders(),
    body: JSON.stringify({ text }),
  }).then((r) => jsonOrThrow<TestTriggerResult>(r));
}
