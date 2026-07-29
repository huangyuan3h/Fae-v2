import type {
  ApprovalDecisionInput,
  ApprovalRequestHandler,
  ApprovalResolvedHandler,
  LlmConfigInput,
  NotifyHandler,
  StreamHandlers,
  WsServerMessage,
} from "./types";

export class ChatAbortedError extends Error {
  constructor() {
    super("chat aborted");
    this.name = "ChatAbortedError";
  }
}

function withAccessToken(wsUrl: string, token?: string): string {
  const t = (token || "").trim();
  if (!t) return wsUrl;
  const sep = wsUrl.includes("?") ? "&" : "?";
  return `${wsUrl}${sep}access_token=${encodeURIComponent(t)}`;
}

export type TurnStartedHandler = (msg: {
  turn_id: string;
  session_id: string;
}) => void;

export class WsChatClient {
  private ws: WebSocket | null = null;
  private activeCleanup: (() => void) | null = null;
  private activeReject: ((err: Error) => void) | null = null;
  private notifyHandler: NotifyHandler | null = null;
  private approvalRequestHandler: ApprovalRequestHandler | null = null;
  private approvalResolvedHandler: ApprovalResolvedHandler | null = null;
  private turnStartedHandler: TurnStartedHandler | null = null;

  constructor(private readonly url: string) {}

  setNotificationHandler(handler: NotifyHandler | null) {
    this.notifyHandler = handler;
  }

  setApprovalRequestHandler(handler: ApprovalRequestHandler | null) {
    this.approvalRequestHandler = handler;
  }

  setApprovalResolvedHandler(handler: ApprovalResolvedHandler | null) {
    this.approvalResolvedHandler = handler;
  }

  setTurnStartedHandler(handler: TurnStartedHandler | null) {
    this.turnStartedHandler = handler;
  }

