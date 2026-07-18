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

export class WsChatClient {
  private ws: WebSocket | null = null;

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
  ): Promise<void> {
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
      };

      ws.addEventListener("message", onMessage);
      ws.send(
        JSON.stringify({
          type: "chat",
          request: {
            config: {
              base_url: config.baseUrl,
              api_key: config.apiKey,
              model: config.model,
            },
            messages: [{ role: "user", content: text }],
          },
        }),
      );
    });
  }

  cancel(): void {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({ type: "cancel" }));
    }
  }

  close(): void {
    this.ws?.close();
    this.ws = null;
  }
}
