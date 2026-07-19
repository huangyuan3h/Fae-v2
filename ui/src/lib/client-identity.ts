/**
 * Stable memory session id for single-user local FAE.
 * Aligns browser chat / Daily memory / proactive cron / consolidate on "default".
 */

export const MEMORY_SESSION_KEY = "fae.memorySessionId";
export const DEFAULT_MEMORY_SESSION_ID = "default";

const UUID_RE =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

function looksLikeEphemeralId(value: string): boolean {
  const v = value.trim();
  if (!v) return true;
  if (v === DEFAULT_MEMORY_SESSION_ID) return false;
  if (UUID_RE.test(v)) return true;
  if (v.startsWith("local-")) return true;
  return false;
}

/** Return the stable memory session id (persisted in localStorage). */
export function getMemorySessionId(): string {
  if (typeof window === "undefined") {
    return DEFAULT_MEMORY_SESSION_ID;
  }
  try {
    const existing = window.localStorage.getItem(MEMORY_SESSION_KEY)?.trim();
    if (existing && !looksLikeEphemeralId(existing)) {
      return existing;
    }
    // Migrate random UUIDs from older builds onto the shared default bucket.
    window.localStorage.setItem(MEMORY_SESSION_KEY, DEFAULT_MEMORY_SESSION_ID);
    return DEFAULT_MEMORY_SESSION_ID;
  } catch {
    return DEFAULT_MEMORY_SESSION_ID;
  }
}
