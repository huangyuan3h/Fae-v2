import { backendHttpBase } from "@/lib/config";

export type NotificationItem = {
  id: string;
  title: string;
  body: string;
  session_id: string;
  created_at: number;
  read: boolean;
  source: string;
};

export type NotificationPrefs = {
  enabled: boolean;
  quiet_start_hour: number | null;
  quiet_end_hour: number | null;
  desktop_enabled: boolean;
  web_push_enabled: boolean;
  vapid_configured?: boolean;
};

async function jsonOrThrow<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try {
      const body = (await res.json()) as { detail?: string };
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      /* keep */
    }
    throw new Error(detail);
  }
  return (await res.json()) as T;
}

export function listNotifications(unreadOnly = false) {
  const q = unreadOnly ? "?unread_only=true" : "";
  return fetch(`${backendHttpBase()}/api/notifications${q}`).then((r) =>
    jsonOrThrow<{ items: NotificationItem[] }>(r),
  );
}

export function markNotificationsRead(ids?: string[]) {
  return fetch(`${backendHttpBase()}/api/notifications/read`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ids: ids ?? null }),
  }).then((r) => jsonOrThrow<{ ok: boolean; updated: number }>(r));
}

export function getNotificationPrefs() {
  return fetch(`${backendHttpBase()}/api/notifications/prefs`).then((r) =>
    jsonOrThrow<NotificationPrefs>(r),
  );
}

export function putNotificationPrefs(
  prefs: Partial<{
    enabled: boolean;
    quiet_start_hour: number | null;
    quiet_end_hour: number | null;
    desktop_enabled: boolean;
    web_push_enabled: boolean;
    clear_quiet: boolean;
  }>,
) {
  return fetch(`${backendHttpBase()}/api/notifications/prefs`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(prefs),
  }).then((r) => jsonOrThrow<NotificationPrefs>(r));
}

export function getVapidPublicKey() {
  return fetch(`${backendHttpBase()}/api/notifications/vapid-public-key`).then((r) =>
    jsonOrThrow<{ publicKey: string }>(r),
  );
}

export function subscribePush(subscription: PushSubscriptionJSON) {
  return fetch(`${backendHttpBase()}/api/notifications/subscribe`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      endpoint: subscription.endpoint,
      keys: subscription.keys,
    }),
  }).then((r) => jsonOrThrow<{ ok: boolean }>(r));
}

export function unsubscribePush(endpoint: string) {
  return fetch(`${backendHttpBase()}/api/notifications/subscribe`, {
    method: "DELETE",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ endpoint, keys: { p256dh: "-", auth: "-" } }),
  }).then((r) => jsonOrThrow<{ ok: boolean }>(r));
}

function urlBase64ToUint8Array(base64String: string): Uint8Array {
  const padding = "=".repeat((4 - (base64String.length % 4)) % 4);
  const base64 = (base64String + padding).replace(/-/g, "+").replace(/_/g, "/");
  const raw = atob(base64);
  const out = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
  return out;
}

export async function registerPushSubscription(): Promise<boolean> {
  if (typeof window === "undefined" || !("serviceWorker" in navigator)) {
    return false;
  }
  try {
    const { publicKey } = await getVapidPublicKey();
    const reg = await navigator.serviceWorker.register("/sw.js");
    await navigator.serviceWorker.ready;
    const sub = await reg.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: urlBase64ToUint8Array(publicKey) as BufferSource,
    });
    await subscribePush(sub.toJSON());
    return true;
  } catch {
    return false;
  }
}

export function showBrowserNotification(title: string, body: string) {
  if (typeof window === "undefined" || !("Notification" in window)) return;
  if (Notification.permission === "granted") {
    new Notification(title, { body });
  }
}

export async function ensureNotificationPermission(): Promise<NotificationPermission> {
  if (typeof window === "undefined" || !("Notification" in window)) {
    return "denied";
  }
  if (Notification.permission === "default") {
    return Notification.requestPermission();
  }
  return Notification.permission;
}
