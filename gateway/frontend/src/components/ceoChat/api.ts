// gateway/frontend/src/components/ceoChat/api.ts
//
// CANON (chat-first):
// - Chat/Plan ide na POST /api/chat i vraća text/summary + proposed_commands (0..N).
// - UI prikazuje proposed_commands, ali NE radi side-effects automatski.
// - Side-effects idu isključivo kroz /api/execute/raw (create approval) + /api/ai-ops/approval/approve (approve&execute).
//
// Ovaj file:
// - normalizuje response (normalize.ts)
// - podržava streaming (ne konzumira stream ovdje; UI ga čita)
// - daje helper metode za Notion Ops read/search (GET /notion-ops/databases, POST /notion-ops/bulk/query)

import { normalizeConsoleResponse, streamTextFromResponse } from "./normalize";

export type ProposedCommand = {
  command?: string;
  intent?: string;
  args?: Record<string, any>;
  params?: Record<string, any>;
  payload?: Record<string, any>;
  command_type?: string;
  required_approval?: boolean;
  dry_run?: boolean;
  scope?: string;
  risk?: string;
  risk_hint?: string;
  status?: string;
  [k: string]: any;
};

export type GovernanceCard = {
  state: "BLOCKED" | "APPROVED" | "EXECUTED" | string;
  title: string;
  summary?: string;
  reasons?: string[];
  approvalRequestId?: string;
  proposals?: ProposedCommand[];
};

export type NormalizedConsoleResponse = {
  requestId?: string;
  systemText?: string;

  // compatibility fields
  summary?: string;
  proposed_commands?: ProposedCommand[];

  governance?: GovernanceCard;

  // debug / trace
  raw?: any;
  source_endpoint?: string;

  // streaming (UI reads this)
  stream?: AsyncIterable<string>;
};

export type CeoCommandRequest = {
  text?: string;
  input_text?: string;

  initiator?: string;
  session_id?: string | null;

  context_hint?: Record<string, any> | null;
  smart_context?: Record<string, any> | null;

  [k: string]: any;
};

// ------------------------------
// Notion Ops (generic DB search)
// ------------------------------
export type NotionDatabasesResponse = {
  ok?: boolean;
  read_only?: boolean;
  databases: Record<string, string>; // db_key -> database_id
};

export type NotionQuerySpec = {
  db_key?: string;
  database_id?: string;

  filter?: Record<string, any> | null;
  sorts?: Array<Record<string, any>> | null;
  start_cursor?: string | null;
  page_size?: number | null;

  [k: string]: any;
};

export type NotionBulkQueryPayload = {
  queries: NotionQuerySpec[];
};

export type CeoConsoleApi = {
  sendCommand: (
    req: CeoCommandRequest,
    signal?: AbortSignal,
    onPartial?: (partial: NormalizedConsoleResponse) => void
  ) => Promise<NormalizedConsoleResponse>;

  approve: (approvalRequestId: string, signal?: AbortSignal) => Promise<any>;

  // Notion bulk ops (read/search)
  listNotionDatabases: (signal?: AbortSignal) => Promise<NotionDatabasesResponse>;
  notionBulkQuery: (payload: NotionBulkQueryPayload, signal?: AbortSignal) => Promise<any>;
};

function isNonEmptyString(v: any): v is string {
  return typeof v === "string" && v.trim().length > 0;
}

function asString(v: any): string {
  return typeof v === "string" ? v : "";
}

function extractText(req: CeoCommandRequest): string {
  const t = (req as any)?.text ?? (req as any)?.input_text ?? (req as any)?.message ?? "";
  return String(t || "").trim();
}

function isChatEndpoint(url: string): boolean {
  return url.includes("/api/chat") || url.endsWith("/chat");
}

