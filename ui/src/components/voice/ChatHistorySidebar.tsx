"use client";

import { useState } from "react";

import type { ChatSessionSummary } from "@/lib/ws-chat";

type Props = {
  sessions: ChatSessionSummary[];
  activeSessionId: string;
  retentionDays: number;
  onSwitch: (sessionId: string) => void;
  onRename: (sessionId: string, title: string) => void;
  onPin: (sessionId: string, pinned: boolean) => void;
};

function formatRelative(iso: string): string {
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "";
  const diff = Date.now() - then;
  const m = Math.floor(diff / 60000);
  if (m < 1) return "刚刚";
  if (m < 60) return `${m} 分钟前`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h} 小时前`;
  const d = Math.floor(h / 24);
  if (d < 7) return `${d} 天前`;
  return new Date(iso).toLocaleDateString();
}

export function ChatHistorySidebar({
  sessions,
  activeSessionId,
  retentionDays,
  onSwitch,
  onRename,
  onPin,
}: Props) {
  const [editingId, setEditingId] = useState<string | null>(null);
  const [draftTitle, setDraftTitle] = useState("");
  const [newId, setNewId] = useState("");

  const startEdit = (s: ChatSessionSummary) => {
    setEditingId(s.session_id);
    setDraftTitle(s.title);
  };

  const commitEdit = () => {
    if (editingId === null) return;
    onRename(editingId, draftTitle.trim());
    setEditingId(null);
  };

  const handleCreate = (e: React.FormEvent) => {
    e.preventDefault();
    const target = (newId || "").trim();
    if (!target) return;
    onSwitch(target);
    setNewId("");
  };

  return (
    <aside
      className="flex h-full w-full flex-col gap-3 rounded-2xl border border-black/10 bg-white/70 p-3 text-sm shadow-sm backdrop-blur-md"
      data-testid="chat-history-sidebar"
    >
      <header className="flex items-center justify-between">
        <span className="font-semibold text-[var(--ink)]">历史会话</span>
        <span className="text-[10px] text-[var(--ink-soft)]">
          保留 {retentionDays} 天
        </span>
      </header>
      <form className="flex gap-1" onSubmit={handleCreate}>
        <input
          value={newId}
          onChange={(e) => setNewId(e.target.value)}
          placeholder="新建/切换 session id"
          className="min-w-0 flex-1 rounded-md border border-black/10 bg-white px-2 py-1 text-xs outline-none focus:border-[var(--accent)]"
          data-testid="chat-history-new-input"
        />
        <button
          type="submit"
          className="rounded-md bg-[var(--accent)] px-2 py-1 text-xs font-semibold text-white disabled:opacity-50"
          disabled={!newId.trim()}
          data-testid="chat-history-new-submit"
        >
          打开
        </button>
      </form>
      <ul className="flex max-h-[60vh] flex-col gap-1 overflow-y-auto pr-1">
        {sessions.length === 0 && (
          <li className="rounded-md bg-black/[0.04] px-2 py-2 text-xs text-[var(--ink-soft)]">
            暂无历史会话，发送第一条消息后会自动出现在这里。
          </li>
        )}
        {sessions.map((s) => {
          const isActive = s.session_id === activeSessionId;
          const isEditing = editingId === s.session_id;
          return (
            <li
              key={s.session_id}
              className={[
                "rounded-lg border px-2 py-2 text-xs",
                isActive
                  ? "border-[var(--accent)] bg-[var(--accent)]/10"
                  : "border-black/5 bg-white/60",
              ].join(" ")}
              data-testid={`chat-history-row-${s.session_id}`}
            >
              <div className="flex items-start gap-2">
                <button
                  type="button"
                  onClick={() => onSwitch(s.session_id)}
                  className="min-w-0 flex-1 text-left"
                  data-testid={`chat-history-switch-${s.session_id}`}
                >
                  <div className="flex items-center gap-1">
                    {s.pinned && (
                      <span
                        title="已固定（不会自动清理）"
                        className="inline-flex h-4 w-4 items-center justify-center rounded-full bg-amber-400/80 text-[10px] text-white"
                      >
                        📌
                      </span>
                    )}
                    {isEditing ? (
                      <span className="text-[var(--ink-soft)]">重命名中…</span>
                    ) : (
                      <span className="truncate font-medium text-[var(--ink)]">
                        {s.title || s.session_id}
                      </span>
                    )}
                  </div>
                  <div className="mt-0.5 flex items-center gap-1 text-[10px] text-[var(--ink-soft)]">
                    <code className="rounded bg-black/[0.04] px-1">
                      {s.session_id}
                    </code>
                    <span>· {s.turn_count} 条</span>
                    <span>· {formatRelative(s.last_activity_at)}</span>
                  </div>
                </button>
                <div className="flex shrink-0 items-center gap-1">
                  <button
                    type="button"
                    onClick={() => onPin(s.session_id, !s.pinned)}
                    className={[
                      "rounded-md px-1.5 py-0.5 text-[10px]",
                      s.pinned
                        ? "bg-amber-200 text-amber-900"
                        : "bg-black/[0.05] text-[var(--ink-soft)]",
                    ].join(" ")}
                    title={s.pinned ? "取消固定" : "固定（不自动删除）"}
                    data-testid={`chat-history-pin-${s.session_id}`}
                  >
                    {s.pinned ? "已固定" : "固定"}
                  </button>
                  <button
                    type="button"
                    onClick={() => startEdit(s)}
                    className="rounded-md bg-black/[0.05] px-1.5 py-0.5 text-[10px] text-[var(--ink-soft)]"
                    data-testid={`chat-history-rename-${s.session_id}`}
                  >
                    改名
                  </button>
                </div>
              </div>
              {isEditing && (
                <div className="mt-1 flex gap-1">
                  <input
                    value={draftTitle}
                    onChange={(e) => setDraftTitle(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") commitEdit();
                      if (e.key === "Escape") setEditingId(null);
                    }}
                    className="min-w-0 flex-1 rounded-md border border-black/10 bg-white px-2 py-1 text-xs outline-none focus:border-[var(--accent)]"
                    data-testid={`chat-history-rename-input-${s.session_id}`}
                  />
                  <button
                    type="button"
                    onClick={commitEdit}
                    className="rounded-md bg-[var(--accent)] px-2 py-1 text-[10px] font-semibold text-white"
                    data-testid={`chat-history-rename-save-${s.session_id}`}
                  >
                    保存
                  </button>
                  <button
                    type="button"
                    onClick={() => setEditingId(null)}
                    className="rounded-md bg-black/[0.05] px-2 py-1 text-[10px] text-[var(--ink-soft)]"
                  >
                    取消
                  </button>
                </div>
              )}
            </li>
          );
        })}
      </ul>
    </aside>
  );
}