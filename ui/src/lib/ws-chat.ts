import type { AgentConfig } from "./config";
import { backendWsBase } from "./config";

export type WsServerMessage =
  | { type: "token"; content: string }
  | { type: "done"; usage: unknown }
  | { type: "error"; code: string; message: string };

export type StreamHandlers = {
  onToken: (token: string) => void;
  onDone: () => void;
  onError: (code: string, message: string) => void;
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

  constructor(private readonly url = `${backendWsBase()}/ws/chat`) {}

  connect(): Promise<void> {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      return Promise.resolve();
    }
    return new Promise((resolve, reject) => {
      const ws = new WebSocket(this.url);
      this.ws = ws;
      ws.onopen = () => resolve();
      ws.onerror = () => reject(new Error("WebSocket connection failed"));
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
        if (msg.type === "token") {
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
