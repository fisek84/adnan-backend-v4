// gateway/frontend/src/components/ceoChat/api.ts
//
// Cilj:
// - UI mora uvijek dobiti proposed_commands (ako ih backend vrati).
// - Ako /api/ceo/command ne vraća proposals (poznato ponašanje), automatski fallback na /api/chat.
// - Podržati AbortSignal iz CeoChatbox-a (api.sendCommand(req, controller.signal)).
// - Ne oslanjati se na krhke TS kontrakte (req.text vs req.input_text): tolerantan mapping.

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
  systemText?: string;
  summary?: string;
  proposed_commands?: ProposedCommand[];
  governance?: GovernanceCard;
  raw?: any;
  source_endpoint?: string;
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
  ];

  for (const c of candidates) {
    if (Array.isArray(c)) return c as ProposedCommand[];
  }
  return [];
}

function extractApprovalId(raw: any): string | undefined {
  const v = raw?.approval_request_id ?? raw?.approvalId ?? raw?.approval_id ?? raw?.approvalID;
  return isNonEmptyString(v) ? v.trim() : undefined;
}

function deriveGovernance(raw: any, proposed: ProposedCommand[]): GovernanceCard | undefined {
  const approvalId = extractApprovalId(raw);

  if (approvalId) {
    return {
      state: "BLOCKED",
      title: "Approval required",
      summary:
        asString(raw?.summary) ||
        asString(raw?.text) ||
        "Execution is blocked until CEO approval.",
      approvalRequestId: approvalId,
      proposals: proposed.length ? proposed : undefined,
    };
  }

  if (proposed.length) {
    return {
      state: "BLOCKED",
      title: "Proposals",
      summary: asString(raw?.summary) || asString(raw?.text) || "Agent returned proposed commands.",
      proposals: proposed,
    };
  }

  return undefined;
}

function normalizeResponse(raw: any, sourceEndpoint: string): NormalizedConsoleResponse {
  const proposed = extractProposedCommands(raw);

  const systemText =
    (isNonEmptyString(raw?.text) && raw.text.trim()) ||
    (isNonEmptyString(raw?.summary) && raw.summary.trim()) ||
    "";

  const normalized: NormalizedConsoleResponse = {
    systemText: systemText || undefined,
    summary: isNonEmptyString(raw?.summary) ? raw.summary.trim() : undefined,
    proposed_commands: proposed.length ? proposed : undefined,
    governance: deriveGovernance(raw, proposed),
    raw,
    source_endpoint: sourceEndpoint,
  };

  return normalized;
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

async function fetchJson(url: string, payload: any, signal?: AbortSignal, headers?: Record<string, string>) {
  const res = await fetch(url, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(headers || {}),
    },
    body: JSON.stringify(payload),
    signal,
  });

  const contentType = res.headers.get("content-type") || "";

  if (!res.ok) {
    const txt = await res.text().catch(() => "");
    throw new Error(`HTTP ${res.status} from ${url}: ${txt || res.statusText}`);
  }

  if (contentType.includes("text/event-stream")) {
    const txt = await res.text().catch(() => "");
    return { raw: { text: txt }, contentType };
  }

  const raw = await res.json().catch(async () => {
    const txt = await res.text().catch(() => "");
    return { text: txt };
  });

  return { raw, contentType };
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
      _onPartial?: (partial: NormalizedConsoleResponse) => void
    ): Promise<NormalizedConsoleResponse> => {
      // 1) Primary endpoint
      const p1 = buildPayload(ceoCommandUrl, req);
      const r1 = await fetchJson(ceoCommandUrl, p1, signal, headers);
      let n1 = normalizeResponse(r1.raw, ceoCommandUrl);

      // 2) Fallback: ako ceo endpoint ne vrati proposals → probaj /api/chat
      const noProposals = !n1.proposed_commands || n1.proposed_commands.length === 0;

      if (noProposals && !isChatEndpoint(ceoCommandUrl)) {
        const chatUrl = deriveChatUrl(ceoCommandUrl);
        const p2 = buildPayload(chatUrl, req);
        const r2 = await fetchJson(chatUrl, p2, signal, headers);
        const n2 = normalizeResponse(r2.raw, chatUrl);

        const chatHasProposals = !!(n2.proposed_commands && n2.proposed_commands.length > 0);
        const chatHasText = !!n2.systemText;

        if (chatHasProposals || chatHasText) {
          n1 = n2;
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
