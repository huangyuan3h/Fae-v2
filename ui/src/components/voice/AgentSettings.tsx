"use client";

import type { AgentConfig } from "@/lib/config";

type Props = {
  config: AgentConfig;
  onChange: (next: AgentConfig) => void;
};

export function AgentSettings({ config, onChange }: Props) {
  return (
    <div className="mx-auto grid w-full max-w-xl gap-2 px-4 pb-8 pt-2">
      <label className="grid gap-1 text-xs text-[var(--ink-soft)]">
        API Base URL
        <input
          className="rounded-md border border-black/10 bg-white/70 px-3 py-2 text-sm text-[var(--ink)] outline-none focus:border-[var(--accent)]"
          value={config.baseUrl}
          onChange={(e) => onChange({ ...config, baseUrl: e.target.value })}
        />
      </label>
      <label className="grid gap-1 text-xs text-[var(--ink-soft)]">
        API Key
        <input
          type="password"
          autoComplete="off"
          className="rounded-md border border-black/10 bg-white/70 px-3 py-2 text-sm text-[var(--ink)] outline-none focus:border-[var(--accent)]"
          value={config.apiKey}
          onChange={(e) => onChange({ ...config, apiKey: e.target.value })}
          placeholder="sk-…"
        />
      </label>
      <label className="grid gap-1 text-xs text-[var(--ink-soft)]">
        Model
        <input
          className="rounded-md border border-black/10 bg-white/70 px-3 py-2 text-sm text-[var(--ink)] outline-none focus:border-[var(--accent)]"
          value={config.model}
          onChange={(e) => onChange({ ...config, model: e.target.value })}
        />
      </label>
    </div>
  );
}
