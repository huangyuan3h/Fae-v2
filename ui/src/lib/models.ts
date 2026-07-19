import type { AgentConfig } from "@/lib/config";
import { DEFAULT_CONFIG, loadConfig, saveConfig } from "@/lib/config";

export type ModelType = "openai" | "ollama";

export type ModelProfile = {
  id: string;
  name: string;
  type: ModelType;
  model: string;
  baseUrl: string;
  apiKey: string;
};

const PROFILES_KEY = "fae.modelProfiles";
const ACTIVE_KEY = "fae.activeModelId";
export const CONFIG_CHANGED_EVENT = "fae:config-changed";

function uid(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return `m-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function notifyConfigChanged(): void {
  if (typeof window === "undefined") return;
  window.dispatchEvent(new Event(CONFIG_CHANGED_EVENT));
}

export function defaultBaseUrl(type: ModelType): string {
  if (type === "ollama") return "http://localhost:11434/v1";
  return (
    process.env.NEXT_PUBLIC_LLM_BASE_URL ??
    "https://dashscope.aliyuncs.com/compatible-mode/v1"
  );
}

export function profileToConfig(profile: ModelProfile): AgentConfig {
  return {
    baseUrl: profile.baseUrl.trim() || defaultBaseUrl(profile.type),
    apiKey: profile.apiKey.trim() || (profile.type === "ollama" ? "ollama" : ""),
    model: profile.model.trim() || DEFAULT_CONFIG.model,
  };
}

/** Migrate legacy single AgentConfig into a profile list once. */
function ensureSeeded(): ModelProfile[] {
  const existing = readProfilesRaw();
  if (existing.length > 0) return existing;

  const legacy = loadConfig();
  const seeded: ModelProfile = {
    id: uid(),
    name: legacy.model || "default",
    type: "openai",
    model: legacy.model || DEFAULT_CONFIG.model,
    baseUrl: legacy.baseUrl || DEFAULT_CONFIG.baseUrl,
    apiKey: legacy.apiKey || "",
  };
  writeProfilesRaw([seeded]);
  localStorage.setItem(ACTIVE_KEY, seeded.id);
  return [seeded];
}

function readProfilesRaw(): ModelProfile[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = localStorage.getItem(PROFILES_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw) as ModelProfile[];
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function writeProfilesRaw(profiles: ModelProfile[]): void {
  localStorage.setItem(PROFILES_KEY, JSON.stringify(profiles));
}

export function listModelProfiles(): ModelProfile[] {
  if (typeof window === "undefined") return [];
  return ensureSeeded();
}

export function getActiveModelId(): string | null {
  if (typeof window === "undefined") return null;
  ensureSeeded();
  return localStorage.getItem(ACTIVE_KEY);
}

export function getActiveProfile(): ModelProfile | null {
  const profiles = listModelProfiles();
  const activeId = getActiveModelId();
  return profiles.find((p) => p.id === activeId) ?? profiles[0] ?? null;
}

/** Sync active profile → AgentConfig used by chat / Daily. */
export function syncActiveConfig(): AgentConfig {
  const profile = getActiveProfile();
  if (!profile) {
    const cfg = loadConfig();
    return cfg;
  }
  const cfg = profileToConfig(profile);
  saveConfig(cfg);
  return cfg;
}

export function saveModelProfile(
  profile: Omit<ModelProfile, "id"> & { id?: string },
  options?: { setActive?: boolean },
): ModelProfile {
  const setActive = options?.setActive ?? false;
  const profiles = listModelProfiles();
  const id = profile.id || uid();
  const next: ModelProfile = {
    id,
    name: profile.name.trim() || profile.model,
    type: profile.type,
    model: profile.model.trim(),
    baseUrl: profile.baseUrl.trim() || defaultBaseUrl(profile.type),
    apiKey: profile.apiKey,
  };
  const idx = profiles.findIndex((p) => p.id === id);
  if (idx >= 0) profiles[idx] = next;
  else profiles.push(next);
  writeProfilesRaw(profiles);
  if (setActive || !getActiveModelId()) {
    localStorage.setItem(ACTIVE_KEY, id);
    syncActiveConfig();
  } else if (getActiveModelId() === id) {
    syncActiveConfig();
  }
  notifyConfigChanged();
  return next;
}

export function deleteModelProfile(id: string): void {
  const profiles = listModelProfiles().filter((p) => p.id !== id);
  writeProfilesRaw(profiles);
  if (getActiveModelId() === id) {
    const fallback = profiles[0];
    if (fallback) {
      localStorage.setItem(ACTIVE_KEY, fallback.id);
      syncActiveConfig();
    } else {
      localStorage.removeItem(ACTIVE_KEY);
    }
  }
  notifyConfigChanged();
}

export function setActiveModel(id: string): void {
  const profiles = listModelProfiles();
  if (!profiles.some((p) => p.id === id)) return;
  localStorage.setItem(ACTIVE_KEY, id);
  syncActiveConfig();
  notifyConfigChanged();
}
