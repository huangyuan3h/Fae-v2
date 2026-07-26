/**
 * Thin re-export — chat transport lives in @fae/client (P7 SDK).
 */
import {
  buildWsChatUrl,
  ChatAbortedError,
  type ChatHistory,
  type ChatSessionsResponse,
  type ChatSessionSummary,
  WsChatClient as SdkWsChatClient,
  type LlmConfigInput,
  type NotifyHandler,
  type StreamHandlers,
  type SubagentHandler,
  type TokenUsage,
  type ToolHandler,
  type WsServerMessage,
} from "@fae/client";

import type { AgentConfig } from "./config";
import { authHeaders, backendHttpBase, clientAccessToken } from "./config";

export type {
  ChatHistory,
  ChatSessionsResponse,
  ChatSessionSummary,
  NotifyHandler,
  StreamHandlers,
  SubagentHandler,
  TokenUsage,
  ToolHandler,
  WsServerMessage,
};

export { ChatAbortedError };

export class WsChatClient {
  private inner: SdkWsChatClient;

  constructor(url?: string) {
    this.inner = new SdkWsChatClient(
      url ?? buildWsChatUrl(backendHttpBase(), clientAccessToken()),
    );
  }

  setNotificationHandler(handler: NotifyHandler | null) {
    this.inner.setNotificationHandler(handler);
  }

  connect(): Promise<void> {
    return this.inner.connect();
  }

  async chat(
    text: string,
    config: AgentConfig,
    handlers: StreamHandlers,
    sessionId?: string | null,
  ): Promise<void> {
    const llm: LlmConfigInput = {
      baseUrl: config.baseUrl,
      apiKey: config.apiKey,
      model: config.model,
      thinking: config.thinking,
    };
    return this.inner.chat(text, llm, handlers, sessionId);
  }

  cancel(): void {
    this.inner.cancel();
  }

  close(): void {
    this.inner.close();
  }
}

async function jsonFetch<T>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const res = await fetch(`${backendHttpBase()}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init.headers ?? {}),
      ...authHeaders(),
    },
  });
  if (!res.ok) {
    throw new Error(`chat history failed: HTTP ${res.status}`);
  }
  return (await res.json()) as T;
}

export async function fetchChatHistory(
  sessionId: string,
  opts: { limit?: number; before?: string } = {},
): Promise<ChatHistory> {
  const params = new URLSearchParams({ session_id: sessionId });
  if (opts.limit && opts.limit > 0) {
    params.set("limit", String(opts.limit));
  }
  if (opts.before) {
    params.set("before", opts.before);
  }
  return jsonFetch<ChatHistory>(`/api/chat/history?${params}`);
}

export async function fetchChatSessions(): Promise<ChatSessionsResponse> {
  return jsonFetch<ChatSessionsResponse>(`/api/chat/sessions`);
}

export async function updateChatSessionTitle(
  sessionId: string,
  title: string,
): Promise<ChatSessionSummary> {
  return jsonFetch<ChatSessionSummary>(
    `/api/chat/sessions/${encodeURIComponent(sessionId)}`,
    {
      method: "PATCH",
      body: JSON.stringify({ title }),
    },
  );
}

export async function setChatSessionPinned(
  sessionId: string,
  pinned: boolean,
): Promise<ChatSessionSummary> {
  return jsonFetch<ChatSessionSummary>(
    `/api/chat/sessions/${encodeURIComponent(sessionId)}/pin`,
    {
      method: "POST",
      body: JSON.stringify({ pinned }),
    },
  );
}
