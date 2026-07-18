/**
 * Voice transport client facade.
 *
 * Phase 1 ships a browser Web Speech + WebSocket path so the MVP works
 * without Daily API keys. When DAILY_API_KEY is configured server-side,
 * `createVoiceSession()` can return a Daily room for the future Pipecat path.
 */

import { backendHttpBase } from "./config";

export type VoiceSessionMode = "browser" | "daily";

export type VoiceSession = {
  mode: VoiceSessionMode;
  sessionId: string;
  roomUrl?: string;
  token?: string;
};

export async function createVoiceSession(): Promise<VoiceSession> {
  const res = await fetch(`${backendHttpBase()}/api/voice/session`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({}),
  });
  if (!res.ok) {
    throw new Error(`voice session failed: ${res.status}`);
  }
  return (await res.json()) as VoiceSession;
}
