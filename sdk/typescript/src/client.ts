import type {
  CreateClientOptions,
  FaeCapabilities,
  FaeReady,
  LlmConfigInput,
  NotifyHandler,
  StreamHandlers,
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

  close(): void {
    this.ws.close();
  }

  private authHeaders(): Record<string, string> {
    return this.token ? { Authorization: `Bearer ${this.token}` } : {};
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
}

export function createClient(opts: CreateClientOptions): FaeClient {
  return new FaeClient(opts);
}
