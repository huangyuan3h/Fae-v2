"use client";

import { useEffect, useState } from "react";

import {
  fetchPersona,
  updatePersona,
  type PersonaPreset,
} from "@/lib/memory-api";

export function PersonaPanel() {
  const [persona, setPersona] = useState("");
  const [defaultPersona, setDefaultPersona] = useState("");
  const [presets, setPresets] = useState<PersonaPreset[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    fetchPersona()
      .then((p) => {
        if (cancelled) return;
        setPersona(p.persona || "");
        setDefaultPersona(p.default || "");
        setPresets(p.presets || []);
        setError(null);
      })
      .catch((e) => {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : String(e));
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  async function onSave() {
    setSaving(true);
    setSaved(false);
    setError(null);
    try {
      const next = await updatePersona({ persona: persona.trim() });
      setPersona(next.persona || "");
      setDefaultPersona(next.default || "");
      setPresets(next.presets || []);
      setSaved(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  }

  async function onReset() {
    setSaving(true);
    setSaved(false);
    setError(null);
    try {
      const next = await updatePersona({ reset: true });
      setPersona(next.persona || "");
      setDefaultPersona(next.default || "");
      setPresets(next.presets || []);
      setSaved(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  }

  function applyPreset(text: string) {
    setPersona(text);
    setSaved(false);
  }

  if (loading) {
    return <p className="text-sm text-[var(--ink-soft)]">加载人设…</p>;
  }

  return (
    <section className="space-y-5">
      <div>
        <h2
          className="text-lg font-semibold text-[var(--ink)]"
          style={{ fontFamily: "var(--font-display)" }}
        >
          人设
        </h2>
        <p className="mt-1 text-sm text-[var(--ink-soft)]">
          对应记忆里的 persona
          块：决定 FAE 是谁、怎么说话。这是系统身份（人情味、语气、边界），不是关于你的资料——「关于你」请去「重要信息」。
        </p>
      </div>

      {error && (
        <p className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
          {error}
        </p>
      )}

      {presets.length > 0 && (
        <div className="space-y-2">
          <p className="text-sm text-[var(--ink-soft)]">一键预设（写入编辑框，需再保存）</p>
          <div className="flex flex-wrap gap-2">
            {presets.map((p) => (
              <button
                key={p.id}
                type="button"
                title={p.description}
                onClick={() => applyPreset(p.text)}
                className="rounded-md border border-black/10 bg-white px-3 py-1.5 text-sm text-[var(--ink)] transition hover:border-[var(--accent)]"
              >
                {p.label}
              </button>
            ))}
          </div>
        </div>
      )}

      <label className="block space-y-1.5">
        <span className="text-sm text-[var(--ink-soft)]">persona（英文或中英均可）</span>
        <textarea
          value={persona}
          onChange={(e) => {
            setPersona(e.target.value);
            setSaved(false);
          }}
          rows={12}
          placeholder={
            defaultPersona ||
            "例如：You are FAE, a warm companion. Speak gently and check in on how I am doing…"
          }
          className="w-full resize-y rounded-md border border-black/10 bg-white px-3 py-2 font-mono text-sm leading-relaxed text-[var(--ink)] outline-none focus:border-[var(--accent)]"
        />
      </label>

      <div className="flex flex-wrap items-center gap-3">
        <button
          type="button"
          onClick={() => void onSave()}
          disabled={saving || !persona.trim()}
          className="rounded-md px-4 py-2 text-sm text-white disabled:opacity-60"
          style={{ background: "var(--accent)" }}
        >
          {saving ? "保存中…" : "保存"}
        </button>
        <button
          type="button"
          onClick={() => void onReset()}
          disabled={saving}
          className="rounded-md border border-black/10 bg-white px-4 py-2 text-sm text-[var(--ink)] disabled:opacity-60"
        >
          恢复默认
        </button>
        {saved && (
          <span className="text-sm text-[var(--ink-soft)]">已保存，下一轮对话生效</span>
        )}
      </div>
    </section>
  );
}
