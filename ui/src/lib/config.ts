/** MiniMax-compatible thinking control (auto = omit provider param). */
export type ThinkingMode = "auto" | "disabled" | "adaptive";

export type AgentConfig = {
  baseUrl: string;
  apiKey: string;
  model: string;
  thinking?: ThinkingMode;
};

const STORAGE_KEY = "fae.agentConfig";
const CLIENT_TOKEN_KEY = "fae.clientToken";

export const DEFAULT_CONFIG: AgentConfig = {
  baseUrl:
    process.env.NEXT_PUBLIC_LLM_BASE_URL ??
    "https://dashscope.aliyuncs.com/compatible-mode/v1",
  apiKey: "",
  model: process.env.NEXT_PUBLIC_LLM_MODEL ?? "qwen3-max",
  // Voice UX: skip long hidden <think> by default; Settings can re-enable.
  thinking: "disabled",
};

export function loadConfig(): AgentConfig {
  if (typeof window === "undefined") return DEFAULT_CONFIG;
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return DEFAULT_CONFIG;
    return { ...DEFAULT_CONFIG, ...JSON.parse(raw) };
  } catch {
    return DEFAULT_CONFIG;
  }
}

export function saveConfig(config: AgentConfig): void {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(config));
}

export function backendHttpBase(): string {
  return (
    process.env.NEXT_PUBLIC_API_URL?.replace(/\/$/, "") ||
    "http://localhost:8000"
  );
}

export function backendWsBase(): string {
  const http = backendHttpBase();
  if (http.startsWith("https://")) return http.replace("https://", "wss://");
  return http.replace("http://", "ws://");
}

/** Optional FAE_CLIENT_TOKEN — env or localStorage override. */
export function clientAccessToken(): string {
  if (typeof window !== "undefined") {
    try {
      const local = localStorage.getItem(CLIENT_TOKEN_KEY);
      if (local?.trim()) return local.trim();
    } catch {
      /* ignore */
    }
  }
  return (process.env.NEXT_PUBLIC_FAE_CLIENT_TOKEN || "").trim();
}

export function saveClientAccessToken(token: string): void {
  if (typeof window === "undefined") return;
  const t = token.trim();
  if (!t) localStorage.removeItem(CLIENT_TOKEN_KEY);
  else localStorage.setItem(CLIENT_TOKEN_KEY, t);
}

export function authHeaders(): Record<string, string> {
  const t = clientAccessToken();
  return t ? { Authorization: `Bearer ${t}` } : {};
}
