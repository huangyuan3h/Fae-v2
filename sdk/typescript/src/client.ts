import type {
  ApprovalDecisionInput,
  ApprovalListResponse,
  ApprovalRequestMsg,
  ChatHistory,
  ChatSessionsResponse,
  ChatSessionSummary,
  CreateClientOptions,
  FaeCapabilities,
  FaeReady,
  LlmConfigInput,
  NotifyHandler,
  SessionPolicies,
  StreamHandlers,
  ToolSpecSummary,
} from "./types";
import { buildWsChatUrl, WsChatClient } from "./ws-chat";

export class FaeClient {
  readonly baseUrl: string;
  readonly token: string;
  private ws: WsChatClient;

  constructor(opts: CreateClientOptions) {
    this.baseUrl = opts.baseUrl.replace(/\/$/, "");
    this.token = (opts.token || "").trim();
    this.ws = new WsChatClient(buildWsChatUrl(this.baseUrl, this.token));
  }

  /** Open (or reuse) the streaming chat WebSocket. */
  connect(): Promise<void> {
    return this.ws.connect();
  }

  setNotificationHandler(handler: NotifyHandler | null): void {
    this.ws.setNotificationHandler(handler);
  }

  /** Stream one user turn over `/ws/chat`. Empty apiKey uses server LLM. */
  chatStream(
    text: string,
    config: LlmConfigInput,
    handlers: StreamHandlers,
    sessionId?: string | null,
  ): Promise<void> {
    return this.ws.chat(text, config, handlers, sessionId);
  }

  cancelChat(): void {
    this.ws.cancel();
  }

  /** Send an approval decision over the existing WS connection (preferred). */
  sendApprovalDecision(
    approvalId: string,
    decision: ApprovalDecisionInput,
  ): void {
    this.ws.sendApprovalDecision(approvalId, decision);
  }

  close(): void {
    this.ws.close();
  }

  private authHeaders(): Record<string, string> {
    return this.token ? { Authorization: `Bearer ${this.token}` } : {};
  }

  async listChatHistory(
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
    const res = await fetch(
      `${this.baseUrl}/api/chat/history?${params}`,
      { headers: this.authHeaders() },
    );
    if (!res.ok) {
      throw new Error(`chat history failed: HTTP ${res.status}`);
    }
    return (await res.json()) as ChatHistory;
  }

  async listChatSessions(): Promise<ChatSessionsResponse> {
    const res = await fetch(
      `${this.baseUrl}/api/chat/sessions`,
      { headers: this.authHeaders() },
    );
    if (!res.ok) {
      throw new Error(`chat sessions failed: HTTP ${res.status}`);
    }
    return (await res.json()) as ChatSessionsResponse;
  }

  async updateChatSessionTitle(
    sessionId: string,
    title: string,
  ): Promise<ChatSessionSummary> {
    const res = await fetch(
      `${this.baseUrl}/api/chat/sessions/${encodeURIComponent(sessionId)}`,
      {
        method: "PATCH",
        headers: {
          "Content-Type": "application/json",
          ...this.authHeaders(),
        },
        body: JSON.stringify({ title }),
      },
    );
    if (!res.ok) {
      throw new Error(`update session title failed: HTTP ${res.status}`);
    }
    return (await res.json()) as ChatSessionSummary;
  }

