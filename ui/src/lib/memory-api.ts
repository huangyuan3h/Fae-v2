import { backendHttpBase } from "@/lib/config";

export type MemoryFact = {
  id: string;
  content: string;
  tags: string[];
  session_id?: string | null;
  created_at?: string | null;
};

export type TimelinePoint = {
  id: string;
  kind: string;
  label: string;
  at: string | null;
  tags?: string[];
};

export type SearchHit = {
  id: string;
  content: string;
  tags?: string[];
  source: string;
  kind?: string;
  created_at?: string | null;
};

export type SearchResult = {
  query: string;
  facts: SearchHit[];
  archival: SearchHit[];
  events: SearchHit[];
};

async function jsonFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${backendHttpBase()}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers || {}),
    },
  });
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(detail || `HTTP ${res.status}`);
  }
  return res.json() as Promise<T>;
}

export function fetchFacts(q?: string) {
  const params = new URLSearchParams({ limit: "80" });
  if (q) params.set("q", q);
  return jsonFetch<{ facts: MemoryFact[] }>(`/api/memory/facts?${params}`);
}

export function createFact(content: string, tags: string[] = []) {
  return jsonFetch<MemoryFact>("/api/memory/facts", {
    method: "POST",
    body: JSON.stringify({ content, tags }),
  });
}

export function updateFact(id: string, content: string, tags: string[] = []) {
  return jsonFetch<MemoryFact>(`/api/memory/facts/${id}`, {
    method: "PATCH",
    body: JSON.stringify({ content, tags }),
  });
}

export function deleteFact(id: string) {
  return jsonFetch<{ ok: boolean }>(`/api/memory/facts/${id}`, {
    method: "DELETE",
  });
}

export function searchMemory(q: string) {
  const params = new URLSearchParams({ q, top_k: "12" });
  return jsonFetch<SearchResult>(`/api/memory/search?${params}`);
}

export function fetchTimeline() {
  return jsonFetch<{ points: TimelinePoint[] }>("/api/memory/timeline?limit=40");
}

export function fetchMemoryStats() {
  return jsonFetch<{
    recall_turns: number;
    events: number;
    archival: string;
    sleeptime: string;
  }>("/api/memory/stats");
}
