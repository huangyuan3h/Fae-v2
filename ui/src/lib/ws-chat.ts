import type { AgentConfig } from "./config";
import { backendWsBase } from "./config";

export type WsServerMessage =
  | {
      type: "skills";
      active: string[];
      lazy_catalog?: string[];
      scores?: Record<string, number>;
    }
  | {
      type: "subagent";
      phase: "start" | "done";
      name: string;
      task?: string;
      ok?: boolean;
      error?: string | null;
      summary?: string;
    }
  | { type: "token"; content: string }
  | { type: "done"; usage: unknown; session_id?: string }
  | {
      type: "notification";
      id?: string;
      title: string;
      body: string;
      quiet?: boolean;
      speak?: boolean;
    }
  | { type: "error"; code: string; message: string };

export type NotifyHandler = (
  title: string,
  body: string,
  quiet?: boolean,
  speak?: boolean,
) => void;

export type SubagentHandler = (msg: {
  phase: "start" | "done";
  name: string;
  task?: string;
  ok?: boolean;
  error?: string | null;
  summary?: string;
}) => void;

export type StreamHandlers = {
  onToken: (token: string) => void;
  onDone: () => void;
  onError: (code: string, message: string) => void;
  onSkills?: (
    active: string[],
    scores?: Record<string, number>,
    lazyCatalog?: string[],
  ) => void;
  onSubagent?: SubagentHandler;
  onNotification?: NotifyHandler;
};

export class ChatAbortedError extends Error {
  constructor() {
    super("chat aborted");
    this.name = "ChatAbortedError";
  }
}

export class WsChatClient {
  private ws: WebSocket | null = null;
  private activeCleanup: (() => void) | null = null;
  private activeReject: ((err: Error) => void) | null = null;
  private notifyHandler: NotifyHandler | null = null;

  constructor(private readonly url = `${backendWsBase()}/ws/chat`) {}

  setNotificationHandler(handler: NotifyHandler | null) {
    this.notifyHandler = handler;
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
    config: AgentConfig,
    handlers: StreamHandlers,
    sessionId?: string | null,
  ): Promise<void> {
    // One in-flight chat per client — cancel any previous turn first.
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
          handlers.onSkills?.(
            msg.active ?? [],
            msg.scores,
            msg.lazy_catalog,
          );
        } else if (msg.type === "subagent") {
          handlers.onSubagent?.({
            phase: msg.phase,
            name: msg.name,
            task: msg.task,
            ok: msg.ok,
            error: msg.error,
            summary: msg.summary,
          });
        } else if (msg.type === "notification") {
          handlers.onNotification?.(
            msg.title,
            msg.body,
            msg.quiet,
            msg.speak,
          );
        } else if (msg.type === "token") {
          handlers.onToken(msg.content);
        } else if (msg.type === "done") {
          cleanup();
          handlers.onDone();
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
            base_url: config.baseUrl,
            api_key: config.apiKey,
            model: config.model,
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