function deriveNotionOpsUrl(fromBaseUrl: string, path: string): string {
  const p = path.startsWith("/") ? path : `/${path}`;

  // Ako je base relative (npr. "/api/chat"), vrati relativnu notion-ops rutu.
  if (!/^https?:\/\//i.test(fromBaseUrl)) return p;

  try {
    return new URL(p, fromBaseUrl).toString();
  } catch {
    return p;
  }
}

function extractProposedCommands(raw: any): ProposedCommand[] {
  if (!raw || typeof raw !== "object") return [];

  // /api/chat (kanon) obično vraća proposed_commands direktno,
  // ali ostavljamo tolerantne wrappere radi kompatibilnosti.
  const candidates = [
    raw.proposed_commands,
    raw.proposedCommands,
    raw?.result?.proposed_commands,
    raw?.result?.proposedCommands,
    raw?.data?.proposed_commands,
    raw?.data?.proposedCommands,
  ];

  for (const c of candidates) {
    if (Array.isArray(c)) return c as ProposedCommand[];
  }
  return [];
}

function extractApprovalId(raw: any): string | undefined {
  const v =
    raw?.approval_id ??
    raw?.approvalId ??
    raw?.approval_request_id ??
    raw?.approvalRequestId ??
    raw?.approval?.approval_id ??
    raw?.approval?.approvalId;

  return isNonEmptyString(v) ? v.trim() : undefined;
}

function mergeGovernance(
  baseGov: any | undefined,
  raw: any,
  proposed: ProposedCommand[]
): GovernanceCard | undefined {
  // NOTE (CANON):
  // Chat response ne mora imati governance. Governance se pojavljuje tek na execute/approve endpointima.
  // Ovdje samo “propagiramo” governance ako ga backend ipak vrati (npr. approval/execute response).
  const approvalId = extractApprovalId(raw);

  const g: GovernanceCard | undefined = baseGov
    ? {
        state: asString(baseGov.state) || asString(baseGov.status) || "BLOCKED",
        title: asString(baseGov.title) || "Governance",
        summary: isNonEmptyString(baseGov.summary) ? baseGov.summary : undefined,
        reasons: Array.isArray(baseGov.reasons) ? baseGov.reasons : undefined,
        approvalRequestId: isNonEmptyString(baseGov.approvalRequestId)
          ? baseGov.approvalRequestId
          : undefined,
      }
    : undefined;

  if (approvalId && g) g.approvalRequestId = g.approvalRequestId ?? approvalId;

  if (proposed.length) {
    if (g) {
      g.proposals = g.proposals ?? proposed;
    }
  }

  return g;
}

function normalizeRawToUi(raw: any, sourceEndpoint: string, headers?: Headers): NormalizedConsoleResponse {
  const base = normalizeConsoleResponse(raw, headers);
  const proposed = extractProposedCommands(raw);

  // systemText fallback (ako normalizeConsoleResponse nije mapirao)
  const sysText =
    (base as any)?.systemText ??
    (typeof raw?.text === "string" ? raw.text : undefined) ??
    (typeof raw?.summary === "string" ? raw.summary : undefined);

  const out: NormalizedConsoleResponse = {
    requestId: (base as any)?.requestId,
    systemText: isNonEmptyString(sysText) ? String(sysText) : undefined,
    governance: mergeGovernance((base as any)?.governance, raw, proposed),
    proposed_commands: proposed.length ? proposed : undefined,
    raw,
    source_endpoint: sourceEndpoint,
  };

  if (isNonEmptyString(raw?.summary)) out.summary = raw.summary.trim();
  return out;
}

function buildPayload(endpointUrl: string, req: CeoCommandRequest): any {
  const text = extractText(req);
  const initiator = (req as any)?.initiator || "ceo_dashboard";

  // /api/chat shape (AgentRouter / canon)
  if (isChatEndpoint(endpointUrl)) {
    const ctx = ((req as any)?.context_hint ?? {}) as Record<string, any>;
    const preferred =
      (typeof ctx.preferred_agent_id === "string" && ctx.preferred_agent_id.trim()) ||
      (typeof ctx.agent_id === "string" && ctx.agent_id.trim()) ||
      "ceo_advisor";

    return {
      message: text,
      preferred_agent_id: preferred,
      metadata: {
        initiator,
        source: "ceoChatbox",
        canon: "CEO_CONSOLE_APPROVAL_GATED_EXECUTION",
        context_hint: (req as any)?.context_hint ?? null,
        smart_context: (req as any)?.smart_context ?? null,
      },
    };
  }

  // Tolerant fallback (ako neko ipak pozove non-chat endpoint):
  return {
    text,
    input_text: text,
    message: text,
    prompt: text,
    initiator,
    session_id: (req as any)?.session_id ?? null,
    context_hint: (req as any)?.context_hint ?? null,
    smart_context: (req as any)?.smart_context ?? null,
  };
}

function hasExecutionOrApproval(raw: any): boolean {
  if (!raw || typeof raw !== "object") return false;

  const execState = raw?.execution_state ?? raw?.executionState;
  const execId = raw?.execution_id ?? raw?.executionId;
  const approvalId = extractApprovalId(raw);
  const hasApprovalObj = !!raw?.approval;

  return (
    isNonEmptyString(execState) ||
    isNonEmptyString(execId) ||
    isNonEmptyString(approvalId) ||
    hasApprovalObj
  );
}

async function fetchJsonOrText(res: Response): Promise<any> {
  // pokušaj json, fallback na text
  return await res.json().catch(async () => {
    const txt = await res.text().catch(() => "");
    return { text: txt };
  });
}

async function fetchAndNormalize(opts: {
  url: string;
  payload: any;
  signal?: AbortSignal;
  headers?: Record<string, string>;
}): Promise<NormalizedConsoleResponse> {
  const { url, payload, signal, headers } = opts;

  const res = await fetch(url, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(headers || {}),
    },
    body: JSON.stringify(payload),
    signal,
  });

  if (!res.ok) {
    const txt = await res.text().catch(() => "");
    throw new Error(`HTTP ${res.status} from ${url}: ${txt || res.statusText}`);
  }

  // Streaming support: ne konzumirati stream ovdje — UI (CeoChatbox) će ga čitati.
  const stream = streamTextFromResponse(res);
  if (stream) {
    return {
      stream,
      raw: { stream: true },
      source_endpoint: url,
    };
  }

  const raw = await fetchJsonOrText(res);
  return normalizeRawToUi(raw, url, res.headers);
}

