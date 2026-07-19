"use client";

import { useEffect, useState } from "react";

import {
  fetchProfile,
  updateProfile,
  type UserProfile,
} from "@/lib/memory-api";

const TZ_SUGGESTIONS = [
  "Asia/Shanghai",
  "Asia/Hong_Kong",
  "Asia/Tokyo",
  "America/New_York",
  "America/Los_Angeles",
  "Europe/London",
  "UTC",
];

export function ProfilePanel() {
  const [profile, setProfile] = useState<UserProfile | null>(null);
  const [displayName, setDisplayName] = useState("");
  const [city, setCity] = useState("");
  const [timezone, setTimezone] = useState("");
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
        setDisplayName(p.display_name || "");
        setCity(p.city || "");
        setTimezone(p.timezone || "");
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
      const next = await updateProfile({
        display_name: displayName.trim() || undefined,
        city: city.trim() || undefined,
        timezone: timezone.trim() || undefined,
      });
      setProfile(next);
      setDisplayName(next.display_name || "");
      setCity(next.city || "");
      setTimezone(next.timezone || "");
      setSaved(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  }

  if (loading) {
    return <p className="text-sm text-[var(--ink-soft)]">加载个人资料…</p>;
  }

  return (
    <section className="space-y-5">
      <div>
        <h2
          className="text-lg font-semibold text-[var(--ink)]"
          style={{ fontFamily: "var(--font-display)" }}
        >
          个人资料
        </h2>
        <p className="mt-1 text-sm text-[var(--ink-soft)]">
          城市与时区会注入对话上下文；问天气时优先使用这里的城市。
        </p>
      </div>

      {error && (
        <p className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
          {error}
        </p>
      )}

      <label className="block space-y-1.5">
        <span className="text-sm text-[var(--ink-soft)]">显示名</span>
        <input
          value={displayName}
          onChange={(e) => setDisplayName(e.target.value)}
          placeholder="例如：小明"
          className="w-full rounded-md border border-black/10 bg-white px-3 py-2 text-sm text-[var(--ink)] outline-none focus:border-[var(--accent)]"
        />
      </label>

      <label className="block space-y-1.5">
        <span className="text-sm text-[var(--ink-soft)]">默认城市</span>
        <input
          value={city}
          onChange={(e) => setCity(e.target.value)}
          placeholder="例如：北京 / Shanghai"
          className="w-full rounded-md border border-black/10 bg-white px-3 py-2 text-sm text-[var(--ink)] outline-none focus:border-[var(--accent)]"
        />
      </label>

      <label className="block space-y-1.5">
        <span className="text-sm text-[var(--ink-soft)]">时区</span>
        <input
          list="fae-tz-list"
          value={timezone}
          onChange={(e) => setTimezone(e.target.value)}
          placeholder="例如：Asia/Shanghai"
          className="w-full rounded-md border border-black/10 bg-white px-3 py-2 text-sm text-[var(--ink)] outline-none focus:border-[var(--accent)]"
        />
        <datalist id="fae-tz-list">
          {TZ_SUGGESTIONS.map((tz) => (
            <option key={tz} value={tz} />
          ))}
        </datalist>
      </label>

      <div className="flex items-center gap-3">
        <button
          type="button"
          onClick={() => void onSave()}
          disabled={saving}
          className="rounded-md px-4 py-2 text-sm text-white disabled:opacity-60"
          style={{ background: "var(--accent)" }}
        >
          {saving ? "保存中…" : "保存"}
        </button>
        {saved && (
          <span className="text-sm text-[var(--ink-soft)]">已保存</span>
        )}
      </div>

      {profile?.human ? (
        <details className="text-sm text-[var(--ink-soft)]">
          <summary className="cursor-pointer">查看 human 记忆块</summary>
          <pre className="mt-2 whitespace-pre-wrap rounded-md border border-black/5 bg-black/[0.03] p-3 text-xs">
            {profile.human}
          </pre>
        </details>
      ) : null}
    </section>
  );
}
