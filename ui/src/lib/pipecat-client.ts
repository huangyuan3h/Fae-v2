/**
 * Voice transport client facade.
 *
 * - browser: Web Speech STT/TTS + `/ws/chat` (default, no Daily key)
 * - daily: Pipecat bot in a Daily room (requires DAILY_API_KEY server-side)
 */

import type { AgentConfig } from "./config";
import { backendHttpBase } from "./config";

export type VoiceSessionMode = "browser" | "daily";

export type VoiceSession = {
  mode: VoiceSessionMode;
  sessionId: string;
  roomUrl?: string | null;
  token?: string | null;
  detail?: string | null;
};

export async function createVoiceSession(opts: {
  preferDaily?: boolean;
  config?: AgentConfig;
}): Promise<VoiceSession> {
  const res = await fetch(`${backendHttpBase()}/api/voice/session`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      prefer_daily: Boolean(opts.preferDaily),
      llm_api_key: opts.config?.apiKey || null,
      llm_base_url: opts.config?.baseUrl || null,
      llm_model: opts.config?.model || null,
    }),
  });
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(`voice session failed: ${res.status} ${detail}`);
  }
  return (await res.json()) as VoiceSession;
}
