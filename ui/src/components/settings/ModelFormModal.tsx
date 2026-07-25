"use client";

import { FormEvent, useState } from "react";

import type { ThinkingMode } from "@/lib/config";
import {
  defaultBaseUrl,
  type ModelProfile,
  type ModelType,
} from "@/lib/models";

export type ModelFormValues = {
  name: string;
  type: ModelType;
  model: string;
  baseUrl: string;
  apiKey: string;
  thinking: ThinkingMode;
  setActive: boolean;
};

type Props = {
  open: boolean;
  initial?: ModelProfile | null;
  onClose: () => void;
  onSave: (values: ModelFormValues) => void;
};

const EMPTY: ModelFormValues = {
  name: "",
  type: "openai",
  model: "gpt-4o-mini",
  baseUrl: "",
  apiKey: "",
  thinking: "disabled",
  setActive: true,
};

export function ModelFormModal({ open, initial, onClose, onSave }: Props) {
  const [form, setForm] = useState<ModelFormValues>(() =>
    initial
      ? {
          name: initial.name,
          type: initial.type,
          model: initial.model,
          baseUrl: initial.baseUrl,
          apiKey: initial.apiKey,
          thinking: initial.thinking ?? "disabled",
          setActive: true,
        }
      : { ...EMPTY, baseUrl: defaultBaseUrl("openai") },
  );

  if (!open) return null;

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    onSave(form);
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 px-4 backdrop-blur-[2px]"
      role="dialog"
      aria-modal="true"
      aria-labelledby="model-form-title"
      onClick={onClose}
    >
      <form
        onSubmit={onSubmit}
        onClick={(e) => e.stopPropagation()}
        className="w-full max-w-md border border-black/10 bg-[var(--bg-0)] p-5 shadow-lg"
      >
        <h2
          id="model-form-title"
          className="text-lg font-bold text-[var(--ink)]"
          style={{ fontFamily: "var(--font-display)" }}
        >
          {initial ? "编辑模型配置" : "添加模型配置"}
        </h2>

        <div className="mt-4 grid gap-3">
          <label className="grid gap-1 text-xs text-[var(--ink-soft)]">
            名称
            <input
              required
              className="rounded-md border border-black/10 bg-white/70 px-3 py-2 text-sm outline-none focus:border-[var(--accent)]"
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
              placeholder="例如 OpenAI Production"
            />
          </label>

          <label className="grid gap-1 text-xs text-[var(--ink-soft)]">
            类型
            <select
              className="rounded-md border border-black/10 bg-white/70 px-3 py-2 text-sm outline-none focus:border-[var(--accent)]"
              value={form.type}
              onChange={(e) => {
                const type = e.target.value as ModelType;
                setForm({
                  ...form,
                  type,
                  baseUrl: form.baseUrl || defaultBaseUrl(type),
                });
              }}
            >
              <option value="openai">OpenAI</option>
              <option value="ollama">Ollama</option>
            </select>
          </label>

          <label className="grid gap-1 text-xs text-[var(--ink-soft)]">
            模型 ID
            <input
              required
              className="rounded-md border border-black/10 bg-white/70 px-3 py-2 text-sm outline-none focus:border-[var(--accent)]"
              value={form.model}
              onChange={(e) => setForm({ ...form, model: e.target.value })}
              placeholder="gpt-4o-mini"
            />
          </label>

          <label className="grid gap-1 text-xs text-[var(--ink-soft)]">
            Thinking（思考强度）
            <select
              className="rounded-md border border-black/10 bg-white/70 px-3 py-2 text-sm outline-none focus:border-[var(--accent)]"
              value={form.thinking}
              onChange={(e) =>
                setForm({
                  ...form,
                  thinking: e.target.value as ThinkingMode,
                })
              }
            >
              <option value="disabled">关闭（推荐语音，更快出字）</option>
              <option value="adaptive">开启 / adaptive（MiniMax-M3）</option>
              <option value="auto">跟随服务商默认</option>
            </select>
            <span className="text-[11px] leading-snug opacity-80">
              MiniMax-M3 默认会开启 thinking；开启后界面会先显示「思考中…」，再吐正式回答。部分 M2.x 无法关闭。
            </span>
          </label>

          <fieldset className="grid gap-3 border border-black/8 bg-white/40 p-3">
            <legend className="px-1 text-xs font-medium text-[var(--ink-soft)]">
              {form.type === "ollama" ? "Ollama 配置" : "OpenAI 配置"}
            </legend>
            <label className="grid gap-1 text-xs text-[var(--ink-soft)]">
              API Key（可选 — 留空则用服务端 Key）
              <input
                type="password"
                autoComplete="off"
                className="rounded-md border border-black/10 bg-white/70 px-3 py-2 text-sm outline-none focus:border-[var(--accent)]"
                value={form.apiKey}
                onChange={(e) => setForm({ ...form, apiKey: e.target.value })}
                placeholder={
                  form.type === "ollama"
                    ? "ollama（可留空）"
                    : "留空 = Core 服务端 Key"
                }
              />
            </label>
            <label className="grid gap-1 text-xs text-[var(--ink-soft)]">
              Base URL（可选）
              <input
                className="rounded-md border border-black/10 bg-white/70 px-3 py-2 text-sm outline-none focus:border-[var(--accent)]"
                value={form.baseUrl}
                onChange={(e) => setForm({ ...form, baseUrl: e.target.value })}
                placeholder={defaultBaseUrl(form.type)}
              />
            </label>
          </fieldset>

          <label className="flex items-center gap-2 text-sm text-[var(--ink)]">
            <input
              type="checkbox"
              checked={form.setActive}
              onChange={(e) => setForm({ ...form, setActive: e.target.checked })}
            />
            设为当前使用
          </label>
        </div>

        <div className="mt-5 flex justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            className="rounded-full border border-black/15 bg-white/60 px-4 py-2 text-sm"
          >
            取消
          </button>
          <button
            type="submit"
            className="rounded-full px-4 py-2 text-sm font-semibold text-white"
            style={{ background: "var(--accent)" }}
          >
            保存
          </button>
        </div>
      </form>
    </div>
  );
}
