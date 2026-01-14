// gateway/frontend/src/components/ceoChat/normalize.ts

import { isObject } from "../../utils/isObject";

type AnyRecord = Record<string, any>;

export type CeoConsoleEnvelope = {
  id?: string;
  type?: string;
  role?: string;
  content?: any;
  text?: string;
  delta?: string;
  proposed_commands?: any[];
  proposedCommands?: any[];
  governance_state?: string;
  governanceState?: string;
  meta?: AnyRecord;
};

export type NormalizedCeoConsoleMessage = {
  id: string;
  role: "user" | "assistant" | "system";
  text: string;
  raw: AnyRecord | string;
  proposedCommands: any[];
  governanceState?: string;
};

/* ---------------- helpers ---------------- */

function asString(v: any): string | undefined {
  if (v == null) return undefined;
  if (typeof v === "string") return v;
  if (typeof v === "number" || typeof v === "boolean") return String(v);
  return undefined;
}

function safeJsonParse(s: string): any | null {
  try {
    return JSON.parse(s);
  } catch {
    return null;
  }
}

function normalizeRole(v: any): "user" | "assistant" | "system" {
  const r = String(v ?? "").toLowerCase();
  if (r === "user") return "user";
  if (r === "assistant") return "assistant";
  if (r === "system") return "system";
  return "assistant";
}

function pickProposedCommands(obj: AnyRecord): any[] {
  if (Array.isArray(obj?.proposed_commands)) return obj.proposed_commands;
  if (Array.isArray(obj?.proposedCommands)) return obj.proposedCommands;
  if (Array.isArray(obj?.raw?.proposed_commands)) return obj.raw.proposed_commands;
  if (Array.isArray(obj?.raw?.proposedCommands)) return obj.raw.proposedCommands;
  return [];
}

/* ---------------- core ---------------- */

export function deriveSystemTextFromCeoConsole(input: any): {
  text: string;
  proposed_commands: any[];
  governance_state?: string;
  raw: AnyRecord | string;
} {
  if (typeof input === "string") {
    const maybeObj = safeJsonParse(input);
    if (maybeObj && isObject(maybeObj)) {
      const obj = maybeObj as AnyRecord;
      return {
        text:
          asString(obj.text) ??
          asString(obj.delta) ??
          asString(obj.content) ??
          input,
        proposed_commands: pickProposedCommands(obj),
        governance_state:
          asString(obj.governance_state) ??
          asString(obj.governanceState),
        raw: obj,
      };
    }
    return { text: input, proposed_commands: [], raw: input };
  }

  if (isObject(input)) {
    const obj = input as AnyRecord;
    return {
      text:
        asString(obj.delta) ??
        asString(obj.text) ??
        asString(obj.content) ??
        "",
      proposed_commands: pickProposedCommands(obj),
      governance_state:
        asString(obj.governance_state) ??
        asString(obj.governanceState),
      raw: obj,
    };
  }

  return {
    text: String(input ?? ""),
    proposed_commands: [],
    raw: String(input ?? ""),
  };
}

export function normalizeCeoConsoleMessage(
  input: any,
  fallbackId: string
): NormalizedCeoConsoleMessage {
  const { text, proposed_commands, governance_state, raw } =
    deriveSystemTextFromCeoConsole(input);

  return {
    id: asString(input?.id) ?? fallbackId,
    role: normalizeRole(input?.role ?? input?.type),
    text: text ?? "",
    raw,
    proposedCommands: proposed_commands ?? [],
    governanceState: governance_state,
  };
}

export function normalizeCeoConsoleMessages(
  inputs: any[]
): NormalizedCeoConsoleMessage[] {
  if (!Array.isArray(inputs)) return [];
  return inputs.map((m, i) =>
    normalizeCeoConsoleMessage(m, `m_${i}`)
  );
}

/* ---------------- BACKWARD COMPAT ---------------- */

/**
 * api.ts poziva sa (raw, headers)
 * headers se IGNORIŠU – transport level
 */
export function normalizeConsoleResponse(
  input: any,
  _headers?: any
): NormalizedCeoConsoleMessage[] {
  if (Array.isArray(input)) return normalizeCeoConsoleMessages(input);
  return [normalizeCeoConsoleMessage(input, "m_0")];
}

/**
 * api.ts očekuje string → stream helper
 */
export function streamTextFromResponse(input: any): AsyncIterable<string> {
  const { text } = deriveSystemTextFromCeoConsole(input);
  return (async function* () {
    yield text;
  })();
}
