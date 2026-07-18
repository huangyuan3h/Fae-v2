"use client";

import { useQuery } from "@tanstack/react-query";
import { FormEvent, useState } from "react";

import { searchMemory, type SearchHit } from "@/lib/memory-api";

function highlight(text: string, query: string) {
  if (!query.trim()) return text;
  const idx = text.toLowerCase().indexOf(query.toLowerCase());
  if (idx < 0) return text;
  return (
    <>
      {text.slice(0, idx)}
      <mark className="rounded bg-[var(--accent-soft)] px-0.5 not-italic">
        {text.slice(idx, idx + query.length)}
      </mark>
      {text.slice(idx + query.length)}
    </>
  );
}

export function MemorySearch() {
  const [draft, setDraft] = useState("");
  const [query, setQuery] = useState("");

  const result = useQuery({
    queryKey: ["memory", "search", query],
    queryFn: () => searchMemory(query),
    enabled: query.trim().length > 0,
  });

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    setQuery(draft.trim());
  };

  const hits: SearchHit[] = [
    ...(result.data?.facts ?? []),
    ...(result.data?.archival ?? []),
    ...(result.data?.events ?? []),
  ];

  return (
    <section className="space-y-5">
      <form onSubmit={onSubmit} className="flex gap-2">
        <input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder="搜索事实、归档或事件…"
          className="min-w-0 flex-1 rounded-full border border-black/10 bg-white/70 px-4 py-3 text-sm outline-none focus:border-[var(--accent)]"
        />
        <button
          type="submit"
          className="rounded-full px-5 py-3 text-sm font-semibold text-white"
          style={{ background: "var(--accent)" }}
        >
          搜索
        </button>
      </form>

      {result.isFetching && (
        <p className="text-sm text-[var(--ink-soft)]">检索中…</p>
      )}
      {result.isError && (
        <p className="text-sm text-[var(--danger)]">
          {(result.error as Error).message}
        </p>
      )}

      {query && !result.isFetching && hits.length === 0 && (
        <p className="text-sm text-[var(--ink-soft)]">没有命中「{query}」。</p>
      )}

      <ul className="space-y-3">
        {hits.map((hit) => (
          <li
            key={`${hit.source}-${hit.id}`}
            className="rounded-xl border border-black/10 bg-white/50 px-4 py-3"
          >
            <div className="mb-1 flex items-center gap-2 text-xs text-[var(--ink-soft)]">
              <span className="rounded-full bg-black/5 px-2 py-0.5">
                {hit.source}
              </span>
              {hit.kind && <span>{hit.kind}</span>}
            </div>
            <p className="text-sm leading-relaxed">
              {highlight(hit.content, query)}
            </p>
          </li>
        ))}
      </ul>
    </section>
  );
}
