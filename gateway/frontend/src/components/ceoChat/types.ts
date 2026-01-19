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

// ------------------------------
// Proposed commands (UI-friendly)
// ------------------------------
export type ProposedCommand = {
  // tolerant: backend ponekad šalje različite kombinacije
  command_type?: string;
  payload?: Record<string, any>;
  required_approval?: boolean;
  status?: string;

  // tolerant aliases
  command?: string;
  intent?: string;
  params?: Record<string, any>;
  args?: Record<string, any>;

  [k: string]: any;
};

export type GovernanceEventItem = {
  id: string;
  kind: "governance";
  state: GovernanceState;
  title?: string;
  summary?: string;
  reasons?: string[];
  approvalRequestId?: string;

  // optional execution artifacts
  notionLinks?: Array<{ label: string; url: string }>;
  refMap?: Record<string, string>;

  // allow governance cards to carry proposals for UI actions
  proposedCommands?: ProposedCommand[];

  createdAt: number;
  requestId?: string;
};

export type ChatItem = ChatMessageItem | GovernanceEventItem;

// ------------------------------
// Notion Search (generic)
// ------------------------------
export type NotionDatabasesResponse = {
  ok?: boolean;
  read_only?: boolean;
  // db_key -> database_id
  databases: Record<string, string>;
};

export type NotionQuerySpec = {
  // prefer db_key, ali toleriramo i database_id
  db_key?: string;
  database_id?: string;

  filter?: Record<string, any> | null;
  sorts?: Array<Record<string, any>> | null;
  start_cursor?: string | null;
  page_size?: number | null;

  // tolerant passthrough
  [k: string]: any;
};

export type NotionBulkQueryPayload = {
  queries: NotionQuerySpec[];
};

// “Generic” query result (backend može vratiti results: [...])
export type NotionBulkQueryResponse = {
  results?: Array<any>;
  [k: string]: any;
};

// ------------------------------
// UI strings
// ------------------------------
// IMPORTANT: Ovo mora odgovarati defaultStrings u strings.ts
export type UiStrings = {
  headerTitle: string;
  headerSubtitle: string;

  inputPlaceholder: string;
  sendLabel: string;

  processingLabel: string;
  jumpToLatestLabel: string;

  blockedLabel: string;
  approvedLabel: string;
  executedLabel: string;

  openApprovalsLabel: string;
  approveLabel: string;
  retryLabel: string;

  // ------------------------------
  // Notion Search (generic)
  // ------------------------------
  searchNotionLabel: string; // naziv sekcije/akcije
  chooseDatabaseLabel: string; // label za dropdown
  databasePlaceholder: string; // placeholder kad nema izbora
  loadDatabasesLabel: string; // dugme: load/refresh
  runSearchLabel: string; // dugme: search
  searchQueryPlaceholder: string; // input placeholder za search
  searchingLabel: string; // status tokom query
  noResultsLabel: string; // kad nema rezultata
};

export type CeoCommandRequest = {
  // tolerantan input (api.ts koristi extractText)
  text?: string;
  input_text?: string;

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

  // opciono za streaming
  stream?: AsyncIterable<string>;

  // omogućava UI da renderuje proposals i kad nisu mapirani u governance
  proposed_commands?: ProposedCommand[];

  // raw response za debug/compat (nikad ne gubi polja)
  raw?: RawCeoConsoleResponse;

  // optional: source endpoint
  source_endpoint?: string;
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

    [k: string]: any;
  }>;

  trace?: Record<string, any>;

  [k: string]: any;
};
