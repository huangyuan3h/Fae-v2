const PREFER_DAILY_KEY = "fae.preferDaily";
export const PREFER_DAILY_CHANGED_EVENT = "fae:prefer-daily-changed";

export function loadPreferDaily(): boolean {
  if (typeof window === "undefined") return false;
  return localStorage.getItem(PREFER_DAILY_KEY) === "1";
}

export function savePreferDaily(v: boolean): void {
  localStorage.setItem(PREFER_DAILY_KEY, v ? "1" : "0");
  window.dispatchEvent(new Event(PREFER_DAILY_CHANGED_EVENT));
}
