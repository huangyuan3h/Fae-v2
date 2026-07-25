/** Shared types for the thin FAE client SDK. */

export type ThinkingMode = "auto" | "disabled" | "adaptive";

export type LlmConfigInput = {
  baseUrl?: string;
  apiKey?: string;
  model?: string;
  thinking?: ThinkingMode;
};

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

export type FaeCapabilities = {
  app: string;
  channels: {
    web_ws: boolean;
    http_chat: boolean;
    telegram: { configured: boolean; running: boolean };
  };
  modes: { text: boolean; voice_daily: boolean; tts_local: boolean };
  tools: string[];
  skills_enabled: boolean;
  subagent_enabled: boolean;
  scheduler_enabled: boolean;
  scheduler_running: boolean;
  llm: { server_configured: boolean };
  auth: { client_token_required: boolean };
  status: {
    scheduler: string;
    telegram: string;
    proactive_llm: string;
  };
};

export type FaeReady = {
  status: string;
  app?: string;
  memory?: string;
  scheduler?: string;
  telegram?: string;
  proactive_llm?: string;
  letta?: string;
};

export type CreateClientOptions = {
  /** HTTP base, e.g. http://127.0.0.1:8000 */
  baseUrl: string;
  /** Optional FAE_CLIENT_TOKEN (Bearer / WS query). */
  token?: string;
};
