// gateway/frontend/src/components/ceoChat/types.ts

export type CeoRole = "ceo" | "system";
export type GovernanceState = "BLOCKED" | "APPROVED" | "EXECUTED";

export type ChatItemKind = "message" | "governance";

export type ChatItemBase = {
  id: string;
  kind: ChatItemKind;
  createdAt: number; // epoch ms
};

export type ChatMessageItem = ChatItemBase & {
  kind: "message";
  role: CeoRole;
  content: string;
  status?: "sending" | "delivered" | "streaming" | "final" | "error";
  requestId?: string;
};

export type GovernanceEventItem = ChatItemBase & {
  kind: "governance";
  state: GovernanceState;
  title?: string;
  summary?: string;
  reasons?: string[];
  approvalRequestId?: string;
  requestId?: string;
};

export type ChatItem = ChatMessageItem | GovernanceEventItem;

/**
 * UI Strings contract used by CeoChatbox + strings.ts
 */
export type UiStrings = {
  headerTitle: string;
  headerSubtitle: string;

  processingLabel: string;
  jumpToLatestLabel: string;

  blockedLabel: string;
  approvedLabel: string;
  executedLabel: string;

  openApprovalsLabel: string;
  approveLabel: string;
  retryLabel: string;

  inputPlaceholder: string;
  sendLabel: string;
};

/**
 * Gateway backend expects:
 * POST /api/ceo/command
 * {
 *   "input_text": "...",
 *   "smart_context": {...},
 *   "source": "ceo_dashboard"
 * }
 *
 * NOTE: Keeping legacy fields optional for backward-compat during migration.
 */
export type CeoCommandRequest = {
  // NEW (gateway)
  input_text: string;
  smart_context?: Record<string, unknown> | null;
  source?: string;

  // LEGACY (older frontend / older backend)
  text?: string;
  initiator?: string;
  session_id?: string;
  context_hint?: Record<string, unknown>;
  client_request_id?: string;
};

export type NormalizedConsoleResponse = {
  requestId?: string;
  systemText?: string;
  governance?: {
    state: GovernanceState;
    title?: string;
    summary?: string;
    reasons?: string[];
    approvalRequestId?: string;
  };
  // For streaming: incremental chunks of system text
  stream?: AsyncIterable<string>;
};
