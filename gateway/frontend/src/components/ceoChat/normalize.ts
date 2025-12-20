import type { GovernanceState, NormalizedConsoleResponse } from "./types";

const asString = (v: unknown): string | undefined => (typeof v === "string" ? v : undefined);
const asArrayOfStrings = (v: unknown): string[] | undefined =>
  Array.isArray(v) && v.every((x) => typeof x === "string") ? (v as string[]) : undefined;

const normalizeState = (v: unknown): GovernanceState | undefined => {
  const s = asString(v)?.toUpperCase();
  if (s === "BLOCKED" || s === "APPROVED" || s === "EXECUTED") return s;
  return undefined;
};

const redactAgentDetails = (text: string): string => {
  // Minimal redaction: strips obvious executor/agent sections without guessing schema.
  // Keeps content readable while avoiding "agent execution details".
  const lines = text.split("\n");
  const filtered = lines.filter((l) => {
    const ll = l.toLowerCase();
    if (ll.includes("executor:") || ll.includes("agent:") || ll.includes("tool_call") || ll.includes("tool call")) return false;
    if (ll.includes("openai_assistant") || ll.includes("assistant id") || ll.includes("notion sdk")) return false;
    return true;
  });
  return filtered.join("\n").trim();
};

function* ndjsonIterator(body: ReadableStream<Uint8Array>): Generator<Promise<string | null>, void, unknown> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    yield (async () => {
      const { value, done } = await reader.read();
      if (done) return null;
      buffer += decoder.decode(value, { stream: true });
      const idx = buffer.indexOf("\n");
      if (idx === -1) return "";
      const line = buffer.slice(0, idx).trim();
      buffer = buffer.slice(idx + 1);
      return line;
    })();
  }
}

async function* parseNdjsonText(body: ReadableStream<Uint8Array>): AsyncIterable<string> {
  for (const next of ndjsonIterator(body)) {
    const line = await next;
    if (line === null) break;
    if (!line) continue;

    // Best-effort: either raw text lines or JSON with {delta|text|content}
    try {
      const obj = JSON.parse(line) as any;
      const delta = asString(obj?.delta) ?? asString(obj?.text) ?? asString(obj?.content);
      if (delta) yield delta;
    } catch {
      yield line;
    }
  }
}

async function* parseSseText(body: ReadableStream<Uint8Array>): AsyncIterable<string> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    // SSE frames separated by double newline
    let splitIndex = buffer.indexOf("\n\n");
    while (splitIndex !== -1) {
      const frame = buffer.slice(0, splitIndex);
      buffer = buffer.slice(splitIndex + 2);

      // Collect all `data:` lines
      const dataLines = frame
        .split("\n")
        .map((l) => l.trimEnd())
        .filter((l) => l.startsWith("data:"))
        .map((l) => l.slice(5).trimStart());

      for (const dl of dataLines) {
        if (!dl || dl === "[DONE]") continue;
        try {
          const obj = JSON.parse(dl) as any;
          const delta = asString(obj?.delta) ?? asString(obj?.text) ?? asString(obj?.content);
          if (delta) yield delta;
        } catch {
          yield dl;
        }
      }

      splitIndex = buffer.indexOf("\n\n");
    }
  }
}

export const normalizeConsoleResponse = (raw: unknown, responseHeaders?: Headers): NormalizedConsoleResponse => {
  // JSON response normalization (best-effort, schema-tolerant).
  const obj = (raw && typeof raw === "object") ? (raw as any) : {};

  const requestId =
    asString(obj?.request_id) ??
    asString(obj?.requestId) ??
    asString(obj?.client_request_id) ??
    asString(obj?.meta?.request_id) ??
    asString(obj?.meta?.requestId);

  // Candidate system text fields
  const sysText =
    asString(obj?.system_text) ??
    asString(obj?.systemText) ??
    asString(obj?.message) ??
    asString(obj?.response) ??
    asString(obj?.text) ??
    asString(obj?.content) ??
    asString(obj?.ai_response?.text) ??
    asString(obj?.ai_response?.message) ??
    asString(obj?.aiResponse?.text);

  // Governance candidates
  const g = obj?.governance ?? obj?.governance_state ?? obj?.governanceState ?? obj?.approval ?? obj?.status;
  const gState =
    normalizeState(obj?.governance?.state) ??
    normalizeState(obj?.governance_state?.state) ??
    normalizeState(obj?.governanceState?.state) ??
    normalizeState(obj?.status) ??
    normalizeState(obj?.state) ??
    normalizeState(g?.state);

  const approvalRequestId =
    asString(obj?.approval_request_id) ??
    asString(obj?.approvalRequestId) ??
    asString(obj?.governance?.approval_request_id) ??
    asString(obj?.governance?.approvalRequestId) ??
    asString(obj?.governance_state?.approval_request_id) ??
    asString(obj?.governance_state?.approvalRequestId);

  const reasons =
    asArrayOfStrings(obj?.reasons) ??
    asArrayOfStrings(obj?.governance?.reasons) ??
    asArrayOfStrings(obj?.governance_state?.reasons) ??
    asArrayOfStrings(obj?.governance?.block_reasons) ??
    asArrayOfStrings(obj?.governance_state?.block_reasons);

  const title =
    asString(obj?.governance?.title) ??
    asString(obj?.governance_state?.title) ??
    asString(obj?.title);

  const summary =
    asString(obj?.governance?.summary) ??
    asString(obj?.governance_state?.summary) ??
    asString(obj?.summary);

  const systemText = sysText ? redactAgentDetails(sysText) : undefined;

  const normalized: NormalizedConsoleResponse = {
    requestId,
    systemText,
  };

  if (gState) {
    normalized.governance = {
      state: gState,
      title,
      summary,
      reasons,
      approvalRequestId,
    };
  }

  // Streaming is handled by api.ts based on content-type; keep normalize pure.
  void responseHeaders;

  return normalized;
};

export const detectStreamParser = (headers: Headers | undefined) => {
  const ct = headers?.get("content-type")?.toLowerCase() ?? "";
  if (ct.includes("text/event-stream")) return "sse" as const;
  if (ct.includes("application/x-ndjson") || ct.includes("application/ndjson")) return "ndjson" as const;
  return null;
};

export const streamTextFromResponse = (res: Response): AsyncIterable<string> | null => {
  const mode = detectStreamParser(res.headers);
  if (!mode || !res.body) return null;
  return mode === "sse" ? parseSseText(res.body) : parseNdjsonText(res.body);
};
