// gateway/frontend/src/components/ceoChat/api.ts
//
// Cilj:
// - UI mora uvijek dobiti proposed_commands (ako ih backend vrati).
// - Ako /api/ceo/command ne vraća proposals (poznato ponašanje), automatski fallback na /api/chat.
// - Podržati AbortSignal iz CeoChatbox-a (api.sendCommand(req, controller.signal)).
// - Ne oslanjati se na krhke TS kontrakte (req.text vs req.input_text): tolerantan mapping.
// - KORISTITI normalize.ts (normalizeConsoleResponse + streaming) da promjene stvarno utiču na UI.
//
// Napomena (bitno za tvoj bug):
// - NE RADITI fallback na /api/chat ako primarni odgovor već sadrži execution/approve payload
//   (npr. execution_state/approval). U tom slučaju /api/chat često vraća “NEMA DOVOLJNO...”
//   i pregazi ispravan rezultat.

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

  // optional compatibility fields (ne mora se koristiti u UI, ali pomaže)
  summary?: string;
  proposed_commands?: ProposedCommand[];

  governance?: GovernanceCard;

  // debug / trace
  raw?: any;
  source_endpoint?: string;
  stream?: AsyncIterable<string>;
};

export type CeoCommandRequest = {
  // tolerantan: UI može slati text ili input_text
  text?: string;
  input_text?: string;

  initiator?: string;
  session_id?: string | null;

  // tolerantan: context_hint/smart_context su “UI hintovi”
  context_hint?: Record<string, any> | null;
  smart_context?: Record<string, any> | null;

  // dopuštamo dodatna polja
  [k: string]: any;
};

export type CeoConsoleApi = {
  sendCommand: (
    req: CeoCommandRequest,
    signal?: AbortSignal,
    onPartial?: (partial: NormalizedConsoleResponse) => void
  ) => Promise<NormalizedConsoleResponse>;
  approve: (approvalRequestId: string, signal?: AbortSignal) => Promise<any>;
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
  // ako je absolute URL, samo zamijeni path
  if (/^https?:\/\//i.test(fromCeoCommandUrl)) {
    try {
      return new URL("/api/chat", fromCeoCommandUrl).toString();
    } catch {
      return "/api/chat";
    }
  }
  return "/api/chat";
}

function extractProposedCommands(raw: any): ProposedCommand[] {
  if (!raw || typeof raw !== "object") return [];

  // tražimo proposals kroz više mogućih wrappera
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

function mergeGovernance(
  baseGov: any | undefined,
  raw: any,
  proposed: ProposedCommand[]
): GovernanceCard | undefined {
  const approvalId = extractApprovalId(raw);

  // start from normalize.ts governance if it exists
  const g: GovernanceCard | undefined = baseGov
    ? {
        state: asString(baseGov.state) || asString(baseGov.status) || "BLOCKED",
        title: asString(baseGov.title) || "Governance",
        summary: isNonEmptyString(baseGov.summary) ? baseGov.summary : undefined,
        reasons: Array.isArray(baseGov.reasons) ? baseGov.reasons : undefined,
        approvalRequestId: isNonEmptyString(baseGov.approvalRequestId) ? baseGov.approvalRequestId : undefined,
      }
    : undefined;

  // ensure approvalRequestId if present anywhere
  if (approvalId) {
    if (g) g.approvalRequestId = g.approvalRequestId ?? approvalId;
  }

  // ensure proposals are present for UI buttons
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

  // optional summary compatibility (if backend returns it)
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

  // /api/ceo/command (wrappers) – šaljemo više alias-a radi kompatibilnosti
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

  // approve/execute wrapperi: često dolazi kao { execution_state, execution_id, approval: {...} }
  const hasApprovalObj = !!raw?.approval;

  return (
    isNonEmptyString(execState) ||
    isNonEmptyString(execId) ||
    isNonEmptyString(approvalId) ||
    hasApprovalObj
  );
}

async function fetchAndNormalize(opts: {
  url: string;
  payload: any;
  signal?: AbortSignal;
  headers?: Record<string, string>;
  onPartial?: (partial: NormalizedConsoleResponse) => void;
}): Promise<NormalizedConsoleResponse> {
  const { url, payload, signal, headers, onPartial } = opts;

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

  // Streaming support (SSE/NDJSON)
  const stream = streamTextFromResponse(res);
  if (stream) {
    let acc = "";
    try {
      for await (const chunk of stream) {
        acc += chunk;
        onPartial?.({
          systemText: acc,
          stream,
          raw: { delta: chunk },
          source_endpoint: url,
        });
      }
    } catch {
      // ignore streaming parse errors; we still return accumulated
    }

    // Return a terminal normalized response
    return {
      systemText: acc.trim() || undefined,
      raw: { text: acc },
      source_endpoint: url,
    };
  }

  // Non-streaming JSON
  const raw = await res.json().catch(async () => {
    const txt = await res.text().catch(() => "");
    return { text: txt };
  });

  return normalizeRawToUi(raw, url, res.headers);
}

export function createCeoConsoleApi(opts: {
  ceoCommandUrl: string;
  approveUrl: string;
  headers?: Record<string, string>;
}): CeoConsoleApi {
  const ceoCommandUrl = opts.ceoCommandUrl;
  const approveUrl = opts.approveUrl;
  const headers = opts.headers || {};

  return {
    sendCommand: async (
      req: CeoCommandRequest,
      signal?: AbortSignal,
      onPartial?: (partial: NormalizedConsoleResponse) => void
    ): Promise<NormalizedConsoleResponse> => {
      // 1) Primary endpoint
      const p1 = buildPayload(ceoCommandUrl, req);
      const n1 = await fetchAndNormalize({
        url: ceoCommandUrl,
        payload: p1,
        signal,
        headers,
        onPartial,
      });

      // 2) Fallback: samo ako primarni odgovor NIJE execution/approval payload
      // (da /api/chat ne pregazi stvarni execution rezultat)
      const raw1: any = (n1 as any)?.raw ?? {};
      const hasExecOrApproval = hasExecutionOrApproval(raw1);

      const noProposals = !n1.proposed_commands || n1.proposed_commands.length === 0;
      const noText = !isNonEmptyString(n1.systemText);

      // fallback je smislen samo ako fali i tekst i proposals, i nemamo execution/approval wrapper
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

        // prefer chat if it adds value
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

      return await res.json().catch(async () => {
        const txt = await res.text().catch(() => "");
        return { text: txt };
      });
    },
  };
}
