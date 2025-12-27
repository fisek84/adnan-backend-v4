// gateway/frontend/src/components/ceoChat/normalize.ts
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
  const lines = text.split("\n");
  const filtered = lines.filter((l) => {
    const ll = l.toLowerCase();
    if (ll.includes("executor:") || ll.includes("agent:") || ll.includes("tool_call") || ll.includes("tool call"))
      return false;
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

    let splitIndex = buffer.indexOf("\n\n");
    while (splitIndex !== -1) {
      const frame = buffer.slice(0, splitIndex);
      buffer = buffer.slice(splitIndex + 2);

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

const formatSection = (title: string, lines: string[]) => {
  const clean = (lines || []).map((x) => (typeof x === "string" ? x.trim() : "")).filter(Boolean);
  if (!clean.length) return "";
  return `${title}\n${clean.map((x) => `- ${x}`).join("\n")}`;
};

const deriveSystemTextFromCeoConsole = (obj: any): string | undefined => {
  // CEO Console canonical response: { summary, questions[], plan[], options[], proposed_commands[] }
  const summary = asString(obj?.summary) ?? asString(obj?.text) ?? asString(obj?.message);
  const questions = asArrayOfStrings(obj?.questions) ?? [];
  const plan = asArrayOfStrings(obj?.plan) ?? [];
  const options = asArrayOfStrings(obj?.options) ?? [];

  const proposed = Array.isArray(obj?.proposed_commands) ? obj.proposed_commands : [];
  const proposedLines =
    proposed.length > 0
      ? proposed
          .map((p: any, idx: number) => {
            const t = asString(p?.command_type) ?? asString(p?.command) ?? "";
            const risk = asString(p?.risk_hint) ?? asString(p?.risk) ?? "";
            const extra = [t || `Command #${idx + 1}`, risk ? `risk: ${risk}` : ""].filter(Boolean).join(" — ");
            return extra || `Command #${idx + 1}`;
          })
          .filter(Boolean)
      : [];

  const blocks: string[] = [];
  if (summary && summary.trim()) blocks.push(summary.trim());
  const planBlock = formatSection("Plan", plan);
  if (planBlock) blocks.push(planBlock);
  const optBlock = formatSection("Options", options);
  if (optBlock) blocks.push(optBlock);
  const qBlock = formatSection("Questions", questions);
  if (qBlock) blocks.push(qBlock);
  const pBlock = formatSection("Proposed commands (BLOCKED)", proposedLines);
  if (pBlock) blocks.push(pBlock);

  const out = blocks.join("\n\n").trim();
  return out || undefined;
};

export const normalizeConsoleResponse = (raw: unknown, responseHeaders?: Headers): NormalizedConsoleResponse => {
  const obj = raw && typeof raw === "object" ? (raw as any) : {};

  const requestId =
    asString(obj?.request_id) ??
    asString(obj?.requestId) ??
    asString(obj?.client_request_id) ??
    asString(obj?.meta?.request_id) ??
    asString(obj?.meta?.requestId) ??
    asString(obj?.trace?.request_id) ??
    asString(obj?.trace?.requestId);

  // Prefer CEO Console canonical formatting if present
  let sysText =
    deriveSystemTextFromCeoConsole(obj) ??
    asString(obj?.system_text) ??
    asString(obj?.systemText) ??
    asString(obj?.message) ??
    asString(obj?.response) ??
    asString(obj?.text) ??
    asString(obj?.content) ??
    asString(obj?.ai_response?.text) ??
    asString(obj?.ai_response?.message) ??
    asString(obj?.aiResponse?.text);

  // If approve/resume returns structured execution payload, surface something readable
  if (!sysText) {
    const execState =
      asString(obj?.execution_state) ?? asString(obj?.executionState) ?? asString(obj?.status) ?? asString(obj?.state);
    const ok = typeof obj?.ok === "boolean" ? obj.ok : undefined;
    const msg = asString(obj?.detail) ?? asString(obj?.error) ?? asString(obj?.message);
    const lines = [
      execState ? `Execution: ${execState}` : "",
      typeof ok === "boolean" ? `OK: ${ok ? "true" : "false"}` : "",
      msg ? `Message: ${msg}` : "",
    ].filter(Boolean);
    if (lines.length) sysText = lines.join("\n");
  }

  // Governance state derivation (best-effort)
  // CEO Console itself is read-only; proposals are inherently BLOCKED (no approval_id yet).
  const hasProposals = Array.isArray(obj?.proposed_commands) && obj.proposed_commands.length > 0;

  const gStateExplicit =
    normalizeState(obj?.governance?.state) ??
    normalizeState(obj?.governance_state?.state) ??
    normalizeState(obj?.governanceState?.state) ??
    normalizeState(obj?.status) ??
    normalizeState(obj?.state) ??
    normalizeState(obj?.governance?.status) ??
    normalizeState(obj?.approval?.status);

  let gState: GovernanceState | undefined = gStateExplicit;

  // If we have proposals, show BLOCKED governance card
  if (!gState && hasProposals) gState = "BLOCKED";

  // If execution completed/failed, mark as EXECUTED (UI uses EXECUTED for terminal)
  const executionState = asString(obj?.execution_state) ?? asString(obj?.executionState);
  if (!gState && executionState) {
    const up = executionState.toUpperCase();
    if (up === "COMPLETED" || up === "FAILED" || up === "ERROR") gState = "EXECUTED";
  }

  // Approval id normalization (backend uses approval_id)
  const approvalRequestId =
    asString(obj?.approval_id) ??
    asString(obj?.approvalId) ??
    asString(obj?.approval?.approval_id) ??
    asString(obj?.approval?.approvalId) ??
    asString(obj?.governance?.approval_id) ??
    asString(obj?.governance?.approvalId) ??
    asString(obj?.governance?.approval_request_id) ??
    asString(obj?.governance?.approvalRequestId) ??
    asString(obj?.governance_state?.approval_id) ??
    asString(obj?.governance_state?.approvalId) ??
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
    asString(obj?.title) ??
    (hasProposals ? "Proposals ready (BLOCKED)" : undefined);

  const summary =
    asString(obj?.governance?.summary) ??
    asString(obj?.governance_state?.summary) ??
    asString(obj?.summary) ??
    (hasProposals ? "Review proposed commands and promote for approval." : undefined);

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