  async setChatSessionPinned(
    sessionId: string,
    pinned: boolean,
  ): Promise<ChatSessionSummary> {
    const res = await fetch(
      `${this.baseUrl}/api/chat/sessions/${encodeURIComponent(sessionId)}/pin`,
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...this.authHeaders(),
        },
        body: JSON.stringify({ pinned }),
      },
    );
    if (!res.ok) {
      throw new Error(`pin session failed: HTTP ${res.status}`);
    }
    return (await res.json()) as ChatSessionSummary;
  }

  async getCapabilities(): Promise<FaeCapabilities> {
    const res = await fetch(`${this.baseUrl}/api/capabilities`, {
      headers: this.authHeaders(),
    });
    if (!res.ok) {
      throw new Error(`capabilities failed: HTTP ${res.status}`);
    }
    return (await res.json()) as FaeCapabilities;
  }

  async getReady(): Promise<{ httpStatus: number; body: FaeReady }> {
    const res = await fetch(`${this.baseUrl}/ready`, {
      headers: this.authHeaders(),
    });
    const body = (await res.json().catch(() => ({}))) as FaeReady;
    return { httpStatus: res.status, body };
  }

  /**
   * Minimal inbox poll — wraps GET /api/notifications.
   * For live push, use setNotificationHandler on the WS connection.
   */
  async listNotifications(): Promise<unknown> {
    const res = await fetch(`${this.baseUrl}/api/notifications`, {
      headers: this.authHeaders(),
    });
    if (!res.ok) {
      throw new Error(`notifications failed: HTTP ${res.status}`);
    }
    return res.json();
  }

  /** Subscribe to WS notification frames (requires connect()). */
  subscribeNotifications(handler: NotifyHandler): void {
    this.setNotificationHandler(handler);
  }

  async listApprovals(params: {
    session_id?: string;
    tool_name?: string;
    status?: string;
    before?: number;
    limit?: number;
  } = {}): Promise<ApprovalListResponse> {
    const search = new URLSearchParams();
    Object.entries(params).forEach(([key, value]) => {
      if (value !== undefined && value !== null && value !== "") {
        search.set(key, String(value));
      }
    });
    const res = await fetch(
      `${this.baseUrl}/api/approvals${search.size ? `?${search}` : ""}`,
      { headers: this.authHeaders() },
    );
    if (!res.ok) {
      throw new Error(`list approvals failed: HTTP ${res.status}`);
    }
    return (await res.json()) as ApprovalListResponse;
  }

  async getApproval(approvalId: string): Promise<ApprovalRequestMsg> {
    const res = await fetch(
      `${this.baseUrl}/api/approvals/${encodeURIComponent(approvalId)}`,
      { headers: this.authHeaders() },
    );
    if (!res.ok) {
      throw new Error(`get approval failed: HTTP ${res.status}`);
    }
    return (await res.json()) as ApprovalRequestMsg;
  }

  async decideApproval(
    approvalId: string,
    decision: ApprovalDecisionInput,
  ): Promise<ApprovalRequestMsg> {
    const res = await fetch(
      `${this.baseUrl}/api/approvals/${encodeURIComponent(approvalId)}/decide`,
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...this.authHeaders(),
        },
        body: JSON.stringify(decision),
      },
    );
    if (!res.ok) {
      throw new Error(`decide approval failed: HTTP ${res.status}`);
    }
    return (await res.json()) as ApprovalRequestMsg;
  }

  async cancelApproval(
    approvalId: string,
    reason?: string,
  ): Promise<ApprovalRequestMsg> {
    const res = await fetch(
      `${this.baseUrl}/api/approvals/${encodeURIComponent(approvalId)}/cancel`,
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...this.authHeaders(),
        },
        body: JSON.stringify(reason ? { reason } : {}),
      },
    );
    if (!res.ok) {
      throw new Error(`cancel approval failed: HTTP ${res.status}`);
    }
    return (await res.json()) as ApprovalRequestMsg;
  }

  async getSessionPolicies(sessionId: string): Promise<SessionPolicies> {
    const res = await fetch(
      `${this.baseUrl}/api/sessions/${encodeURIComponent(sessionId)}/policies`,
      { headers: this.authHeaders() },
    );
    if (!res.ok) {
      throw new Error(`get session policies failed: HTTP ${res.status}`);
    }
    return (await res.json()) as SessionPolicies;
  }

  async patchSessionPolicies(
    sessionId: string,
    body: {
      always_allow?: string[];
      denied_tools?: string[];
    },
  ): Promise<SessionPolicies> {
    const res = await fetch(
      `${this.baseUrl}/api/sessions/${encodeURIComponent(sessionId)}/policies`,
      {
        method: "PATCH",
        headers: {
          "Content-Type": "application/json",
          ...this.authHeaders(),
        },
        body: JSON.stringify(body),
      },
    );
    if (!res.ok) {
      throw new Error(`patch session policies failed: HTTP ${res.status}`);
    }
    return (await res.json()) as SessionPolicies;
  }

  async getToolSpecs(): Promise<Record<string, ToolSpecSummary>> {
    const res = await fetch(`${this.baseUrl}/api/approvals/capabilities`, {
      headers: this.authHeaders(),
    });
    if (!res.ok) {
      throw new Error(`tool specs failed: HTTP ${res.status}`);
    }
    const json = (await res.json()) as { tools: Record<string, ToolSpecSummary> };
    return json.tools;
  }

  /**
   * Pull the agent execution trace for a session. Used by the FE to
   * hydrate per-turn main-line + details panels after a refresh.
   */
  async listAgentTrace(
    opts: { sessionId?: string; turnId?: string; kind?: string; limit?: number } = {},
  ): Promise<AgentTraceEvent[]> {
    const params = new URLSearchParams();
    if (opts.sessionId) params.set("session_id", opts.sessionId);
    if (opts.turnId) params.set("turn_id", opts.turnId);
    if (opts.kind) params.set("kind", opts.kind);
    if (opts.limit) params.set("limit", String(opts.limit));
    const qs = params.toString();
    const res = await fetch(
      `${this.baseUrl}/api/agent-trace${qs ? "?" + qs : ""}`,
      {
        headers: this.authHeaders(),
      },
    );
    if (!res.ok) {
      throw new Error(`agent-trace failed: HTTP ${res.status}`);
    }
    return (await res.json()) as AgentTraceEvent[];
  }

  /**
   * Pull the tool-audit log for a session. Companion to listAgentTrace
   * for clients that want parameter dumps without re-parsing the trace
   * payload string.
   */
  async listToolAudit(
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
    const res = await fetch(
      `${this.baseUrl}/api/tool-audit${qs ? "?" + qs : ""}`,
      {
        headers: this.authHeaders(),
      },
    );
    if (!res.ok) {
      throw new Error(`tool-audit failed: HTTP ${res.status}`);
    }
    return (await res.json()) as ToolAuditEvent[];
  }
}

export type AgentTraceEvent = {
  id: number;
  turn_id: string;
  session_id: string;
  channel: string;
  channel_id: string | null;
  kind: string;
  phase: string;
  name: string;
  payload: string;
  started_at: number;
  finished_at: number | null;
  duration_ms: number | null;
  ok: boolean | null;
  error_code: string | null;
};

export type ToolAuditEvent = {
  id: string;
  call_id: string;
  session_id: string;
  channel: string;
  channel_id: string | null;
  tool_name: string;
  phase: string;
  arguments: string;
  result: string;
  ok: boolean | null;
  error_code: string | null;
  approval_status: string;
  approval_id: string | null;
  turn_id: string | null;
  started_at: number;
  finished_at: number | null;
  duration_ms: number | null;
};

export function createClient(opts: CreateClientOptions): FaeClient {
  return new FaeClient(opts);
}
