"use client";

import { useEffect, useState } from "react";

import {
  fetchProfile,
  updateProfile,
  type UserProfile,
} from "@/lib/memory-api";

export function ProfilePanel() {
  const [profile, setProfile] = useState<UserProfile | null>(null);
  const [human, setHuman] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    fetchProfile()
      .then((p) => {
        if (cancelled) return;
        setProfile(p);
        setHuman(p.human || "");
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
      const next = await updateProfile({ human: human.trim() });
      setProfile(next);
      setHuman(next.human || "");
      setSaved(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  }

  if (loading) {
    return <p className="text-sm text-[var(--ink-soft)]">加载重要信息…</p>;
  }

  const hints = [
    profile?.display_name ? `姓名：${profile.display_name}` : null,
    profile?.city ? `城市：${profile.city}` : null,
    profile?.timezone ? `时区：${profile.timezone}` : null,
  ].filter(Boolean);

  return (
    <section className="space-y-5">
      <div>
        <h2
          className="text-lg font-semibold text-[var(--ink)]"
          style={{ fontFamily: "var(--font-display)" }}
        >
          重要信息
        </h2>
        <p className="mt-1 text-sm text-[var(--ink-soft)]">
          对应记忆里的 human
          块：关于你的姓名、常住城市、偏好等。FAE 怎么说话请去「人设」。对话里说「我住在北京」或更正「不对，是上海」也会自动更新；天气等能力会从这里读取。
        </p>
      </div>

      {error && (
        <p className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
          {error}
        </p>
      )}

      {hints.length > 0 && (
        <p className="text-sm text-[var(--ink-soft)]">
          已识别：{hints.join(" · ")}
        </p>
      )}

      <label className="block space-y-1.5">
        <span className="text-sm text-[var(--ink-soft)]">human 记忆（非结构化）</span>
        <textarea
          value={human}
          onChange={(e) => setHuman(e.target.value)}
          rows={10}
          placeholder={
            "例如：\nName: 小明\nLives in 北京.\n喜欢简洁回答，中英都可。"
          }
          className="w-full resize-y rounded-md border border-black/10 bg-white px-3 py-2 font-mono text-sm leading-relaxed text-[var(--ink)] outline-none focus:border-[var(--accent)]"
        />
      </label>

      <div className="flex items-center gap-3">
        <button
          type="button"
          onClick={() => void onSave()}
          disabled={saving || !human.trim()}
          className="rounded-md px-4 py-2 text-sm text-white disabled:opacity-60"
          style={{ background: "var(--accent)" }}
        >
          {saving ? "保存中…" : "保存"}
        </button>
        {saved && (
          <span className="text-sm text-[var(--ink-soft)]">已保存</span>
        )}
      </div>
    </section>
  );
}