  sendApprovalDecision(
    approvalId: string,
    decision: ApprovalDecisionInput,
  ): boolean {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
      return false;
    }
    this.ws.send(
      JSON.stringify({
        type: "approval_decision",
        approval_id: approvalId,
        action: decision.action,
        reason: decision.reason,
        confirm: decision.confirm ?? false,
        remember: decision.remember ?? null,
        decided_by: decision.decided_by ?? "user",
      }),
    );
    return true;
  }

  connect(): Promise<void> {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      return Promise.resolve();
    }
    return new Promise((resolve, reject) => {
      const ws = new WebSocket(this.url);
      this.ws = ws;
      ws.onopen = () => resolve();
      ws.onerror = () => reject(new Error("WebSocket connection failed"));
      ws.addEventListener("message", (ev) => {
        try {
          const msg = JSON.parse(String(ev.data)) as WsServerMessage;
          if (msg.type === "notification") {
            this.notifyHandler?.(msg.title, msg.body, msg.quiet, msg.speak);
          }
        } catch {
          /* ignore */
        }
      });
    });
  }

  async chat(
    text: string,
    config: LlmConfigInput,
    handlers: StreamHandlers,
    sessionId?: string | null,
  ): Promise<void> {
    this.cancel();
    await this.connect();
    const ws = this.ws;
    if (!ws) throw new Error("WebSocket not connected");

    return new Promise((resolve, reject) => {
      const onMessage = (ev: MessageEvent) => {
        let msg: WsServerMessage;
        try {
          msg = JSON.parse(String(ev.data)) as WsServerMessage;
        } catch {
          return;
        }
        if (msg.type === "skills") {
          handlers.onSkills?.(msg.active ?? [], msg.scores, msg.lazy_catalog);
        } else if (msg.type === "subagent") {
          handlers.onSubagent?.({
            phase: msg.phase,
            name: msg.name,
            task: msg.task,
            ok: msg.ok,
            error: msg.error,
            summary: msg.summary,
          });
        } else if (msg.type === "turn_started") {
          this.turnStartedHandler?.({
            turn_id: msg.turn_id,
            session_id: msg.session_id,
          });
        } else if (msg.type === "tool") {
          handlers.onTool?.({
            phase: msg.phase,
            id: msg.id,
            name: msg.name,
            arguments: msg.arguments,
            ok: msg.ok,
            result: msg.result,
            approval_id: msg.approval_id,
            approval_status: msg.approval_status,
            error_code: msg.error_code ?? null,
          });
        } else if (msg.type === "approval_request") {
          handlers.onApprovalRequest?.(msg.approval, msg.follow_up);
          this.approvalRequestHandler?.(msg.approval, msg.follow_up);
        } else if (msg.type === "approval_resolved") {
          handlers.onApprovalResolved?.({
            approval_id: msg.approval_id,
            tool_name: msg.tool_name,
            status: msg.status,
            decision_reason: msg.decision_reason ?? null,
            decided_by: msg.decided_by ?? null,
          });
          this.approvalResolvedHandler?.({
            approval_id: msg.approval_id,
            tool_name: msg.tool_name,
            status: msg.status,
            decision_reason: msg.decision_reason ?? null,
            decided_by: msg.decided_by ?? null,
          });
        } else if (msg.type === "notification") {
          handlers.onNotification?.(
            msg.title,
            msg.body,
            msg.quiet,
            msg.speak,
          );
        } else if (msg.type === "plan_loaded") {
          if (msg.plan) handlers.onPlanLoaded?.(msg.plan);
        } else if (msg.type === "plan_suggested") {
          handlers.onPlanSuggested?.(msg.user_text ?? "");
        } else if (msg.type === "plan_created") {
          if (msg.plan) handlers.onPlanCreated?.(msg.plan);
        } else if (msg.type === "plan_step_update") {
          if (msg.plan && msg.step) {
            handlers.onPlanStepUpdate?.(msg.plan, msg.step);
          }
        } else if (msg.type === "plan_step_completed") {
          if (msg.plan && msg.step) {
            handlers.onPlanStepCompleted?.(msg.plan, msg.step);
          }
        } else if (msg.type === "token") {
          handlers.onToken(msg.content);
        } else if (msg.type === "done") {
          cleanup();
          handlers.onDone?.({
            usage: msg.usage ?? null,
            turn_id: msg.turn_id,
            chat_turn_id: msg.chat_turn_id,
          });
          resolve();
        } else if (msg.type === "error") {
          cleanup();
          handlers.onError(msg.code, msg.message);
          reject(new Error(`${msg.code}: ${msg.message}`));
        }
      };

      const cleanup = () => {
        ws.removeEventListener("message", onMessage);
        if (this.activeCleanup === cleanup) {
          this.activeCleanup = null;
          this.activeReject = null;
        }
      };

      this.activeCleanup = cleanup;
      this.activeReject = reject;
      ws.addEventListener("message", onMessage);
      const payload: Record<string, unknown> = {
        type: "chat",
        request: {
          config: {
            base_url: config.baseUrl ?? "",
            api_key: config.apiKey ?? "",
            model: config.model ?? "",
            thinking: config.thinking ?? "disabled",
          },
          messages: [{ role: "user", content: text }],
          session_id: sessionId || undefined,
        },
      };
      if (sessionId) {
        payload.session_id = sessionId;
      }
      ws.send(JSON.stringify(payload));
    });
  }

  cancel(): void {
    const reject = this.activeReject;
    if (this.activeCleanup) {
      this.activeCleanup();
    }
    if (reject) {
      reject(new ChatAbortedError());
    }
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({ type: "cancel" }));
    }
  }

  close(): void {
    this.cancel();
    this.ws?.close();
    this.ws = null;
  }
}

export function buildWsChatUrl(httpBase: string, token?: string): string {
  const http = httpBase.replace(/\/$/, "");
  let ws: string;
  if (http.startsWith("https://")) ws = http.replace("https://", "wss://");
  else ws = http.replace("http://", "ws://");
  return withAccessToken(`${ws}/ws/chat`, token);
}
