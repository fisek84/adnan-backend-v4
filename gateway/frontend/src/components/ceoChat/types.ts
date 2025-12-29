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

  // vezivanje request/response (korisno za debug + retry)
  requestId?: string;
};

export type GovernanceState = "BLOCKED" | "APPROVED" | "EXECUTED" | string;

export type GovernanceCard = {
  state: GovernanceState;
  title?: string;
  summary?: string;
  reasons?: string[];
  approvalRequestId?: string;

  // za UI korelaciju (nije obavezno da backend šalje)
  requestId?: string;
};

export type GovernanceEventItem = {
  id: string;
  kind: "governance";
  state: GovernanceState;
  title?: string;
  summary?: string;
  reasons?: string[];
  approvalRequestId?: string;

  createdAt: number;
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
};

export type CeoCommandRequest = {
  input_text: string;
  smart_context?: Record<string, any>;
  source?: string;

  // optional: canonical fields koje backend wrapperi razumiju
  initiator?: string;
  session_id?: string | null;
  context_hint?: Record<string, any>;
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

  // omogućava UI da renderuje proposals i kad nisu mapirani u governance
  proposed_commands?: RawCeoConsoleResponse["proposed_commands"];

  // raw response za debug/compat (nikad ne gubi polja)
  raw?: RawCeoConsoleResponse;
};

// Backend shape (CEOCommandResponse iz FastAPI)
export type RawCeoConsoleResponse = {
  ok?: boolean;
  read_only?: boolean;
  context?: any;

  summary?: string;
  text?: string;

  // proposals iz agenta/routera (kanon za UI)
  proposed_commands?: Array<{
    command_type?: string;
    payload?: Record<string, any>;
    status?: string;
    required_approval?: boolean;
    cost_hint?: string | null;
    risk_hint?: string | null;

    // neki oblici proposals imaju args / command / intent / params
    command?: string;
    intent?: string;
    params?: Record<string, any>;
    args?: Record<string, any>;
  }>;

  trace?: Record<string, any>;
};
