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
 * CEO Console backend expects:
 * POST /api/ceo-console/command
 * {
 *   "text": "...",
 *   "initiator": "...",
 *   "session_id": "...",
 *   "context_hint": {...}
 * }
 */
export type CeoCommandRequest = {
  text: string;
  initiator?: string;
  session_id?: string;
  context_hint?: Record<string, unknown>;
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
  // For future streaming: incremental chunks of system text
  stream?: AsyncIterable<string>;
};
