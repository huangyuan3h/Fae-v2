"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import {
  ensureNotificationPermission,
  getNotificationPrefs,
  listNotifications,
  markNotificationsRead,
  putNotificationPrefs,
  registerPushSubscription,
} from "@/lib/notifications-api";

export function NotificationsPanel() {
  const qc = useQueryClient();
  const prefsQ = useQuery({
    queryKey: ["notification-prefs"],
    queryFn: getNotificationPrefs,
  });
  const inboxQ = useQuery({
    queryKey: ["notifications"],
    queryFn: () => listNotifications(false),
  });
  const [status, setStatus] = useState<string | null>(null);
  const [quietStart, setQuietStart] = useState("");
  const [quietEnd, setQuietEnd] = useState("");

  useEffect(() => {
    if (!prefsQ.data) return;
    setQuietStart(
      prefsQ.data.quiet_start_hour == null
        ? ""
        : String(prefsQ.data.quiet_start_hour),
    );
    setQuietEnd(
      prefsQ.data.quiet_end_hour == null
        ? ""
        : String(prefsQ.data.quiet_end_hour),
    );
  }, [prefsQ.data]);

  const saveM = useMutation({
    mutationFn: putNotificationPrefs,
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["notification-prefs"] });
      setStatus("已保存");
    },
    onError: (e: Error) => setStatus(e.message),
  });

  const prefs = prefsQ.data;

  const saveQuiet = () => {
    if (quietStart === "" && quietEnd === "") {
      saveM.mutate({ clear_quiet: true });
      return;
    }
    const start = quietStart === "" ? null : Number(quietStart);
    const end = quietEnd === "" ? null : Number(quietEnd);
    if (
      (start != null && (Number.isNaN(start) || start < 0 || start > 23)) ||
      (end != null && (Number.isNaN(end) || end < 0 || end > 23))
    ) {
      setStatus("勿扰小时须为 0–23");
      return;
    }
    saveM.mutate({
      quiet_start_hour: start,
      quiet_end_hour: end,
    });
  };

  return (
    <div className="space-y-8">
      <section className="space-y-3">
        <h2 className="text-sm font-semibold text-[var(--ink)]">通知开关</h2>
        {!prefs && prefsQ.isLoading && (
          <p className="text-sm text-[var(--ink-soft)]">加载中…</p>
        )}
        {prefs && (
          <div className="space-y-3 text-sm">
            <label className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={prefs.enabled}
                onChange={(e) => saveM.mutate({ enabled: e.target.checked })}
              />
              启用通知
            </label>
            <label className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={prefs.desktop_enabled}
                onChange={(e) =>
                  saveM.mutate({ desktop_enabled: e.target.checked })
                }
              />
              桌面通知（本机 osascript / notify-send）
            </label>
            <label className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={prefs.web_push_enabled}
                onChange={(e) =>
                  saveM.mutate({ web_push_enabled: e.target.checked })
                }
              />
              Web Push
            </label>
            <label className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={prefs.proactive_enabled !== false}
                onChange={(e) =>
                  saveM.mutate({ proactive_enabled: e.target.checked })
                }
              />
              主动 Loop（闲时问候 / heartbeat 生成）
            </label>
            <p className="text-xs text-[var(--ink-soft)]">
              主动 Loop 使用服务端{" "}
              <code className="text-[11px]">PROACTIVE_LLM_*</code> /{" "}
              <code className="text-[11px]">DASHSCOPE_API_KEY</code>
              ，不读取浏览器模型 Key。勿扰时段内不会生成主动消息。
            </p>
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-[var(--ink-soft)]">勿扰时段（本地小时）</span>
              <input
                type="number"
                min={0}
                max={23}
                className="w-16 rounded border border-black/10 px-2 py-1"
                value={quietStart}
                placeholder="起"
                onChange={(e) => setQuietStart(e.target.value)}
              />
              <span>—</span>
              <input
                type="number"
                min={0}
                max={23}
                className="w-16 rounded border border-black/10 px-2 py-1"
                value={quietEnd}
                placeholder="止"
                onChange={(e) => setQuietEnd(e.target.value)}
              />
              <button
                type="button"
                className="rounded-full border border-black/10 px-3 py-1 text-xs"
                onClick={saveQuiet}
              >
                保存勿扰
              </button>
              <button
                type="button"
                className="text-xs text-[var(--accent)] underline"
                onClick={() => {
                  setQuietStart("");
                  setQuietEnd("");
                  saveM.mutate({ clear_quiet: true });
                }}
              >
                清除勿扰
              </button>
            </div>
          </div>
        )}
        <div className="flex flex-wrap gap-2 pt-2">
          <button
            type="button"
            className="rounded-full border border-black/10 px-3 py-1.5 text-sm"
            onClick={async () => {
              const p = await ensureNotificationPermission();
              setStatus(`浏览器权限：${p}`);
            }}
          >
            请求浏览器通知权限
          </button>
          <button
            type="button"
            className="rounded-full border border-black/10 px-3 py-1.5 text-sm"
            onClick={async () => {
              const ok = await registerPushSubscription();
              setStatus(
                ok
                  ? "Web Push 已订阅"
                  : "订阅失败（需配置 VAPID 或 HTTPS）",
              );
            }}
          >
            订阅 Web Push
          </button>
        </div>
        {status && (
          <p className="text-xs text-[var(--ink-soft)]">{status}</p>
        )}
        {prefs?.vapid_configured === false && (
          <p className="text-xs text-[var(--ink-soft)]">
            未配置 VAPID_PUBLIC_KEY / VAPID_PRIVATE_KEY，Web Push 不可用。
          </p>
        )}
      </section>

      <section>
        <div className="mb-2 flex items-center justify-between">
          <h2 className="text-sm font-semibold text-[var(--ink)]">收件箱</h2>
          <button
            type="button"
            className="text-xs text-[var(--accent)] underline"
            onClick={async () => {
              await markNotificationsRead();
              void qc.invalidateQueries({ queryKey: ["notifications"] });
            }}
          >
            全部标为已读
          </button>
        </div>
        <ul className="space-y-2">
          {(inboxQ.data?.items ?? []).map((item) => (
            <li
              key={item.id}
              className="rounded-xl border border-black/10 bg-white/50 px-3 py-2 text-sm"
            >
              <p className="font-medium text-[var(--ink)]">
                {item.title}
                {!item.read && (
                  <span className="ml-2 text-xs text-[var(--accent)]">未读</span>
                )}
              </p>
              <p className="text-[var(--ink-soft)]">{item.body}</p>
            </li>
          ))}
        </ul>
        {!inboxQ.isLoading && (inboxQ.data?.items?.length ?? 0) === 0 && (
          <p className="text-sm text-[var(--ink-soft)]">暂无通知</p>
        )}
      </section>
    </div>
  );
}
