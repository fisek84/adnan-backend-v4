// gateway/frontend/src/components/ceoChat/types.ts

export type BusyState = "idle" | "submitting" | "streaming" | "error";

export type ChatStatus = "delivered" | "streaming" | "final" | "error";
export type ChatRole = "ceo" | "system";

export type ChatMessageItem = {
  id: string;
  kind: "message";
  role: ChatRole;
  content: string;
  status: ChatStatus;
  createdAt: number;
  requestId?: string;
};

export type GovernanceState = "BLOCKED" | "APPROVED" | "EXECUTED" | string;

export type GovernanceEventItem = {
  id: string;
  kind: "governance";
  createdAt: number;
  state: GovernanceState;
  title?: string;
  summary?: string;
  reasons?: string[];
  approvalRequestId?: string;
  requestId?: string;
};

export type ChatItem = ChatMessageItem | GovernanceEventItem;

export type UiStrings = {
  headerTitle: string;
  headerSubtitle: string;
  processingLabel: string;
  jumpToLatestLabel: string;
  inputPlaceholder: string;
  sendLabel: string;

  blockedLabel: string;
  approvedLabel: string;
  executedLabel: string;

  openApprovalsLabel: string;
  approveLabel: string;

  retryLabel: string;
};

export type CeoCommandRequest = {
  // Preferirano (tvoj FastAPI router očekuje ovo):
  text: string;
  initiator?: string;
  session_id?: string;
  context_hint?: Record<string, any>;

  // Legacy polja (ako negdje u kodu još postoji):
  input_text?: string;
  smart_context?: Record<string, any>;
  source?: string;
};

export type GovernanceCard = {
  state: GovernanceState;
  title?: string;
  summary?: string;
  reasons?: string[];
  approvalRequestId?: string;
};

export type NormalizedConsoleResponse = {
  requestId?: string;

  // preferirano polje koje CeoChatbox koristi
  systemText?: string;

  // kompatibilnost (da build nikad ne padne ako se negdje koristi)
  summary?: string;
  text?: string;

  governance?: GovernanceCard;

  // opciono za streaming (ako ikad dodaš)
  stream?: AsyncIterable<string>;
};

// Backend shape (CEOCommandResponse iz FastAPI)
export type RawCeoConsoleResponse = {
  ok?: boolean;
  read_only?: boolean;
  context?: any;
  summary?: string;
  text?: string; // fallback ako nekad vrati
  proposed_commands?: Array<{
    command_type?: string;
    payload?: Record<string, any>;
    status?: string;
    required_approval?: boolean;
    cost_hint?: string | null;
    risk_hint?: string | null;
  }>;
  trace?: Record<string, any>;
};
