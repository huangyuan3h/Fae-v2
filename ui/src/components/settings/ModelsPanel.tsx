"use client";

import { useCallback, useEffect, useState } from "react";

import { ModelFormModal, type ModelFormValues } from "@/components/settings/ModelFormModal";
import {
  authHeaders,
  backendHttpBase,
  clientAccessToken,
  saveClientAccessToken,
} from "@/lib/config";
import {
  deleteModelProfile,
  getActiveModelId,
  listModelProfiles,
  profileToConfig,
  saveModelProfile,
  setActiveModel,
  type ModelProfile,
} from "@/lib/models";

type CapsLlm = {
  llm?: { server_configured?: boolean };
  auth?: { client_token_required?: boolean };
  status?: { proactive_llm?: string };
};

export function ModelsPanel() {
  const [profiles, setProfiles] = useState<ModelProfile[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<ModelProfile | null>(null);
  const [status, setStatus] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [serverLlm, setServerLlm] = useState<string>("…");
  const [tokenRequired, setTokenRequired] = useState(false);
  const [clientToken, setClientToken] = useState("");

  const refresh = useCallback(() => {
    setProfiles(listModelProfiles());
    setActiveId(getActiveModelId());
  }, []);

  useEffect(() => {
    refresh();
    setClientToken(clientAccessToken());
  }, [refresh]);

  useEffect(() => {
    void fetch(`${backendHttpBase()}/api/capabilities`)
      .then(async (res) => {
        if (!res.ok) {
          setServerLlm("不可用");
          return;
        }
        const data = (await res.json()) as CapsLlm;
        const ok = Boolean(data.llm?.server_configured);
        setServerLlm(
          ok
            ? `已配置（${data.status?.proactive_llm ?? "ok"}）`
            : "未配置 — 请在 Core .env 设置 DASHSCOPE_API_KEY / PROACTIVE_LLM_*",
        );
        setTokenRequired(Boolean(data.auth?.client_token_required));
      })
      .catch(() => setServerLlm("无法连接 Core"));
  }, []);

  const active = profiles.find((p) => p.id === activeId) ?? profiles[0] ?? null;

  const openCreate = () => {
    setEditing(null);
    setModalOpen(true);
  };

  const openEdit = (p: ModelProfile) => {
    setEditing(p);
    setModalOpen(true);
  };

  const onSave = (values: ModelFormValues) => {
    saveModelProfile(
      {
        id: editing?.id,
        name: values.name,
        type: values.type,
        model: values.model,
        baseUrl: values.baseUrl,
        apiKey: values.apiKey,
        thinking: values.thinking,
      },
      { setActive: values.setActive },
    );
    setModalOpen(false);
    setEditing(null);
    refresh();
    setStatus("已保存");
  };

  const onDelete = (id: string) => {
    if (!window.confirm("确定删除这个模型配置？")) return;
    deleteModelProfile(id);
    refresh();
  };

  const onSelect = (id: string) => {
    setActiveModel(id);
    refresh();
  };

  const testConnection = async (profile?: ModelProfile | null) => {
    const target = profile ?? active;
    const cfg = target
      ? profileToConfig(target)
      : { baseUrl: "", apiKey: "", model: "", thinking: "disabled" as const };
    setBusy(true);
    setStatus("测试中…");
    try {
      const res = await fetch(`${backendHttpBase()}/api/test-connection`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...authHeaders() },
        body: JSON.stringify({
          base_url: cfg.baseUrl,
          api_key: cfg.apiKey,
          model: cfg.model,
          thinking: cfg.thinking ?? "disabled",
        }),
      });
      const data = (await res.json().catch(() => ({}))) as {
        status?: string;
        echo?: string;
        detail?: string | { code?: string; message?: string };
      };
      if (!res.ok) {
        const detail =
          typeof data.detail === "string"
            ? data.detail
            : data.detail?.message || `连接失败 (${res.status})`;
        setStatus(detail);
        return;
      }
      setStatus(
        `连接成功 · ${data.echo || target?.model || "server"}` +
          (cfg.apiKey.trim() ? "" : "（服务端 Key）"),
      );
    } catch (e) {
      setStatus(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2
            className="text-xl font-bold text-[var(--ink)]"
            style={{ fontFamily: "var(--font-display)" }}
          >
            模型配置
          </h2>
          <p className="mt-1 text-sm text-[var(--ink-soft)]">
            浏览器 Key 为可选覆盖；常驻 Core 对话默认使用服务端 Key。
          </p>
          <p className="mt-1 text-xs text-[var(--ink-soft)]">
            Server LLM：<span className="font-medium text-[var(--ink)]">{serverLlm}</span>
          </p>
          <p className="mt-1 text-xs text-[var(--ink-soft)]">
            主动 Loop / Telegram 使用服务端{" "}
            <code className="text-[11px]">PROACTIVE_LLM_*</code> /{" "}
            <code className="text-[11px]">DASHSCOPE_API_KEY</code>。
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={refresh}
            className="rounded-full border border-black/15 bg-white/60 px-3 py-2 text-sm"
          >
            刷新
          </button>
          <button
            type="button"
            disabled={busy}
            onClick={() => void testConnection()}
            className="rounded-full border border-black/15 bg-white/60 px-3 py-2 text-sm disabled:opacity-50"
          >
            测试连接
          </button>
          <button
            type="button"
            onClick={openCreate}
            className="rounded-full px-3 py-2 text-sm font-semibold text-white"
            style={{ background: "var(--accent)" }}
          >
            + 添加
          </button>
        </div>
      </div>

      <div className="mt-4 border border-black/8 bg-white/50 px-4 py-3 text-sm text-[var(--ink)]">
        当前使用：{" "}
        {active ? (
          <span className="font-medium">
            {active.name}{" "}
            <span className="text-[var(--ink-soft)]">
              ({active.type} / {active.model})
            </span>
          </span>
        ) : (
          <span className="text-[var(--ink-soft)]">未配置本地模型 — 将使用服务端默认</span>
        )}
      </div>

      {(tokenRequired || clientToken) && (
        <label className="mt-3 grid gap-1 text-xs text-[var(--ink-soft)]">
          Client token（FAE_CLIENT_TOKEN）
          <input
            type="password"
            autoComplete="off"
            className="rounded-md border border-black/10 bg-white/70 px-3 py-2 text-sm"
            value={clientToken}
            onChange={(e) => setClientToken(e.target.value)}
            onBlur={() => saveClientAccessToken(clientToken)}
            placeholder={tokenRequired ? "Core 要求 Bearer token" : "可选"}
          />
        </label>
      )}

      {status && (
        <p className="mt-2 text-sm text-[var(--ink-soft)]" role="status">
          {status}
        </p>
      )}

      <div className="mt-4 overflow-x-auto">
        <table className="w-full min-w-[640px] text-left text-sm">
          <thead>
            <tr className="border-b border-black/10 text-xs text-[var(--ink-soft)]">
              <th className="py-2 pr-2 font-medium"> </th>
              <th className="py-2 pr-3 font-medium">名称</th>
              <th className="py-2 pr-3 font-medium">类型</th>
              <th className="py-2 pr-3 font-medium">模型</th>
              <th className="py-2 pr-3 font-medium">URL</th>
              <th className="py-2 font-medium">操作</th>
            </tr>
          </thead>
          <tbody>
            {profiles.length === 0 && (
              <tr>
                <td colSpan={6} className="py-8 text-center text-[var(--ink-soft)]">
                  还没有本地模型配置；可直接依赖服务端 Key，或点击「添加」。
                </td>
              </tr>
            )}
            {profiles.map((p) => {
              const selected = p.id === activeId;
              return (
                <tr key={p.id} className="border-b border-black/5">
                  <td className="py-3 pr-2">
                    <button
                      type="button"
                      aria-label={selected ? "当前使用" : "设为当前使用"}
                      onClick={() => onSelect(p.id)}
                      className="flex h-5 w-5 items-center justify-center rounded-full border border-black/20"
                      style={{
                        background: selected ? "var(--accent)" : "transparent",
                        color: selected ? "#fff" : "transparent",
                      }}
                    >
                      ✓
                    </button>
                  </td>
                  <td className="py-3 pr-3 font-medium text-[var(--ink)]">
                    {p.name}
                  </td>
                  <td className="py-3 pr-3 text-[var(--ink-soft)]">{p.type}</td>
                  <td className="py-3 pr-3 text-[var(--ink)]">{p.model}</td>
                  <td
                    className="max-w-[220px] truncate py-3 pr-3 text-[var(--ink-soft)]"
                    title={p.baseUrl}
                  >
                    {p.baseUrl}
                  </td>
                  <td className="py-3">
                    <div className="flex gap-2">
                      <button
                        type="button"
                        onClick={() => openEdit(p)}
                        className="text-sm text-[var(--ink-soft)] underline-offset-2 hover:underline"
                      >
                        编辑
                      </button>
                      <button
                        type="button"
                        onClick={() => onDelete(p.id)}
                        className="text-sm text-[var(--danger)] underline-offset-2 hover:underline"
                      >
                        删除
                      </button>
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <ModelFormModal
        open={modalOpen}
        initial={editing}
        onClose={() => {
          setModalOpen(false);
          setEditing(null);
        }}
        onSave={onSave}
      />
    </section>
  );
}
