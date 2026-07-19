/** MiniMax-compatible thinking control (auto = omit provider param). */
export type ThinkingMode = "auto" | "disabled" | "adaptive";

export type AgentConfig = {
  baseUrl: string;
  apiKey: string;
  model: string;
  thinking?: ThinkingMode;
};

const STORAGE_KEY = "fae.agentConfig";

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
