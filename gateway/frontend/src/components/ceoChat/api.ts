// gateway/frontend/src/components/ceoChat/api.ts
import type { CeoCommandRequest, NormalizedConsoleResponse } from "./types";
import { normalizeConsoleResponse, streamTextFromResponse } from "./normalize";

export type CeoConsoleApi = {
  sendCommand: (
    req: CeoCommandRequest,
    signal?: AbortSignal
  ) => Promise<NormalizedConsoleResponse>;
  approve: (
    approvalId: string,
    signal?: AbortSignal
  ) => Promise<NormalizedConsoleResponse>;
};

type ApiOptions = {
  ceoCommandUrl: string;
  approveUrl?: string;
  headers?: Record<string, string>;
  /** hard timeout (ms) to avoid hanging requests */
  timeoutMs?: number;
};

const jsonHeaders = { "Content-Type": "application/json" };

/**
 * Normalize request payload so backend always gets the CEO Console contract:
 *   { text, initiator?, session_id?, context_hint? }
 *
 * Supports legacy shapes too (e.g. { input_text, source }).
 */
function buildCeoConsolePayload(req: any): Record<string, any> {
  // Preferred: new contract already present
  if (typeof req?.text === "string" && req.text.trim()) {
    const initiator =
      typeof req?.initiator === "string" && req.initiator.trim()
        ? req.initiator.trim()
        : typeof req?.source === "string" && req.source.trim()
          ? req.source.trim()
          : "ceo_dashboard";

    return {
      ...req,
      text: req.text,
      initiator,
    };
  }

  // Legacy contract: input_text / source
  const inputText =
    (typeof req?.input_text === "string" && req.input_text) ||
    (typeof req?.message === "string" && req.message) ||
    "";

  const initiator =
    (typeof req?.source === "string" && req.source.trim()) ||
    (typeof req?.initiator === "string" && req.initiator.trim()) ||
    "ceo_dashboard";

  const sessionId =
    (typeof req?.session_id === "string" && req.session_id) ||
    (typeof req?.requestId === "string" && req.requestId) ||
    undefined;

  // keep context_hint if caller provides it (snapshot override)
  const contextHint =
    req?.context_hint && typeof req.context_hint === "object"
      ? req.context_hint
      : undefined;

  return {
    text: String(inputText || "").trim(),
    initiator,
    session_id: sessionId,
    context_hint: contextHint,
  };
}

async function safeReadText(res: Response): Promise<string> {
  try {
    return await res.text();
  } catch {
    return "";
  }
}

function mergeSignals(a?: AbortSignal, b?: AbortSignal): AbortSignal | undefined {
  if (!a) return b;
  if (!b) return a;

  // If either aborts => merged aborts.
  const ctrl = new AbortController();
  const onAbort = () => ctrl.abort();
  if (a.aborted || b.aborted) {
    ctrl.abort();
    return ctrl.signal;
  }
  a.addEventListener("abort", onAbort, { once: true });
  b.addEventListener("abort", onAbort, { once: true });
  return ctrl.signal;
}

export const createCeoConsoleApi = (opts: ApiOptions): CeoConsoleApi => {
  const baseHeaders = { ...opts.headers };
  const timeoutMs = typeof opts.timeoutMs === "number" ? opts.timeoutMs : 60000;

  const sendCommand: CeoConsoleApi["sendCommand"] = async (req, signal) => {
    const payload = buildCeoConsolePayload(req);

    if (!payload.text) {
      throw new Error("text required");
    }

    // Timeout controller
    const timeoutCtrl = new AbortController();
    const t = window.setTimeout(() => timeoutCtrl.abort(), timeoutMs);
    const mergedSignal = mergeSignals(signal, timeoutCtrl.signal);

    try {
      const res = await fetch(opts.ceoCommandUrl, {
        method: "POST",
        headers: { ...jsonHeaders, ...baseHeaders },
        body: JSON.stringify(payload),
        signal: mergedSignal,
      });

      if (!res.ok) {
        const text = await safeReadText(res);
        throw new Error(text || `HTTP ${res.status}`);
      }

      // Streaming?
      const stream = streamTextFromResponse(res);
      if (stream) {
        return { requestId: payload.session_id, stream };
      }

      // Normal JSON path with robust fallback
      const rawText = await safeReadText(res);
      try {
        const data = rawText ? JSON.parse(rawText) : {};
        return normalizeConsoleResponse(data, res.headers);
      } catch {
        // Backend returned non-JSON; treat as summary text
        return normalizeConsoleResponse({ summary: rawText || "" }, res.headers);
      }
    } finally {
      window.clearTimeout(t);
    }
  };

  const approve: CeoConsoleApi["approve"] = async (approvalId, signal) => {
    if (!opts.approveUrl) {
      throw new Error("Approve endpoint is not configured");
    }

    const timeoutCtrl = new AbortController();
    const t = window.setTimeout(() => timeoutCtrl.abort(), timeoutMs);
    const mergedSignal = mergeSignals(signal, timeoutCtrl.signal);

    try {
      const res = await fetch(opts.approveUrl, {
        method: "POST",
        headers: { ...jsonHeaders, ...baseHeaders },
        body: JSON.stringify({ approval_id: approvalId, approved_by: "ceo" }),
        signal: mergedSignal,
      });

      if (!res.ok) {
        const text = await safeReadText(res);
        throw new Error(text || `HTTP ${res.status}`);
      }

      const stream = streamTextFromResponse(res);
      if (stream) {
        return { requestId: approvalId, stream };
      }

      const rawText = await safeReadText(res);
      try {
        const data = rawText ? JSON.parse(rawText) : {};
        return normalizeConsoleResponse(data, res.headers);
      } catch {
        return normalizeConsoleResponse({ summary: rawText || "" }, res.headers);
      }
    } finally {
      window.clearTimeout(t);
    }
  };

  return { sendCommand, approve };
};
