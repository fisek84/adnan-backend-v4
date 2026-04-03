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
// - daje helper metode za Notion Ops read/search (GET /api/notion-ops/databases, POST /api/notion-ops/bulk/query)
// - NEW: daje helper metodu za Notion page read (POST /api/notion/read) — SAFE READ

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

type StructuredPreviewPayload = {
  command?: Record<string, any>;
  review?: Record<string, any>;
  notion?: Record<string, any>;
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

// ------------------------------
// Notion Read (page by title) — SAFE READ
// ------------------------------
export type NotionReadResponse =
  | {
      ok: true;
      title: string;
      notion_url: string;
      content_markdown: string;
      [k: string]: any;
    }
  | {
      ok: false;
      error: string;
      [k: string]: any;
    };

export type CeoConsoleApi = {
  sendCommand: (
    req: CeoCommandRequest,
    signal?: AbortSignal,
    onPartial?: (partial: NormalizedConsoleResponse) => void,
    opts?: { forceNonStreaming?: boolean }
  ) => Promise<NormalizedConsoleResponse>;

  // Voice adapter endpoint (STT optional on client; TTS optional on server).
  // This remains additive: text flow stays on /api/chat.
  sendVoiceExecText: (
    req: CeoCommandRequest,
    signal?: AbortSignal,
    opts?: { forceHttp?: boolean }
  ) => Promise<NormalizedConsoleResponse>;

  approve: (approvalRequestId: string, signal?: AbortSignal) => Promise<any>;

  // Notion bulk ops (read/search)
  listNotionDatabases: (signal?: AbortSignal) => Promise<NotionDatabasesResponse>;
  notionBulkQuery: (payload: NotionBulkQueryPayload, signal?: AbortSignal) => Promise<any>;

  // Notion page read (SAFE)
  notionReadPageByTitle: (query: string, signal?: AbortSignal) => Promise<NotionReadResponse>;
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

function deriveChatStreamUrl(fromBaseUrl: string): string {
  // Always derive an /api/chat/stream URL (relative or absolute) from the configured base.
  return deriveApiUrl(fromBaseUrl, "/chat/stream");
}

function deriveNotionOpsUrl(fromBaseUrl: string, path: string): string {
  const p = path.startsWith("/") ? path : `/${path}`;

  // FIX:
  // Notion Ops endpointi moraju ići kroz /api prefiks, bez obzira da li je base relative ili absolute.
  // - relative base: "/api/chat" -> "/api/notion-ops/..."
  // - absolute base: "https://host/api/chat" -> "https://host/api/notion-ops/..."
  if (!/^https?:\/\//i.test(fromBaseUrl)) return `/api${p}`;

  try {
    const base = new URL(fromBaseUrl);
    const apiPath = `/api${p}`;
    return new URL(apiPath, base.origin).toString();
  } catch {
    return `/api${p}`;
  }
}

// General helper: derive any /api/* URL based on ceoCommandUrl (relative or absolute)
function deriveApiUrl(fromBaseUrl: string, apiPathWithoutPrefix: string): string {
  const p = apiPathWithoutPrefix.startsWith("/") ? apiPathWithoutPrefix : `/${apiPathWithoutPrefix}`;

  if (!/^https?:\/\//i.test(fromBaseUrl)) return `/api${p}`;

  try {
    const base = new URL(fromBaseUrl);
    const apiPath = `/api${p}`;
    return new URL(apiPath, base.origin).toString();
  } catch {
    return `/api${p}`;
  }
}

function deriveWsApiUrl(
  fromBaseUrl: string,
  apiPathWithoutPrefix: string,
  query?: Record<string, string | undefined>
): string {
  const p = apiPathWithoutPrefix.startsWith("/") ? apiPathWithoutPrefix : `/${apiPathWithoutPrefix}`;
  const apiPath = `/api${p}`;

  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(query || {})) {
    if (typeof v === "string" && v.trim()) qs.set(k, v);
  }
  const q = qs.toString();
  const suffix = q ? `?${q}` : "";

  // Absolute base URL -> convert protocol to ws/wss
  if (/^https?:\/\//i.test(fromBaseUrl)) {
    try {
      const base = new URL(fromBaseUrl);
      const proto = base.protocol.toLowerCase() === "https:" ? "wss:" : "ws:";
      return `${proto}//${base.host}${apiPath}${suffix}`;
    } catch {
      // fallthrough
    }
  }

  // Relative base URL -> best-effort use window.location when available.
  try {
    const loc = (globalThis as any)?.location;
    const protocol = String(loc?.protocol || "").toLowerCase();
    const host = String(loc?.host || "");
    if (host) {
      const proto = protocol === "https:" ? "wss:" : "ws:";
      return `${proto}//${host}${apiPath}${suffix}`;
    }
  } catch {
    // ignore
  }

  // Last resort: return a path URL (browser may resolve it).
  return `${apiPath}${suffix}`;
}

function streamTextFromVoiceRealtimeWebSocket(opts: {
  wsUrl: string;
  text: string;
  sessionId?: string | null;
  conversationId?: string | null;
  preferredAgentId?: string | null;
  outputLang?: string | null;
  contextHint?: any;
  identityPack?: Record<string, any> | null;
  metadata?: Record<string, any> | null;
  signal?: AbortSignal;
}): AsyncIterable<string> {
  let resolveFinal: (v: any) => void = () => undefined;
  let rejectFinal: (e: any) => void = () => undefined;
  const finalResponse = new Promise<any>((resolve, reject) => {
    resolveFinal = resolve;
    rejectFinal = reject;
  });

  let finalSettled = false;
  let finalRaw: any = null;

  const gen = (async function* () {
    const { wsUrl, signal } = opts;
    const WS: any = (globalThis as any)?.WebSocket;
    if (typeof WS !== "function") {
      throw new Error("WebSocket not supported");
    }

    const ws: any = new WS(wsUrl);

    const queue: any[] = [];
    let wake: (() => void) | null = null;
    let closed = false;
    let closeEvent: any = null;

    const nextMessage = async (): Promise<any> => {
      while (queue.length === 0) {
        if (closed) return null;
        await new Promise<void>((resolve) => {
          wake = resolve;
        });
      }
      return queue.shift();
    };

    const finishWithError = (err: any) => {
      if (!finalSettled) {
        finalSettled = true;
        rejectFinal(err);
      }
      throw err;
    };

    const onAbort = () => {
      const err = new Error("aborted");
      (err as any).name = "AbortError";
      try {
        ws.close?.(1000, "aborted");
      } catch {
        // ignore
      }
      if (!finalSettled) {
        finalSettled = true;
        rejectFinal(err);
      }
    };

    if (signal) {
      if (signal.aborted) onAbort();
      signal.addEventListener("abort", onAbort, { once: true });
    }

    await new Promise<void>((resolve, reject) => {
      ws.onopen = () => resolve();
      ws.onerror = () => reject(new Error("WebSocket connection failed"));
      ws.onclose = (ev: any) => {
        closed = true;
        closeEvent = ev;
        if (wake) {
          const w = wake;
          wake = null;
          w();
        }
      };
      ws.onmessage = (ev: any) => {
        queue.push(ev?.data);
        if (wake) {
          const w = wake;
          wake = null;
          w();
        }
      };
    });

    const sessionId = String(opts.sessionId || "").trim() || `ws_session_${Date.now()}`;
    const conversationId = String(opts.conversationId || "").trim() || sessionId;

    ws.send(
      JSON.stringify({
        type: "session.start",
        data: { session_id: sessionId, conversation_id: conversationId },
      })
    );

    ws.send(
      JSON.stringify({
        type: "input.final",
        data: {
          text: opts.text,
          preferred_agent_id: opts.preferredAgentId || undefined,
          output_lang: opts.outputLang || undefined,
          context_hint: opts.contextHint ?? undefined,
          identity_pack: opts.identityPack ?? undefined,
          metadata: opts.metadata ?? undefined,
          // Ask server to include additive voice_output when VOICE_TTS_ENABLED is on.
          want_voice_output: true,
        },
      })
    );

    try {
      while (true) {
        if (signal?.aborted) {
          finishWithError(Object.assign(new Error("aborted"), { name: "AbortError" }));
        }

        const raw = await nextMessage();
        if (raw == null) {
          const code = closeEvent?.code;
          const reason = closeEvent?.reason;
          const err = new Error(
            typeof reason === "string" && reason.trim()
              ? reason
              : `WebSocket closed${typeof code === "number" ? ` (${code})` : ""}`
          );
          (err as any).closeCode = code;
          throw err;
        }

        const evt = typeof raw === "string" ? JSON.parse(raw) : raw;
        const type = String(evt?.type || "");

        if (type === "assistant.delta") {
          const delta = evt?.data?.delta_text;
          if (typeof delta === "string" && delta) yield delta;
          continue;
        }

        if (type === "assistant.final") {
          finalRaw = evt?.data?.response ?? evt?.data ?? null;
          if (!finalSettled) {
            finalSettled = true;
            resolveFinal(finalRaw);
          }
          continue;
        }

        if (type === "error") {
          const msg =
            typeof evt?.data?.message === "string" && evt.data.message.trim()
              ? evt.data.message.trim()
              : "Stream error";
          const err = new Error(msg);
          (err as any).code = evt?.data?.code;
          (err as any).httpStatus = evt?.data?.http_status;
          finishWithError(err);
        }

        if (type === "done") {
          if (!finalSettled) {
            finalSettled = true;
            resolveFinal(finalRaw);
          }
          try {
            ws.close?.(1000, "done");
          } catch {
            // ignore
          }
          return;
        }

        // Ignore other event types for forward-compat.
      }
    } catch (e) {
      if (!finalSettled) {
        finalSettled = true;
        rejectFinal(e);
      }
      throw e;
    } finally {
      try {
        if (signal) signal.removeEventListener("abort", onAbort);
      } catch {
        // ignore
      }
      try {
        ws.close?.(1000, "cleanup");
      } catch {
        // ignore
      }
    }
  })();

  (gen as any).finalResponse = finalResponse;
  return gen;
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
    if (Array.isArray(c)) {
      return attachStructuredPreviewToCommands(
        c as ProposedCommand[],
        raw,
      );
    }
  }
  return [];
}

function extractStructuredPreviewPayload(raw: any): StructuredPreviewPayload | null {
  if (!raw || typeof raw !== "object") return null;

  const command = raw.command;
  const review = raw.review;
  const notion = raw.notion;

  if (
    (!command || typeof command !== "object" || Array.isArray(command)) &&
    (!review || typeof review !== "object" || Array.isArray(review)) &&
    (!notion || typeof notion !== "object" || Array.isArray(notion))
  ) {
    return null;
  }

  return {
    ...(command && typeof command === "object" && !Array.isArray(command) ? { command } : {}),
    ...(review && typeof review === "object" && !Array.isArray(review) ? { review } : {}),
    ...(notion && typeof notion === "object" && !Array.isArray(notion) ? { notion } : {}),
  };
}

export function attachStructuredPreviewToCommands<T extends ProposedCommand>(
  commands: T[],
  raw: any
): T[] {
  const attachedPreview = extractStructuredPreviewPayload(raw);
  if (!attachedPreview || !Array.isArray(commands) || commands.length === 0) {
    return commands;
  }

  return commands.map((command) => {
    if (!command || typeof command !== "object" || Array.isArray(command)) {
      return command;
    }
    const next = { ...command };
    Object.defineProperty(next, "__attachedPreview", {
      value: attachedPreview,
      enumerable: false,
      configurable: true,
    });
    return next as T;
  });
}

export function getAttachedPreviewPayload(command: any): StructuredPreviewPayload | null {
  const attachedPreview = command?.__attachedPreview;
  if (
    !attachedPreview ||
    typeof attachedPreview !== "object" ||
    Array.isArray(attachedPreview)
  ) {
    return null;
  }
  return attachedPreview as StructuredPreviewPayload;
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

  // CHANGED: default initiator to chat (prevents dashboard-mode defaults if caller forgot to set it)
  const initiator = (req as any)?.initiator || "ceo_chat";
  const session_id = (req as any)?.session_id ?? null;

  // /api/chat shape (AgentRouter / canon)
  if (isChatEndpoint(endpointUrl)) {
    const ctx = ((req as any)?.context_hint ?? {}) as Record<string, any>;
    const preferred =
      (typeof ctx.preferred_agent_id === "string" && ctx.preferred_agent_id.trim()) ||
      (typeof ctx.agent_id === "string" && ctx.agent_id.trim()) ||
      "ceo_advisor";

    const uiOutputLang =
      (req as any)?.output_lang ||
      (ctx as any)?.ui_output_lang ||
      (req as any)?.metadata?.ui_output_lang ||
      null;

    return {
      message: text,
      preferred_agent_id: preferred,
      // Important for Notion Ops ARMED gate: backend extracts session_id from either
      // payload.session_id or payload.metadata.session_id.
      session_id,
      metadata: {
        initiator,
        session_id,
        source: "ceoChatbox",
        context_hint: (req as any)?.context_hint ?? null,
        smart_context: (req as any)?.smart_context ?? null,
        ui_output_lang: uiOutputLang,
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
    session_id,
    context_hint: (req as any)?.context_hint ?? null,
    smart_context: (req as any)?.smart_context ?? null,
  };
}

function buildVoiceExecTextPayload(req: CeoCommandRequest): any {
  const text = extractText(req);

  const initiator = (req as any)?.initiator || "ceo_chat";
  const session_id = (req as any)?.session_id ?? null;

  const ctx = ((req as any)?.context_hint ?? {}) as Record<string, any>;
  const preferred =
    (typeof ctx.preferred_agent_id === "string" && ctx.preferred_agent_id.trim()) ||
    (typeof ctx.agent_id === "string" && ctx.agent_id.trim()) ||
    "ceo_advisor";

  const uiOutputLang =
    (req as any)?.output_lang ||
    (ctx as any)?.ui_output_lang ||
    (req as any)?.metadata?.ui_output_lang ||
    null;

  const voiceProfiles = (req as any)?.metadata?.voice_profiles ?? null;

  return {
    text,
    preferred_agent_id: preferred,
    session_id,
    output_lang: uiOutputLang,
    context_hint: (req as any)?.context_hint ?? null,
    metadata: {
      initiator,
      session_id,
      source: "ceoChatbox",
      context_hint: (req as any)?.context_hint ?? null,
      smart_context: (req as any)?.smart_context ?? null,
      ui_output_lang: uiOutputLang,
      ...(voiceProfiles ? { voice_profiles: voiceProfiles } : {}),
    },
    // Explicitly request additive backend audio output if enabled server-side.
    want_voice_output: true,
  };
}

async function fetchJsonOrText(res: Response): Promise<any> {
  // pokušaj json, fallback na text
  return await res.json().catch(async () => {
    const txt = await res.text().catch(() => "");
    return { text: txt };
  });
}

// ✅ Streaming must be explicit (SSE/NDJSON), otherwise normalize JSON.
// This prevents raw={stream:true} and systemText=<missing> in UI.
function isExplicitStreamingResponse(res: Response): boolean {
  const ct = String(res.headers.get("content-type") || "").toLowerCase();
  return (
    ct.includes("text/event-stream") ||
    ct.includes("application/x-ndjson") ||
    ct.includes("application/ndjson")
  );
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

  // ✅ FIX: only treat as stream if server explicitly returns streaming content-type.
  if (isExplicitStreamingResponse(res)) {
    const stream = streamTextFromResponse(res);
    if (stream) {
      return {
        stream,
        raw: { stream: true },
        source_endpoint: url,
      };
    }
  }

  const raw = await fetchJsonOrText(res);

  return normalizeRawToUi(raw, url, res.headers);
}

function coerceNotionReadResponse(raw: any): NotionReadResponse {
  // Expected:
  // { ok: true, title, notion_url, content_markdown }
  // or { ok: false, error }
  if (!raw || typeof raw !== "object") {
    return { ok: false, error: "Invalid response shape." };
  }

  if (raw.ok === true) {
    const title = typeof raw.title === "string" ? raw.title : "";
    const notionUrl = typeof raw.notion_url === "string" ? raw.notion_url : "";
    const md = typeof raw.content_markdown === "string" ? raw.content_markdown : "";

    return {
      ok: true,
      title,
      notion_url: notionUrl,
      content_markdown: md,
    };
  }

  const err =
    typeof raw.error === "string"
      ? raw.error
      : typeof raw.message === "string"
        ? raw.message
        : "Document not found.";
  return { ok: false, error: err };
}

export function createCeoConsoleApi(opts: {
  ceoCommandUrl: string; // SHOULD be "/api/chat" per CANON
  approveUrl?: string; // default "/api/ai-ops/approval/approve"
  headers?: Record<string, string>;
}): CeoConsoleApi {
  const ceoCommandUrl = opts.ceoCommandUrl;
  const approveUrl = opts.approveUrl || "/api/ai-ops/approval/approve";
  const headers = opts.headers || {};

  return {
    // CANON: single source of truth for chat is /api/chat (no fallback to other endpoints).
    sendCommand: async (
      req: CeoCommandRequest,
      signal?: AbortSignal,
      _onPartial?: (partial: NormalizedConsoleResponse) => void,
      opts2?: { forceNonStreaming?: boolean }
    ): Promise<NormalizedConsoleResponse> => {
      const payload = buildPayload(ceoCommandUrl, req);

      // Stream-first for chat, with strict fallback:
      // - Only fallback when stream endpoint is disabled/unavailable (404).
      // - Any other error should surface (don’t hide server bugs).
      if (!opts2?.forceNonStreaming && isChatEndpoint(ceoCommandUrl)) {
        const streamUrl = deriveChatStreamUrl(ceoCommandUrl);
        try {
          return await fetchAndNormalize({
            url: streamUrl,
            payload,
            signal,
            headers,
          });
        } catch (e: any) {
          const msg = typeof e?.message === "string" ? e.message : String(e);
          if (msg.includes(`HTTP 404 from ${streamUrl}`)) {
            // Expected when CHAT_STREAMING_ENABLED is OFF.
          } else {
            throw e;
          }
        }
      }

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

    sendVoiceExecText: async (
      req: CeoCommandRequest,
      signal?: AbortSignal,
      opts2?: { forceHttp?: boolean }
    ): Promise<NormalizedConsoleResponse> => {
      const payload = buildVoiceExecTextPayload(req);

      // Prefer realtime WS when available; fall back to HTTP voice adapter.
      if (!opts2?.forceHttp && typeof (globalThis as any)?.WebSocket === "function") {
        const token =
          (headers as any)?.["X-CEO-Token"] ||
          (headers as any)?.["x-ceo-token"] ||
          (headers as any)?.["x-ceo_token"] ||
          undefined;

        const wsUrl = deriveWsApiUrl(ceoCommandUrl, "/voice/realtime/ws", {
          ceo_token: typeof token === "string" ? token : undefined,
        });

        const stream = streamTextFromVoiceRealtimeWebSocket({
          wsUrl,
          text: String(payload?.text || ""),
          sessionId: payload?.session_id ?? null,
          conversationId: (payload as any)?.conversation_id ?? null,
          preferredAgentId: payload?.preferred_agent_id ?? null,
          outputLang: (req as any)?.output_lang ?? null,
          contextHint: payload?.context_hint ?? null,
          identityPack: (req as any)?.identity_pack ?? null,
          metadata: payload?.metadata ?? null,
          signal,
        });

        return {
          stream,
          raw: { stream: true },
          source_endpoint: wsUrl,
        };
      }

      const url = deriveApiUrl(ceoCommandUrl, "/voice/exec_text");
      return await fetchAndNormalize({ url, payload, signal, headers });
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

    // NEW: Notion page read by title (SAFE READ)
    notionReadPageByTitle: async (query: string, signal?: AbortSignal): Promise<NotionReadResponse> => {
      const q = String(query ?? "").trim();
      if (!q) return { ok: false, error: "Query is empty." };

      const url = deriveApiUrl(ceoCommandUrl, "/notion/read");

      let res: Response;
      try {
        res = await fetch(url, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            ...(headers || {}),
          },
          body: JSON.stringify({ mode: "page_by_title", query: q }),
          signal,
        });
      } catch (e: any) {
        const msg = typeof e?.message === "string" ? e.message : String(e);
        return { ok: false, error: `Network error: ${msg}` };
      }

      const raw = await fetchJsonOrText(res);

      // For this READ endpoint we return {ok:false,error} instead of throwing,
      // so UI can show a user-friendly message.
      if (!res.ok) {
        const err =
          typeof raw?.error === "string"
            ? raw.error
            : typeof raw?.text === "string"
              ? raw.text
              : `HTTP ${res.status} from ${url}`;
        return { ok: false, error: err };
      }

      return coerceNotionReadResponse(raw);
    },
  };
}
