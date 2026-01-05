// gateway/frontend/src/components/ceoChat/api.ts
//
// Cilj:
// - UI mora uvijek dobiti proposed_commands (ako ih backend vrati).
// - Ako /api/ceo-console/command ne vraća proposals, automatski fallback na /api/chat.
// - Podržati AbortSignal iz CeoChatbox-a.
// - Ne oslanjati se na krhke TS kontrakte: tolerantan mapping.
// - KORISTITI normalize.ts (normalizeConsoleResponse + streaming) da promjene utiču na UI.
//
// Napomena:
// - NE RADITI fallback na /api/chat ako primarni odgovor već sadrži execution/approve payload
//   (npr. execution_state/approval). U tom slučaju /api/chat često pregazi ispravan rezultat.

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

  // streaming
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

function deriveChatUrl(fromCeoCommandUrl: string): string {
  if (/^https?:\/\//i.test(fromCeoCommandUrl)) {
    try {
      return new URL("/api/chat", fromCeoCommandUrl).toString();
    } catch {
      return "/api/chat";
    }
  }
  return "/api/chat";
}

function deriveNotionOpsUrl(fromCeoCommandUrl: string, path: string): string {
  const p = path.startsWith("/") ? path : `/${path}`;
  if (!/^https?:\/\//i.test(fromCeoCommandUrl)) return p;
  try {
    return new URL(p, fromCeoCommandUrl).toString();
  } catch {
    return p;
  }
}

function extractProposedCommands(raw: any): ProposedCommand[] {
  if (!raw || typeof raw !== "object") return [];

  const candidates = [
    raw.proposed_commands,
    raw.proposedCommands,
    raw?.advisory?.proposed_commands,
    raw?.advisory?.proposedCommands,
    raw?.result?.proposed_commands,
    raw?.result?.proposedCommands,
    raw?.data?.proposed_commands,
    raw?.data?.proposedCommands,

    // approve/execute wrapperi
    raw?.approval?.proposed_commands,
    raw?.approval?.payload_summary?.proposed_commands,
    raw?.approval?.payload_summary?.result?.proposed_commands,
    raw?.approval?.payload_summary?.payload?.proposed_commands,
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

function mergeGovernance(baseGov: any | undefined, raw: any, proposed: ProposedCommand[]): GovernanceCard | undefined {
  const approvalId = extractApprovalId(raw);

  const g: GovernanceCard | undefined = baseGov
    ? {
        state: asString(baseGov.state) || asString(baseGov.status) || "BLOCKED",
        title: asString(baseGov.title) || "Governance",
        summary: isNonEmptyString(baseGov.summary) ? baseGov.summary : undefined,
        reasons: Array.isArray(baseGov.reasons) ? baseGov.reasons : undefined,
        approvalRequestId: isNonEmptyString(baseGov.approvalRequestId) ? baseGov.approvalRequestId : undefined,
      }
    : undefined;

  if (approvalId && g) g.approvalRequestId = g.approvalRequestId ?? approvalId;

  if (proposed.length) {
    if (g) {
      g.proposals = g.proposals ?? proposed;
      if (!g.state) g.state = "BLOCKED";
      if (!g.title) g.title = approvalId ? "Approval required" : "Proposals";
    } else {
      return {
        state: "BLOCKED",
        title: approvalId ? "Approval required" : "Proposals",
        summary:
          asString(raw?.summary) ||
          asString(raw?.text) ||
          (approvalId ? "Execution is blocked until CEO approval." : "Agent returned proposed commands."),
        approvalRequestId: approvalId,
        proposals: proposed,
      };
    }
  }

  return g;
}

function normalizeRawToUi(raw: any, sourceEndpoint: string, headers?: Headers): NormalizedConsoleResponse {
  const base = normalizeConsoleResponse(raw, headers);
  const proposed = extractProposedCommands(raw);

  const out: NormalizedConsoleResponse = {
    requestId: (base as any)?.requestId,
    systemText: (base as any)?.systemText,
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

  // /api/chat shape (AgentRouter)
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
        context_hint: (req as any)?.context_hint ?? null,
        smart_context: (req as any)?.smart_context ?? null,
      },
    };
  }

  // /api/ceo-console/command wrappers – tolerantan shape
  return {
    text,
    input_text: text,
    message: text,
    prompt: text,
    initiator,
    session_id: (req as any)?.session_id ?? null,
    context_hint: (req as any)?.context_hint ?? null,
    smart_context: (req as any)?.smart_context ?? null,
    data: {
      text,
      input_text: text,
      message: text,
      prompt: text,
      initiator,
      session_id: (req as any)?.session_id ?? null,
      context_hint: (req as any)?.context_hint ?? null,
      smart_context: (req as any)?.smart_context ?? null,
    },
  };
}

function hasExecutionOrApproval(raw: any): boolean {
  if (!raw || typeof raw !== "object") return false;

  const execState = raw?.execution_state ?? raw?.executionState;
  const execId = raw?.execution_id ?? raw?.executionId;
  const approvalId = extractApprovalId(raw);
  const hasApprovalObj = !!raw?.approval;

  return isNonEmptyString(execState) || isNonEmptyString(execId) || isNonEmptyString(approvalId) || hasApprovalObj;
}

async function fetchJsonOrText(res: Response): Promise<any> {
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
  onPartial?: (partial: NormalizedConsoleResponse) => void;
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

  // Streaming support: NE konzumirati stream ovdje — prepusti UI-u (CeoChatbox.tsx).
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

// fallback: izvuci mapping db_key -> database_id iz ceo snapshot-a (inventory)
function extractDatabasesFromSnapshot(raw: any): Record<string, string> {
  const out: Record<string, string> = {};

  const dbs =
    raw?.context?.snapshot?.ceo_dashboard_snapshot?.dashboard?.metadata?.databases ??
    raw?.context?.snapshot?.ceo_dashboard_snapshot?.metadata?.databases ??
    raw?.snapshot?.ceo_dashboard_snapshot?.dashboard?.metadata?.databases;

  if (dbs && typeof dbs === "object") {
    for (const [k, v] of Object.entries(dbs)) {
      if (typeof k !== "string" || !k.trim()) continue;
      if (typeof v === "string" && v.trim()) {
        out[k.trim()] = v.trim();
        continue;
      }
      if (v && typeof v === "object") {
        const id = (v as any).database_id ?? (v as any).databaseId ?? (v as any).id;
        if (typeof id === "string" && id.trim()) out[k.trim()] = id.trim();
      }
    }
  }

  return out;
}

export function createCeoConsoleApi(opts: {
  ceoCommandUrl: string;
  approveUrl?: string;
  headers?: Record<string, string>;
}): CeoConsoleApi {
  const ceoCommandUrl = opts.ceoCommandUrl;
  const approveUrl = opts.approveUrl || "/api/ai-ops/approval/approve";
  const headers = opts.headers || {};

  return {
    sendCommand: async (
      req: CeoCommandRequest,
      signal?: AbortSignal,
      onPartial?: (partial: NormalizedConsoleResponse) => void
    ): Promise<NormalizedConsoleResponse> => {
      const p1 = buildPayload(ceoCommandUrl, req);
      const n1 = await fetchAndNormalize({
        url: ceoCommandUrl,
        payload: p1,
        signal,
        headers,
        onPartial,
      });

      // fallback samo ako NEMA execution/approval wrapper
      const raw1: any = (n1 as any)?.raw ?? {};
      const hasExecOrApproval = hasExecutionOrApproval(raw1);

      const noProposals = !n1.proposed_commands || n1.proposed_commands.length === 0;
      const noText = !isNonEmptyString(n1.systemText);

      if (!hasExecOrApproval && (noProposals || noText) && !isChatEndpoint(ceoCommandUrl)) {
        const chatUrl = deriveChatUrl(ceoCommandUrl);
        const p2 = buildPayload(chatUrl, req);
        const n2 = await fetchAndNormalize({
          url: chatUrl,
          payload: p2,
          signal,
          headers,
          onPartial,
        });

        const chatHasProposals = !!(n2.proposed_commands && n2.proposed_commands.length > 0);
        const chatHasText = isNonEmptyString(n2.systemText);

        if (chatHasProposals || (noText && chatHasText)) {
          return n2;
        }
      }

      return n1;
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

      // 1) pokušaj canonical endpoint (ako postoji u backendu)
      try {
        const res = await fetch(url, {
          method: "GET",
          headers: { ...(headers || {}) },
          signal,
        });

        if (res.ok) {
          const raw = await fetchJsonOrText(res);
          if (raw && typeof raw === "object") {
            const dbs = (raw as any).databases;
            if (dbs && typeof dbs === "object") {
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
            }
          }
        }
      } catch {
        // ignore -> fallback
      }

      // 2) fallback: inventory -> snapshot metadata.databases
      const invPayload = buildPayload(ceoCommandUrl, {
        text: "inventory",
        initiator: "ceo_dashboard",
      });

      const res2 = await fetch(ceoCommandUrl, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...(headers || {}) },
        body: JSON.stringify(invPayload),
        signal,
      });

      if (!res2.ok) {
        const txt = await res2.text().catch(() => "");
        throw new Error(`HTTP ${res2.status} from ${ceoCommandUrl} (inventory fallback): ${txt || res2.statusText}`);
      }

      const raw2 = await fetchJsonOrText(res2);
      const dbs2 = extractDatabasesFromSnapshot(raw2);

      return {
        ok: true,
        read_only: true,
        databases: dbs2,
      };
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

      if (res.ok) {
        return await fetchJsonOrText(res);
      }

      // tolerant retry: flat body (db_key/filter/page_size...) ako backend očekuje jedan query
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

        if (res2.ok) {
          return await fetchJsonOrText(res2);
        }

        const txt2 = await res2.text().catch(() => "");
        throw new Error(`HTTP ${res2.status} from ${url} (flat retry): ${txt2 || res2.statusText}`);
      }

      const txt = await res.text().catch(() => "");
      throw new Error(`HTTP ${res.status} from ${url}: ${txt || res.statusText}`);
    },
  };
}
