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
 * CEO Console backend expects:
 * POST /api/ceo-console/command
 * {
 *   "text": "...",
 *   "initiator": "...",
 *   "session_id": "...",
 *   "context_hint": {...}
 * }
 *
 * NOTE: client_request_id is supported for backward-compat with older frontend code.
 */
export type CeoCommandRequest = {
  text: string;
  initiator?: string;
  session_id?: string;
  context_hint?: Record<string, unknown>;

  // backward-compat (some code still uses this name)
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
