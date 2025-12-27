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
};

const jsonHeaders = { "Content-Type": "application/json" };

export const createCeoConsoleApi = (opts: ApiOptions): CeoConsoleApi => {
  const baseHeaders = { ...opts.headers };

  const sendCommand: CeoConsoleApi["sendCommand"] = async (req, signal) => {
    const res = await fetch(opts.ceoCommandUrl, {
      method: "POST",
      headers: { ...jsonHeaders, ...baseHeaders },
      body: JSON.stringify(req),
      signal,
    });

    if (!res.ok) {
      const text = await res.text().catch(() => "");
      throw new Error(text || `HTTP ${res.status}`);
    }

    const stream = streamTextFromResponse(res);
    if (stream) {
      // CeoCommandRequest nema client_request_id; koristimo session_id (ako je poslan)
      return { requestId: req.session_id, stream };
    }

    const data = await res
      .json()
      .catch(async () => ({ message: await res.text().catch(() => "") }));

    return normalizeConsoleResponse(data, res.headers);
  };

  const approve: CeoConsoleApi["approve"] = async (approvalId, signal) => {
    if (!opts.approveUrl) {
      throw new Error("Approve endpoint is not configured");
    }

    const res = await fetch(opts.approveUrl, {
      method: "POST",
      headers: { ...jsonHeaders, ...baseHeaders },
      body: JSON.stringify({ approval_id: approvalId, approved_by: "ceo" }),
      signal,
    });

    if (!res.ok) {
      const text = await res.text().catch(() => "");
      throw new Error(text || `HTTP ${res.status}`);
    }

    const stream = streamTextFromResponse(res);
    if (stream) {
      return { requestId: approvalId, stream };
    }

    const data = await res
      .json()
      .catch(async () => ({ message: await res.text().catch(() => "") }));

    return normalizeConsoleResponse(data, res.headers);
  };

  return { sendCommand, approve };
};