export function createCeoConsoleApi(opts: {
  ceoCommandUrl: string; // SHOULD be "/api/chat" per CANON
  approveUrl?: string;   // default "/api/ai-ops/approval/approve"
  headers?: Record<string, string>;
}): CeoConsoleApi {
  const ceoCommandUrl = opts.ceoCommandUrl;
  const approveUrl = opts.approveUrl || "/api/ai-ops/approval/approve";
  const headers = opts.headers || {};

  return {
    // CANON: single source of truth for chat is /api/chat (no fallback to other endpoints).
    sendCommand: async (req: CeoCommandRequest, signal?: AbortSignal): Promise<NormalizedConsoleResponse> => {
      const payload = buildPayload(ceoCommandUrl, req);
      const resp = await fetchAndNormalize({
        url: ceoCommandUrl,
        payload,
        signal,
        headers,
      });

      // Safety: ako je neko greškom proslijedio execute/approve payload na ovaj call,
      // ne pokušavamo nikakav fallback. Samo vraćamo response.
      // (Chatbox UI odlučuje šta i kako prikazati.)
      return resp;
    },

    approve: async (approvalRequestId: string, signal?: AbortSignal): Promise<any> => {
      const res = await fetch(approveUrl, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(headers || {}),
        },
        body: JSON.stringify({ approval_id: approvalRequestId }),
        signal,
      });

      if (!res.ok) {
        const txt = await res.text().catch(() => "");
        throw new Error(`HTTP ${res.status} from ${approveUrl}: ${txt || res.statusText}`);
      }

      return await fetchJsonOrText(res);
    },

    listNotionDatabases: async (signal?: AbortSignal): Promise<NotionDatabasesResponse> => {
      const url = deriveNotionOpsUrl(ceoCommandUrl, "/notion-ops/databases");

      const res = await fetch(url, {
        method: "GET",
        headers: { ...(headers || {}) },
        signal,
      });

      if (!res.ok) {
        const txt = await res.text().catch(() => "");
        throw new Error(`HTTP ${res.status} from ${url}: ${txt || res.statusText}`);
      }

      const raw = await fetchJsonOrText(res);
      const dbs = raw?.databases;

      if (!dbs || typeof dbs !== "object") {
        return { ok: true, read_only: true, databases: {} };
      }

      const out: Record<string, string> = {};
      for (const [k, v] of Object.entries(dbs)) {
        if (typeof k !== "string" || !k.trim()) continue;
        if (typeof v === "string" && v.trim()) out[k.trim()] = v.trim();
        else if (v && typeof v === "object") {
          const id = (v as any).database_id ?? (v as any).databaseId ?? (v as any).id;
          if (typeof id === "string" && id.trim()) out[k.trim()] = id.trim();
        }
      }

      return { ok: true, read_only: true, databases: out };
    },

    notionBulkQuery: async (payload: NotionBulkQueryPayload, signal?: AbortSignal): Promise<any> => {
      const url = deriveNotionOpsUrl(ceoCommandUrl, "/notion-ops/bulk/query");

      // canonical: { queries: [...] }
      const res = await fetch(url, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(headers || {}),
        },
        body: JSON.stringify(payload),
        signal,
      });

      if (res.ok) return await fetchJsonOrText(res);

      // tolerant retry: flat body (samo ako imamo 1 query) — kompatibilnost
      if (payload && Array.isArray(payload.queries) && payload.queries.length === 1) {
        const flat = payload.queries[0] || {};
        const res2 = await fetch(url, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            ...(headers || {}),
          },
          body: JSON.stringify(flat),
          signal,
        });

        if (res2.ok) return await fetchJsonOrText(res2);

        const txt2 = await res2.text().catch(() => "");
        throw new Error(`HTTP ${res2.status} from ${url} (flat retry): ${txt2 || res2.statusText}`);
      }

      const txt = await res.text().catch(() => "");
      throw new Error(`HTTP ${res.status} from ${url}: ${txt || res.statusText}`);
    },
  };
}
