/**
 * Voice transport client facade.
 *
 * - browser: Web Speech STT + `/ws/chat` + local TTS via `/api/tts/speak` (default)
 * - daily: Pipecat bot in a Daily WebRTC room (requires DAILY_API_KEY; not local TTS)
 */

import type { AgentConfig } from "./config";
import { authHeaders, backendHttpBase } from "./config";
import { formatNetworkError } from "./network-error";

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
  /** Stable memory bucket (defaults to client identity "default"). */
  memorySessionId?: string | null;
}): Promise<VoiceSession> {
  let res: Response;
  try {
    res = await fetch(`${backendHttpBase()}/api/voice/session`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...authHeaders() },
      body: JSON.stringify({
        prefer_daily: Boolean(opts.preferDaily),
        llm_api_key: opts.config?.apiKey || null,
        llm_base_url: opts.config?.baseUrl || null,
        llm_model: opts.config?.model || null,
        memory_session_id: opts.memorySessionId || null,
      }),
    });
  } catch (err) {
    throw new Error(formatNetworkError(err, "/api/voice/session"));
  }
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(`voice session failed: ${res.status} ${detail}`);
  }
  return (await res.json()) as VoiceSession;
}
