/**
 * Thin re-export — chat transport lives in @fae/client (P7 SDK).
 */
import {
  buildWsChatUrl,
  ChatAbortedError,
  type ApprovalRequestMsg,
  type ChatHistory,
  type ChatSessionsResponse,
  type ChatSessionSummary,
  WsChatClient as SdkWsChatClient,
  type AgentTraceEvent,
  type LlmConfigInput,
  type NotifyHandler,
  type StreamHandlers,
  type SubagentHandler,
  type TokenUsage,
  type ToolAuditEvent,
  type ToolHandler,
  type TurnStartedHandler,
  type WsServerMessage,
} from "@fae/client";

import type { AgentConfig } from "./config";
import { authHeaders, backendHttpBase, clientAccessToken } from "./config";

export type {
  ApprovalRequestMsg,
  ChatHistory,
  ChatSessionsResponse,
  ChatSessionSummary,
  AgentTraceEvent,
  NotifyHandler,
  StreamHandlers,
  SubagentHandler,
  TokenUsage,
  ToolAuditEvent,
  ToolHandler,
  TurnStartedHandler,
  WsServerMessage,
};

export { ChatAbortedError };

/* Approval: types & SDK methods live in @fae/client (P7 SDK). */
import type {
  ApprovalDecisionInput,
  ApprovalRequestHandler,
  ApprovalResolvedHandler,
} from "@fae/client";

export type {
  ApprovalDecisionInput,
  ApprovalRequestHandler,
  ApprovalResolvedHandler,
};

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

  setApprovalRequestHandler(handler: ApprovalRequestHandler | null) {
    this.inner.setApprovalRequestHandler(handler);
  }

  setApprovalResolvedHandler(handler: ApprovalResolvedHandler | null) {
    this.inner.setApprovalResolvedHandler(handler);
  }

  setTurnStartedHandler(handler: TurnStartedHandler | null) {
    this.inner.setTurnStartedHandler(handler);
  }

  sendApprovalDecision(approvalId: string, decision: ApprovalDecisionInput): boolean {
    return this.inner.sendApprovalDecision(approvalId, decision);
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

export async function fetchAgentTrace(
  opts: {
    sessionId?: string;
    turnId?: string;
    kind?: string;
    limit?: number;
  } = {},
): Promise<AgentTraceEvent[]> {
  const params = new URLSearchParams();
  if (opts.sessionId) params.set("session_id", opts.sessionId);
  if (opts.turnId) params.set("turn_id", opts.turnId);
  if (opts.kind) params.set("kind", opts.kind);
  if (opts.limit) params.set("limit", String(opts.limit));
  const qs = params.toString();
  return jsonFetch<AgentTraceEvent[]>(
    `/api/agent-trace${qs ? "?" + qs : ""}`,
  );
}

export async function fetchToolAudit(
  opts: {
    sessionId?: string;
    toolName?: string;
    channel?: string;
    phase?: string;
    turnId?: string;
    limit?: number;
  } = {},
): Promise<ToolAuditEvent[]> {
  const params = new URLSearchParams();
  if (opts.sessionId) params.set("session_id", opts.sessionId);
  if (opts.toolName) params.set("tool_name", opts.toolName);
  if (opts.channel) params.set("channel", opts.channel);
  if (opts.phase) params.set("phase", opts.phase);
  if (opts.turnId) params.set("turn_id", opts.turnId);
  if (opts.limit) params.set("limit", String(opts.limit));
  const qs = params.toString();
  return jsonFetch<ToolAuditEvent[]>(
    `/api/tool-audit${qs ? "?" + qs : ""}`,
  );
}
