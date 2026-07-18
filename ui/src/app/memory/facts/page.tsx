"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FormEvent, useState } from "react";

import {
  createFact,
  deleteFact,
  fetchFacts,
  updateFact,
  type MemoryFact,
} from "@/lib/memory-api";

export default function MemoryFactsPage() {
  const qc = useQueryClient();
  const [draft, setDraft] = useState("");
  const [editing, setEditing] = useState<MemoryFact | null>(null);

  const facts = useQuery({
    queryKey: ["memory", "facts"],
    queryFn: () => fetchFacts(),
  });

  const createMut = useMutation({
    mutationFn: (content: string) => createFact(content, ["manual"]),
    onMutate: async (content) => {
      await qc.cancelQueries({ queryKey: ["memory", "facts"] });
      const prev = qc.getQueryData<{ facts: MemoryFact[] }>(["memory", "facts"]);
      const optimistic: MemoryFact = {
        id: `tmp-${Date.now()}`,
        content,
        tags: ["manual"],
        created_at: new Date().toISOString(),
      };
      qc.setQueryData(["memory", "facts"], {
        facts: [optimistic, ...(prev?.facts ?? [])],
      });
      return { prev };
    },
    onError: (_err, _vars, ctx) => {
      if (ctx?.prev) qc.setQueryData(["memory", "facts"], ctx.prev);
    },
    onSettled: () => {
      void qc.invalidateQueries({ queryKey: ["memory", "facts"] });
      void qc.invalidateQueries({ queryKey: ["memory", "timeline"] });
    },
  });

  const updateMut = useMutation({
    mutationFn: ({ id, content }: { id: string; content: string }) =>
      updateFact(id, content, ["manual"]),
    onMutate: async ({ id, content }) => {
      await qc.cancelQueries({ queryKey: ["memory", "facts"] });
      const prev = qc.getQueryData<{ facts: MemoryFact[] }>(["memory", "facts"]);
      qc.setQueryData(["memory", "facts"], {
        facts: (prev?.facts ?? []).map((f) =>
          f.id === id ? { ...f, content } : f,
        ),
      });
      return { prev };
    },
    onError: (_err, _vars, ctx) => {
      if (ctx?.prev) qc.setQueryData(["memory", "facts"], ctx.prev);
    },
    onSettled: () => {
      void qc.invalidateQueries({ queryKey: ["memory", "facts"] });
      setEditing(null);
    },
  });

  const deleteMut = useMutation({
    mutationFn: (id: string) => deleteFact(id),
    onMutate: async (id) => {
      await qc.cancelQueries({ queryKey: ["memory", "facts"] });
      const prev = qc.getQueryData<{ facts: MemoryFact[] }>(["memory", "facts"]);
      qc.setQueryData(["memory", "facts"], {
        facts: (prev?.facts ?? []).filter((f) => f.id !== id),
      });
      return { prev };
    },
    onError: (_err, _vars, ctx) => {
      if (ctx?.prev) qc.setQueryData(["memory", "facts"], ctx.prev);
    },
    onSettled: () => {
      void qc.invalidateQueries({ queryKey: ["memory", "facts"] });
      void qc.invalidateQueries({ queryKey: ["memory", "timeline"] });
    },
  });

  const onCreate = (e: FormEvent) => {
    e.preventDefault();
    const content = draft.trim();
    if (!content) return;
    setDraft("");
    createMut.mutate(content);
  };

  return (
    <section className="space-y-5">
      <form onSubmit={onCreate} className="flex gap-2">
        <input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder="新增事实，例如：用户喜欢手冲咖啡"
          className="min-w-0 flex-1 rounded-full border border-black/10 bg-white/70 px-4 py-3 text-sm outline-none focus:border-[var(--accent)]"
        />
        <button
          type="submit"
          className="rounded-full px-5 py-3 text-sm font-semibold text-white"
          style={{ background: "var(--accent)" }}
        >
          添加
        </button>
      </form>

      {facts.isLoading && (
        <p className="text-sm text-[var(--ink-soft)]">加载事实…</p>
      )}
      {facts.isError && (
        <p className="text-sm text-[var(--danger)]">
          {(facts.error as Error).message}
        </p>
      )}

      <ul className="space-y-3">
        {(facts.data?.facts ?? []).map((fact) => (
          <li
            key={fact.id}
            className="rounded-xl border border-black/10 bg-white/50 px-4 py-3"
          >
            {editing?.id === fact.id ? (
              <form
                className="flex flex-col gap-2 sm:flex-row"
                onSubmit={(e) => {
                  e.preventDefault();
                  const content = editing.content.trim();
                  if (!content) return;
                  updateMut.mutate({ id: fact.id, content });
                }}
              >
                <input
                  value={editing.content}
                  onChange={(e) =>
                    setEditing({ ...editing, content: e.target.value })
                  }
                  className="min-w-0 flex-1 rounded-lg border border-black/10 bg-white px-3 py-2 text-sm"
                />
                <div className="flex gap-2">
                  <button
                    type="submit"
                    className="rounded-full px-3 py-1.5 text-xs font-semibold text-white"
                    style={{ background: "var(--accent)" }}
                  >
                    保存
                  </button>
                  <button
                    type="button"
                    onClick={() => setEditing(null)}
                    className="rounded-full border border-black/10 px-3 py-1.5 text-xs"
                  >
                    取消
                  </button>
                </div>
              </form>
            ) : (
              <>
                <p className="text-sm">{fact.content}</p>
                <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-[var(--ink-soft)]">
                  {(fact.tags || []).map((t) => (
                    <span key={t} className="rounded-full bg-black/5 px-2 py-0.5">
                      {t}
                    </span>
                  ))}
                  <button
                    type="button"
                    className="ml-auto underline-offset-2 hover:underline"
                    onClick={() => setEditing(fact)}
                  >
                    编辑
                  </button>
                  <button
                    type="button"
                    className="text-[var(--danger)] underline-offset-2 hover:underline"
                    onClick={() => deleteMut.mutate(fact.id)}
                  >
                    删除
                  </button>
                </div>
              </>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}
