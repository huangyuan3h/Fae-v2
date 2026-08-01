/** Shared types for the thin FAE client SDK. */

export type ThinkingMode = "auto" | "disabled" | "adaptive";

export type LlmConfigInput = {
  baseUrl?: string;
  apiKey?: string;
  model?: string;
  thinking?: ThinkingMode;
};

export type TokenUsage = {
  prompt_tokens?: number;
  completion_tokens?: number;
  total_tokens?: number;
  cached_tokens?: number;
  cache_creation_tokens?: number;
};

export type WsServerMessage =
  | {
      type: "skills";
      active: string[];
      lazy_catalog?: string[];
      scores?: Record<string, number>;
    }
  | {
      type: "turn_started";
      turn_id: string;
      session_id: string;
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
  | {
      type: "tool";
      phase: "start" | "result";
      id: string;
      name: string;
      arguments?: string;
      ok?: boolean;
      result?: string;
      approval_id?: string | null;
      approval_status?: string | null;
      error_code?: string | null;
    }
  | {
      type: "approval_request";
      approval: ApprovalRequestMsg;
      follow_up?: boolean;
    }
  | {
      type: "approval_resolved";
      approval_id: string;
      tool_name: string;
      status: ApprovalStatus;
      decision_reason?: string | null;
      decided_by?: string | null;
    }
  | { type: "token"; content: string }
  | {
      type: "done";
      usage: TokenUsage | null;
      session_id?: string;
      turn_id?: string;
      chat_turn_id?: string;
      active_skills?: string[];
    }
  | {
      type: "notification";
      id?: string;
      title: string;
      body: string;
      quiet?: boolean;
      speak?: boolean;
    }
  | { type: "error"; code: string; message: string }
  | {
      type: "plan_loaded" | "plan_suggested";
      plan?: PlanPayload;
      user_text?: string;
    }
  | {
      type: "plan_created" | "plan_step_update" | "plan_step_completed";
      plan_id: string;
      plan?: PlanPayload | null;
      step?: PlanStepPayload | null;
    }
  | {
      type: "plan_step_input_ack";
      plan_id: string;
      step_index: number;
      kind: "answer" | "abort";
      step?: PlanStepPayload | null;
      plan?: PlanPayload | null;
    };

export type PlanStepStatus =
  | "pending"
  | "in_progress"
  | "completed"
  | "blocked"
  | "cancelled";

export type PlanStatus = "active" | "completed" | "abandoned";

export type PlanStepPayload = {
  id: string;
  index: number;
  title: string;
  acceptance?: string;
  status: PlanStepStatus;
  note?: string;
  started_at?: number | null;
  finished_at?: number | null;
};

export type PlanPayload = {
  id: string;
  session_id: string;
  title: string;
  summary?: string;
  status: PlanStatus;
  steps: PlanStepPayload[];
  created_at: number;
  updated_at: number;
  finished_at?: number | null;
};

export type WsClientMessage =
  | { type: "chat"; request: unknown; session_id?: string }
  | { type: "cancel" }
  | {
      type: "approval_decision";
      approval_id: string;
      action: "approve" | "deny" | "cancel";
      reason?: string;
      confirm?: boolean;
      remember?: "session" | "always" | null;
      decided_by?: string;
    }
  | {
      type: "plan_step_input";
      plan_id: string;
      step_index: number;
      input_text?: string;
      kind: "answer" | "abort";
      session_id?: string;
    };

export type ApprovalStatus =
  | "pending"
  | "approved"
  | "denied"
  | "expired"
  | "cancelled"
  | "superseded"
  | "awaiting_confirm";

export type ApprovalRequestMsg = {
  id: string;
  session_id: string;
  turn_id: string | null;
  channel: string;
  channel_id: string | null;
  tool_name: string;
  risk_tier: string;
  arguments_summary: string;
  arguments_full: string;
  diff_preview: string | null;
  requester: string;
  status: ApprovalStatus;
  decision_reason: string | null;
  decided_by: string | null;
  needs_double_confirm: boolean;
  double_confirm_window_s: number;
  args_hash: string;
  ttl_s: number;
  created_at: number;
  expires_at: number;
  decided_at: number | null;
  consumed: boolean;
};

export type ApprovalResolvedMsg = {
  approval_id: string;
  tool_name: string;
  status: ApprovalStatus;
  decision_reason?: string | null;
  decided_by?: string | null;
};

export type ApprovalDecisionInput = {
  action: "approve" | "deny" | "cancel";
  reason?: string;
  confirm?: boolean;
  remember?: "session" | "always";
  decided_by?: string;
};

export type ApprovalListResponse = {
  items: ApprovalRequestMsg[];
  count: number;
};

export type SessionPolicies = {
  session_id: string;
  always_allow: string[];
  denied_tools: string[];
  raw_meta?: Record<string, string>;
};

export type ToolSpecSummary = {
  risk_tier: "safe" | "caution" | "sensitive" | "dangerous";
  side_effects: string[];
  requires_approval: boolean;
  needs_diff_preview: boolean;
  needs_double_confirm: boolean;
  default_ttl_s: number;
  description: string;
};

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

export type ToolHandler = (msg: {
  phase: "start" | "result";
  id: string;
  name: string;
  arguments?: string;
  ok?: boolean;
  result?: string;
  approval_id?: string | null;
  approval_status?: string | null;
  error_code?: string | null;
}) => void;

export type ApprovalRequestHandler = (
  msg: ApprovalRequestMsg,
  followUp?: boolean,
) => void;

export type ApprovalResolvedHandler = (msg: ApprovalResolvedMsg) => void;

export type StreamHandlers = {
  onToken: (token: string) => void;
  onDone?: (info?: {
    usage?: TokenUsage | null;
    turn_id?: string;
    chat_turn_id?: string;
  }) => void;
  onError: (code: string, message: string) => void;
  onSkills?: (
    active: string[],
    scores?: Record<string, number>,
    lazyCatalog?: string[],
  ) => void;
  onSubagent?: SubagentHandler;
  onTool?: ToolHandler;
  onNotification?: NotifyHandler;
  onApprovalRequest?: ApprovalRequestHandler;
  onApprovalResolved?: ApprovalResolvedHandler;
  onPlanLoaded?: (plan: PlanPayload) => void;
  onPlanCreated?: (plan: PlanPayload) => void;
  onPlanStepUpdate?: (plan: PlanPayload, step: PlanStepPayload) => void;
  onPlanStepCompleted?: (plan: PlanPayload, step: PlanStepPayload) => void;
  onPlanSuggested?: (userText: string) => void;
  onPlanStepInputAck?: (
    planId: string,
    stepIndex: number,
    kind: "answer" | "abort",
    step?: PlanStepPayload | null,
    plan?: PlanPayload | null,
  ) => void;
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

export type ChatHistoryTurn = {
  id: string;
  session_id: string;
  user_text: string;
  assistant_text: string;
  created_at: string;
  trace_turn_id?: string | null;
};

export type ChatHistory = {
  session_id: string;
  retention_days: number;
  turns: ChatHistoryTurn[];
  has_more: boolean;
};

export type ChatSessionSummary = {
  session_id: string;
  title: string;
  pinned: boolean;
  turn_count: number;
  last_activity_at: string;
};

export type ChatSessionsResponse = {
  retention_days: number;
  sessions: ChatSessionSummary[];
};

export type CreateClientOptions = {
  /** HTTP base, e.g. http://127.0.0.1:8000 */
  baseUrl: string;
  /** Optional FAE_CLIENT_TOKEN (Bearer / WS query). */
  token?: string;
};
