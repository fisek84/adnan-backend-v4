// gateway/frontend/src/components/ceoChat/api.ts

import type {
  CeoCommandRequest,
  NormalizedConsoleResponse,
  RawCeoConsoleResponse,
} from "./types";

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

type CreateApiArgs = {
  ceoCommandUrl: string;
  approveUrl?: string;
  headers?: Record<string, string>;
};

const jsonHeaders = (extra?: Record<string, string>) => ({
  "Content-Type": "application/json",
  ...(extra ?? {}),
});

function normalizeResponse(raw: RawCeoConsoleResponse): NormalizedConsoleResponse {
  const systemText = (raw.summary ?? raw.text ?? "").toString();

  const proposed = Array.isArray(raw.proposed_commands) ? raw.proposed_commands : [];
  const hasProposals = proposed.length > 0;

  // Napomena: backend trenutno NE vraća approval_id ovdje, nego samo "proposal".
  // Zato approvalRequestId ostaje undefined (da UI ne prikazuje "Approve" dugme bez pravog ID-a).
  const governance = hasProposals
    ? {
        state: (proposed[0]?.status ?? "BLOCKED") as string,
        title: `Proposals ready (${(proposed[0]?.status ?? "BLOCKED").toString()})`,
        summary:
          proposed.length === 1
            ? `- ${proposed[0]?.command_type ?? "unknown_command"}`
            : proposed
                .map((p) => `- ${p.command_type ?? "unknown_command"}`)
                .join("\n"),
        reasons: [],
        approvalRequestId: undefined as string | undefined,
      }
    : undefined;

  return {
    systemText,
    // kompatibilnost: ako negdje neko čita summary/text direktno
    summary: raw.summary,
    text: raw.text,
    governance,
  };
}

function toBackendPayload(req: CeoCommandRequest): Record<string, any> {
  // Preferirano: {text, initiator, ...}
  if (typeof req.text === "string" && req.text.trim().length > 0) {
    return {
      text: req.text,
      initiator: req.initiator ?? "ceo",
      session_id: req.session_id,
      context_hint: req.context_hint,
    };
  }

  // Legacy fallback: {input_text,...}
  const text = (req.input_text ?? "").toString();
  return {
    text,
    initiator: (req.source ?? req.initiator ?? "ceo").toString(),
    context_hint: req.smart_context ? { snapshot: req.smart_context } : undefined,
  };
}

export function createCeoConsoleApi(args: CreateApiArgs): CeoConsoleApi {
  const { ceoCommandUrl, approveUrl, headers } = args;

  return {
    sendCommand: async (req, signal) => {
      const payload = toBackendPayload(req);

      const r = await fetch(ceoCommandUrl, {
        method: "POST",
        headers: jsonHeaders(headers),
        body: JSON.stringify(payload),
        signal,
      });

      if (!r.ok) {
        const body = await r.text().catch(() => "");
        throw new Error(`CEO command failed (${r.status}): ${body || r.statusText}`);
      }

      const data = (await r.json()) as RawCeoConsoleResponse;
      return normalizeResponse(data);
    },

    approve: async (approvalId, signal) => {
      if (!approveUrl) {
        return {
          systemText: "",
          governance: {
            state: "BLOCKED",
            title: "Approval required",
            summary: "Approve endpoint nije konfigurisan u UI (approveUrl).",
            reasons: [],
            approvalRequestId: approvalId,
          },
        };
      }

      const r = await fetch(approveUrl, {
        method: "POST",
        headers: jsonHeaders(headers),
        body: JSON.stringify({ approval_id: approvalId }),
        signal,
      });

      if (!r.ok) {
        const body = await r.text().catch(() => "");
        throw new Error(`Approve failed (${r.status}): ${body || r.statusText}`);
      }

      // Approve endpoint ti trenutno vraća execution result; mi ga prikazujemo kao systemText
      const data = (await r.json()) as any;

      const text =
        typeof data?.summary === "string"
          ? data.summary
          : typeof data?.text === "string"
          ? data.text
          : JSON.stringify(data, null, 2);

      return {
        systemText: text,
      };
    },
  };
}
