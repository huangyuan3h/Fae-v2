/**
 * Thin re-export — chat transport lives in @fae/client (P7 SDK).
 */
import {
  buildWsChatUrl,
  ChatAbortedError,
  WsChatClient as SdkWsChatClient,
  type LlmConfigInput,
  type NotifyHandler,
  type StreamHandlers,
  type SubagentHandler,
  type WsServerMessage,
} from "@fae/client";

import type { AgentConfig } from "./config";
import { backendHttpBase, clientAccessToken } from "./config";

export type {
  NotifyHandler,
  StreamHandlers,
  SubagentHandler,
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
