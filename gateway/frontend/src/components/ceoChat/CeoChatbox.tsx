// gateway/frontend/src/components/ceoChat/CeoChatbox.tsx
import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type {
  ChatItem,
  ChatMessageItem,
  GovernanceEventItem,
  NormalizedConsoleResponse,
  UiStrings,
} from "./types";
import { createCeoConsoleApi } from "./api";
import { defaultStrings } from "./strings";
import { useAutoScroll } from "./hooks";
import "./CeoChatbox.css";

type CeoConsoleApi = ReturnType<typeof createCeoConsoleApi>;

const uid = () =>
  typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : `id_${Math.random().toString(16).slice(2)}_${Date.now()}`;

const now = () => Date.now();

const formatTime = (ms: number) => {
  const d = new Date(ms);
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
};

type CeoChatboxProps = {
  ceoCommandUrl: string;
  approveUrl?: string; // POST { approval_id }
  rejectUrl?: string; // OPTIONAL: POST { approval_id } (if backend supports reject/deny)
  executeRawUrl?: string; // POST canonical proposal payload (opaque)
  headers?: Record<string, string>;
  strings?: Partial<UiStrings>;
  onOpenApprovals?: (approvalRequestId?: string) => void;
  className?: string;

  // Voice (client-side, no backend assumptions)
  enableVoice?: boolean; // default true
  autoSendOnVoiceFinal?: boolean; // default false
};

type BusyState = "idle" | "submitting" | "streaming" | "error";

const makeSystemProcessingItem = (requestId?: string): ChatMessageItem => ({
  id: uid(),
  kind: "message",
  role: "system",
  content: "",
  status: "streaming",
  createdAt: now(),
  requestId,
});

const toGovernanceCard = (resp: NormalizedConsoleResponse): GovernanceEventItem | null => {
  const gov = (resp as any)?.governance;
  if (!gov) return null;
  return {
    id: uid(),
    kind: "governance",
    createdAt: now(),
    state: gov.state,
    title: gov.title,
    summary: gov.summary,
    reasons: gov.reasons,
    approvalRequestId: gov.approvalRequestId,
    requestId: (resp as any)?.requestId,
  };
};

/**
 * CANON:
 * proposed_commands from /api/chat must be treated as an OPAQUE, ready-to-send execute/raw payload.
 * Frontend must NOT re-map/normalize/rebuild it (no command_type/payload transformations).
 */
type ProposedCmd = Record<string, any>;

const _extractProposedCommands = (resp: any): ProposedCmd[] => {
  const candidates = [
    resp?.proposed_commands,
    resp?.proposedCommands,
    resp?.raw?.proposed_commands,
    resp?.raw?.proposedCommands,
    resp?.result?.proposed_commands,
    resp?.result?.proposedCommands,
    resp?.governance?.proposed_commands,
    // FAZA A hardening: support camelCase under governance too
    resp?.governance?.proposedCommands,
  ];

  for (const c of candidates) {
    if (!Array.isArray(c)) continue;

    const out: ProposedCmd[] = [];
    for (const x of c) {
      if (!x || typeof x !== "object" || Array.isArray(x)) continue;
      out.push(x as ProposedCmd);
    }
    return out;
  }

  return [];
};

const _pickText = (x: any): string => {
  if (typeof x === "string") return x.trim();
  if (!x || typeof x !== "object") return "";
  const keys = ["summary", "text", "message", "output_text", "outputText", "detail"];
  for (const k of keys) {
    const v = (x as any)[k];
    if (typeof v === "string" && v.trim()) return v.trim();
  }
  return "";
};

function truncateText(s: string, maxLen = 20000): string {
  if (!s) return "";
  if (s.length <= maxLen) return s;
  return s.slice(0, maxLen) + "\n\n…(truncated)…";
}

function isAbortError(e: unknown): boolean {
  const msg = e instanceof Error ? e.message : String(e ?? "");
  return msg.toLowerCase().includes("aborted") || msg.toLowerCase().includes("abort");
}

/**
 * Render helper:
 * - Keeps plain-text rendering (no HTML injection)
 * - Makes "Open in Notion: https://..." clickable
 */
function renderTextWithNotionLink(text: string): React.ReactNode {
  const re = /(Open in Notion:\s*)(https?:\/\/\S+)/;
  const m = text.match(re);
  if (!m) return text;

  const prefix = m[1];
  const url = m[2];

  let safeUrl: string | null = null;
  try {
    safeUrl = new URL(url).toString();
  } catch {
    safeUrl = null;
  }

  const idx = text.indexOf(m[0]);
  const before = idx >= 0 ? text.slice(0, idx) : "";
  const after = idx >= 0 ? text.slice(idx + m[0].length) : "";

  return (
    <>
      {before}
      {prefix}
      {safeUrl ? (
        <a href={safeUrl} target="_blank" rel="noreferrer">
          {url}
        </a>
      ) : (
        url
      )}
      {after}
    </>
  );
}

/**
 * IMPORTANT UX RULE (CANON):
 * Do NOT show "fallback proposals" (the ones that just echo a prompt / ceo.command.propose, dry_run).
 * Only hide proposals when the backend explicitly marks them as fallback.
 *
 * Production rule:
 * - NEVER infer fallback purely from command name (e.g. ceo.command.propose) + flags.
 * - Treat requires_approval as actionable; backend is the source of truth for validity.
 */
function isActionableProposal(p: ProposedCmd): boolean {
  if (!p || typeof p !== "object") return false;

  const cmd = typeof p.command === "string" ? p.command : "";
  const topIntent = typeof p.intent === "string" ? p.intent : "";
  const reason = typeof p.reason === "string" ? p.reason : "";

  // CANON: real intent can be nested at params.ai_command.intent for notion_write wrapper
  const nestedIntent =
    typeof (p as any)?.params?.ai_command?.intent === "string"
      ? (p as any).params.ai_command.intent
      : typeof (p as any)?.params?.aiCommand?.intent === "string"
        ? (p as any).params.aiCommand.intent
        : "";

  const intent = nestedIntent || topIntent;

  const dryRun = p.dry_run === true || p.dryRun === true;

  // Normalize "requires approval" flags (backend variations)
  const requiresApproval =
    p.requires_approval === true ||
    p.requiresApproval === true ||
    p.required_approval === true ||
    (p as any).requiredApproval === true;

  /**
   * CRITICAL FIX:
   * Contract no-op MUST be hidden when backend explicitly marks it.
   * This is NOT heuristics — it is an explicit backend marker.
   */
  const kind =
    typeof (p as any)?.payload_summary?.kind === "string" ? (p as any).payload_summary.kind : "";
  if (kind === "contract_noop") return false;

  /**
   * CRITICAL FIX:
   * Fallback MUST be recognized only via explicit backend marker in reason.
   * Do NOT use cmd/dryRun/requiresApproval heuristics to suppress proposals,
   * because ceo.command.propose may be the canonical wrapper.
   */
  const looksLikeFallback = /fallback proposal/i.test(reason);
  if (looksLikeFallback) return false;

  // If backend says it requires approval, it is actionable for UI purposes.
  // (Backend remains source-of-truth; execute/raw will validate.)
  if (requiresApproval) return true;

  const hasSomePayload =
    (p.args && typeof p.args === "object" && Object.keys(p.args).length > 0) ||
    (p.params && typeof p.params === "object" && Object.keys(p.params).length > 0) ||
    (p.payload && typeof p.payload === "object" && Object.keys(p.payload).length > 0);

  // If not approval-gated, avoid showing empty/no-op proposals.
  if (!intent && !hasSomePayload) return false;

  // Optional: keep dryRun proposals visible only if they have explicit intent/payload.
  void cmd;
  void dryRun;

  return true;
}

function proposalLabel(p: ProposedCmd, idx: number): string {
  const cmd = typeof (p as any)?.command === "string" ? (p as any).command : "";
  const topIntent = typeof (p as any)?.intent === "string" ? (p as any).intent : "";
  const commandType = typeof (p as any)?.command_type === "string" ? (p as any).command_type : "";

  // CANON: show ai_command.intent for notion_write wrapper
  const nestedIntent =
    typeof (p as any)?.params?.ai_command?.intent === "string"
      ? (p as any).params.ai_command.intent
      : typeof (p as any)?.params?.aiCommand?.intent === "string"
        ? (p as any).params.aiCommand.intent
        : "";

  if (nestedIntent) return nestedIntent;
  if (topIntent) return topIntent;
  if (cmd) return cmd;
  if (commandType) return commandType;
  return `proposal_${idx + 1}`;
}

function shouldShowBackendGovernanceCard(gov: GovernanceEventItem, actionableCount: number): boolean {
  if (!gov) return false;

  const title = (gov.title ?? "").toLowerCase();
  const state = (gov as any)?.state ?? "";

  const isProposalReadyCard =
    title.includes("proposals ready") || title.includes("proposed commands") || title.includes("proposal");

  if (isProposalReadyCard && state === "BLOCKED" && !gov.approvalRequestId && actionableCount === 0) {
    return false;
  }

  return true;
}

/** SpeechRecognition typings (browser) */
declare global {
  interface Window {
    webkitSpeechRecognition?: any;
    SpeechRecognition?: any;
  }
}

export const CeoChatbox: React.FC<CeoChatboxProps> = ({
  ceoCommandUrl,
  approveUrl,
  rejectUrl,
  executeRawUrl,
  headers,
  strings,
  onOpenApprovals,
  className,
  enableVoice = true,
  autoSendOnVoiceFinal = false,
}) => {
  const ui = useMemo(() => ({ ...defaultStrings, ...(strings ?? {}) }), [strings]);

  const effectiveApproveUrl = approveUrl?.trim() ? approveUrl : "/api/ai-ops/approval/approve";
  const effectiveRejectUrl = rejectUrl?.trim() ? rejectUrl : "/api/ai-ops/approval/reject";

  const api: CeoConsoleApi = useMemo(
    () =>
      (createCeoConsoleApi as any)({
        ceoCommandUrl,
        approveUrl: effectiveApproveUrl,
        headers,
      }) as CeoConsoleApi,
    [ceoCommandUrl, effectiveApproveUrl, headers]
  );

  const [items, setItems] = useState<ChatItem[]>([]);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState<BusyState>("idle");
  const [lastError, setLastError] = useState<string | null>(null);

  const abortRef = useRef<AbortController | null>(null);

  const { viewportRef, isPinnedToBottom, scrollToBottom } = useAutoScroll();

  useEffect(() => {
    if (isPinnedToBottom) scrollToBottom(false);
  }, [items.length, isPinnedToBottom, scrollToBottom]);

  const appendItem = useCallback((it: ChatItem) => {
    setItems((prev) => [...prev, it]);
  }, []);

  const updateItem = useCallback((id: string, patch: Partial<ChatItem>) => {
    setItems((prev) => prev.map((x) => (x.id === id ? ({ ...x, ...(patch as any) } as ChatItem) : x)));
  }, []);

  const removeItem = useCallback((id: string) => {
    setItems((prev) => prev.filter((x) => x.id !== id));
  }, []);

  const stopCurrent = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    setBusy("idle");
  }, []);

  // --- URL resolvers (support absolute urls and cross-origin dev) ---
  const resolveUrl = useCallback(
    (maybeUrl: string | undefined, fallbackPath: string): string => {
      try {
        if (maybeUrl && maybeUrl.trim()) return new URL(maybeUrl, ceoCommandUrl).toString();
        return new URL(fallbackPath, ceoCommandUrl).toString();
      } catch {
        return maybeUrl && maybeUrl.trim() ? maybeUrl : fallbackPath;
      }
    },
    [ceoCommandUrl]
  );

  const mergedHeaders = useMemo(() => {
    return {
      "Content-Type": "application/json",
      ...(headers ?? {}),
    } as Record<string, string>;
  }, [headers]);

  const postJson = useCallback(
    async (url: string, body: any, signal: AbortSignal): Promise<any> => {
      const res = await fetch(url, {
        method: "POST",
        headers: mergedHeaders,
        body: JSON.stringify(body ?? {}),
        signal,
      });
      const txt = await res.text();
      if (!res.ok) throw new Error(`${url} failed (${res.status}): ${txt || "no body"}`);
      try {
        return txt ? JSON.parse(txt) : {};
      } catch {
        return {};
      }
    },
    [mergedHeaders]
  );

  // ------------------------------
  // VOICE INPUT (browser STT)
  // ------------------------------
  const [voiceSupported, setVoiceSupported] = useState(false);
  const [listening, setListening] = useState(false);
  const recognitionRef = useRef<any>(null);

  useEffect(() => {
    if (!enableVoice) return;

    const Rec = window.SpeechRecognition || window.webkitSpeechRecognition;
    const ok = typeof Rec === "function";
    setVoiceSupported(ok);

    if (!ok) return;

    const rec = new Rec();
    rec.lang = "bs-BA";
    rec.interimResults = true;
    rec.continuous = false;

    rec.onresult = (ev: any) => {
      let finalText = "";
      let interim = "";
      for (let i = ev.resultIndex; i < ev.results.length; i++) {
        const r = ev.results[i];
        const t = String(r?.[0]?.transcript ?? "");
        if (r.isFinal) finalText += t;
        else interim += t;
      }

      const combined = (finalText || interim || "").trim();
      if (combined) setDraft(combined);

      if (autoSendOnVoiceFinal && finalText.trim()) {
        // intentionally no auto-submit unless you wire it explicitly
      }
    };

    rec.onerror = () => {
      setListening(false);
    };

    rec.onend = () => {
      setListening(false);
    };

    recognitionRef.current = rec;

    return () => {
      try {
        rec.onresult = null;
        rec.onerror = null;
        rec.onend = null;
        rec.stop?.();
      } catch {
        // ignore
      }
      recognitionRef.current = null;
    };
  }, [enableVoice, autoSendOnVoiceFinal]);

  const toggleVoice = useCallback(() => {
    if (!enableVoice) return;
    const rec = recognitionRef.current;
    if (!rec) return;

    if (listening) {
      try {
        rec.stop();
      } catch {
        // ignore
      }
      setListening(false);
      return;
    }

    try {
      setListening(true);
      rec.start();
    } catch {
      setListening(false);
    }
  }, [enableVoice, listening]);

  // ------------------------------
  // APPROVAL FLOW HELPERS
  // ------------------------------
  const handleOpenApprovals = useCallback(
    (approvalRequestId?: string) => {
      if (onOpenApprovals) onOpenApprovals(approvalRequestId);
      else window.dispatchEvent(new CustomEvent("ceo:openApprovals", { detail: { approvalRequestId } }));
    },
    [onOpenApprovals]
  );

  /**
   * Step A: Create execution (BLOCKED) from the EXACT proposal object.
   */
  const handleCreateExecutionFromProposal = useCallback(
    async (proposal: ProposedCmd) => {
      if (busy === "submitting" || busy === "streaming") return;

      setBusy("submitting");
      setLastError(null);

      const placeholder = makeSystemProcessingItem("proposal_create_execution");
      appendItem(placeholder);

      const controller = new AbortController();
      abortRef.current = controller;

      try {
        const execUrl = resolveUrl(executeRawUrl, "/api/execute/raw");
        const execJson = await postJson(execUrl, proposal, controller.signal);

        const approvalId: string | null =
          typeof execJson?.approval_id === "string" && execJson.approval_id ? execJson.approval_id : null;

        const executionId: string | null =
          typeof execJson?.execution_id === "string" && execJson.execution_id ? execJson.execution_id : null;

        const msg =
          approvalId?.trim()
            ? `Execution created (BLOCKED). approval_id: ${approvalId}`
            : _pickText(execJson) || "Execution created.";

        updateItem(placeholder.id, { content: msg, status: "final" });

        if (approvalId) {
          appendItem({
            id: uid(),
            kind: "governance",
            createdAt: now(),
            state: "BLOCKED",
            title: "Pending approval",
            summary: executionId ? `execution_id: ${executionId}` : "Execution created and waiting for approval.",
            reasons: [],
            approvalRequestId: approvalId,
            requestId: (execJson as any)?.requestId,
          } as GovernanceEventItem);

          handleOpenApprovals(approvalId);
        }

        abortRef.current = null;
        setBusy("idle");
        setLastError(null);
      } catch (e) {
        abortRef.current = null;
        const msg = e instanceof Error ? e.message : String(e);
        updateItem(placeholder.id, { status: "error", content: "" });
        setBusy(isAbortError(e) ? "idle" : "error");
        setLastError(isAbortError(e) ? null : msg);
      }
    },
    [appendItem, busy, executeRawUrl, handleOpenApprovals, postJson, resolveUrl, updateItem]
  );

  /**
   * Step B: Approve using approval_id.
   */
  const handleApprove = useCallback(
    async (approvalId: string) => {
      const appUrl = resolveUrl(effectiveApproveUrl, "/api/ai-ops/approval/approve");
      if (busy === "submitting" || busy === "streaming") return;

      setBusy("submitting");
      setLastError(null);

      const placeholder = makeSystemProcessingItem(approvalId);
      appendItem(placeholder);

      const controller = new AbortController();
      abortRef.current = controller;

      try {
        const approveJson = await postJson(appUrl, { approval_id: approvalId }, controller.signal);
        const msg =
          _pickText(approveJson) ||
          (approveJson?.execution_state ? `Execution: ${approveJson.execution_state}` : "Approved.");

        updateItem(placeholder.id, { content: msg, status: "final" });
        abortRef.current = null;
        setBusy("idle");
        setLastError(null);
      } catch (e) {
        abortRef.current = null;
        const msg = e instanceof Error ? e.message : String(e);
        updateItem(placeholder.id, { status: "error", content: "" });
        setBusy(isAbortError(e) ? "idle" : "error");
        setLastError(isAbortError(e) ? null : msg);
      }
    },
    [appendItem, effectiveApproveUrl, busy, postJson, resolveUrl, updateItem]
  );

  /**
   * OPTIONAL: Reject/Disapprove approval_id (if backend supports).
   */
  const handleReject = useCallback(
    async (approvalId: string) => {
      const rejUrl = resolveUrl(effectiveRejectUrl, "/api/ai-ops/approval/reject");
      if (busy === "submitting" || busy === "streaming") return;

      setBusy("submitting");
      setLastError(null);

      const placeholder = makeSystemProcessingItem(approvalId);
      appendItem(placeholder);

      const controller = new AbortController();
      abortRef.current = controller;

      try {
        const rejectJson = await postJson(rejUrl, { approval_id: approvalId }, controller.signal);
        const msg = _pickText(rejectJson) || "Rejected.";

        updateItem(placeholder.id, { content: msg, status: "final" });
        abortRef.current = null;
        setBusy("idle");
        setLastError(null);
      } catch (e) {
        abortRef.current = null;
        const msg = e instanceof Error ? e.message : String(e);
        updateItem(placeholder.id, { status: "error", content: "" });
        setBusy(isAbortError(e) ? "idle" : "error");
        setLastError(isAbortError(e) ? null : msg);
      }
    },
    [appendItem, effectiveRejectUrl, busy, postJson, resolveUrl, updateItem]
  );

  /**
   * Single click "Approve" on a proposal:
   * - create execution (BLOCKED)
   * - then approve via approval_id
   */
  const handleApproveProposal = useCallback(
    async (proposal: ProposedCmd) => {
      if (busy === "submitting" || busy === "streaming") return;

      setBusy("submitting");
      setLastError(null);

      const placeholder = makeSystemProcessingItem("approve_proposal");
      appendItem(placeholder);

      const controller = new AbortController();
      abortRef.current = controller;

      try {
        const execUrl = resolveUrl(executeRawUrl, "/api/execute/raw");
        const execJson = await postJson(execUrl, proposal, controller.signal);

        const approvalId: string | null =
          typeof execJson?.approval_id === "string" && execJson.approval_id ? execJson.approval_id : null;

        if (!approvalId) {
          updateItem(placeholder.id, {
            content: _pickText(execJson) || "Execution created, but approval_id missing.",
            status: "final",
          });
          abortRef.current = null;
          setBusy("idle");
          return;
        }

        const appUrl = resolveUrl(effectiveApproveUrl, "/api/ai-ops/approval/approve");
        const approveJson = await postJson(appUrl, { approval_id: approvalId }, controller.signal);

        const msg =
          _pickText(approveJson) ||
          (approveJson?.execution_state
            ? `Execution: ${approveJson.execution_state}`
            : `Approved. approval_id: ${approvalId}`);

        updateItem(placeholder.id, { content: msg, status: "final" });

        abortRef.current = null;
        setBusy("idle");
        setLastError(null);
      } catch (e) {
        abortRef.current = null;
        const msg = e instanceof Error ? e.message : String(e);
        updateItem(placeholder.id, { status: "error", content: "" });
        setBusy(isAbortError(e) ? "idle" : "error");
        setLastError(isAbortError(e) ? null : msg);
      }
    },
    [appendItem, busy, effectiveApproveUrl, executeRawUrl, postJson, resolveUrl, updateItem]
  );

  // ------------------------------
  // CHAT RESPONSE -> UI
  // ------------------------------
  const flushResponseToUi = useCallback(
    async (placeholderId: string, resp: NormalizedConsoleResponse) => {
      if ((resp as any).stream) {
        setBusy("streaming");
        updateItem(placeholderId, { content: "", status: "streaming" });

        let acc = "";
        try {
          for await (const chunk of (resp as any).stream) {
            acc += chunk;
            updateItem(placeholderId, { content: acc, status: "streaming" });
            if (isPinnedToBottom) scrollToBottom(false);
          }

          updateItem(placeholderId, { content: acc.trim(), status: "final" });
          setBusy("idle");
          setLastError(null);
        } catch (e) {
          const msg = e instanceof Error ? e.message : String(e);
          updateItem(placeholderId, { status: "error", content: acc.trim() });
          setBusy("error");
          setLastError(msg);
        }
        return;
      }

      // ✅ FIX (evidence-based): NormalizedConsoleResponse uses `systemText`, so prefer it explicitly.
      const sysText =
        _pickText(resp as any) ||
        (typeof (resp as any)?.systemText === "string" ? (resp as any).systemText.trim() : "") ||
        _pickText((resp as any)?.result) ||
        _pickText((resp as any)?.raw) ||
        _pickText((resp as any)?.data) ||
        "";

      updateItem(placeholderId, { content: sysText, status: "final" });

      const proposalsRaw = _extractProposedCommands(resp as any);
      const proposals = proposalsRaw.filter(isActionableProposal);
      const actionableCount = proposals.length;

      const gov = toGovernanceCard(resp);
      if (gov && shouldShowBackendGovernanceCard(gov, actionableCount)) appendItem(gov);

      // CANON: any actionable proposals => show governance BLOCKED entrypoint
      if (actionableCount > 0) {
        appendItem({
          id: uid(),
          kind: "governance",
          createdAt: now(),
          state: "BLOCKED",
          title: "Approval required",
          summary: "Review the proposed action and either approve or dismiss it.",
          reasons: undefined,
          approvalRequestId: undefined,
          requestId: (resp as any)?.requestId,
          proposedCommands: proposals,
        } as any);
      }

      setBusy("idle");
      setLastError(null);
    },
    [appendItem, updateItem, isPinnedToBottom, scrollToBottom]
  );

  // ------------------------------
  // NOTION READ (page_by_title)
  // ------------------------------
  const [notionQuery, setNotionQuery] = useState<string>("");
  const [notionLoading, setNotionLoading] = useState<boolean>(false);
  const [notionLastError, setNotionLastError] = useState<string | null>(null);

  const runNotionSearch = useCallback(async () => {
    const q = notionQuery.trim();
    if (!q) {
      setNotionLastError("Unesi naziv dokumenta (title) za pretragu.");
      return;
    }
    if (busy === "submitting" || busy === "streaming") return;

    setNotionLastError(null);
    setNotionLoading(true);

    const placeholder = makeSystemProcessingItem("notion_read");
    appendItem(placeholder);

    const controller = new AbortController();
    abortRef.current = controller;

    try {
      const res = await (api as any).notionReadPageByTitle?.(q, controller.signal);

      if (!res || res.ok !== true) {
        const err = typeof res?.error === "string" && res.error.trim() ? res.error.trim() : "Document not found.";
        updateItem(placeholder.id, {
          content: `Document not found for query: "${q}"\n\n${err}`,
          status: "final",
        });
        abortRef.current = null;
        setNotionLoading(false);
        return;
      }

      const title = typeof res.title === "string" && res.title.trim() ? res.title.trim() : q;
      const notionUrl = typeof res.notion_url === "string" && res.notion_url.trim() ? res.notion_url.trim() : "";

      const contentMd = typeof res.content_markdown === "string" && res.content_markdown ? res.content_markdown : "";

      const docText =
        `${title}\n` +
        `${"=".repeat(Math.min(80, Math.max(10, title.length)))}\n\n` +
        (notionUrl ? `Open in Notion: ${notionUrl}\n\n` : "") +
        truncateText(contentMd, 20000);

      updateItem(placeholder.id, { content: docText, status: "final" });

      abortRef.current = null;
      setNotionLoading(false);
      setLastError(null);
    } catch (e) {
      abortRef.current = null;
      const msg = e instanceof Error ? e.message : String(e);
      updateItem(placeholder.id, { status: "error", content: "" });
      setNotionLoading(false);
      setNotionLastError(isAbortError(e) ? null : msg);
      setLastError(isAbortError(e) ? null : msg);
    }
  }, [api, appendItem, busy, notionQuery, updateItem]);

  // ------------------------------
  // SUBMIT CHAT
  // ------------------------------
  const submit = useCallback(async () => {
    const trimmed = draft.trim();
    if (!trimmed) return;
    if (busy === "submitting" || busy === "streaming") return;

    setBusy("submitting");
    setLastError(null);

    const clientRequestId = uid();

    const ceoItem: ChatMessageItem = {
      id: uid(),
      kind: "message",
      role: "ceo",
      content: trimmed,
      status: "delivered",
      createdAt: now(),
      requestId: clientRequestId,
    };

    appendItem(ceoItem);
    setDraft("");

    const placeholder = makeSystemProcessingItem(clientRequestId);
    appendItem(placeholder);

    const controller = new AbortController();
    abortRef.current = controller;

    try {
      const req: any = {
        message: trimmed,
        text: trimmed,

        initiator: "ceo_chat",
        preferred_agent_id: "ceo_advisor",
        context_hint: {
          preferred_agent_id: "ceo_advisor",
        },
      };

      const resp = await api.sendCommand(req, controller.signal);

      // ✅ DEBUG IN-UI (no Console needed): shows what the frontend actually received.
      appendItem({
        id: uid(),
        kind: "message",
        role: "system",
        content:
          "[DEBUG] systemText=" +
          String((resp as any)?.systemText ?? "<missing>") +
          " | raw.text=" +
          String((resp as any)?.raw?.text ?? "<missing>"),
        status: "final",
        createdAt: now(),
      });

      abortRef.current = null;
      await flushResponseToUi(placeholder.id, resp);

      setBusy("idle");
      setLastError(null);
    } catch (e) {
      abortRef.current = null;
      const msg = e instanceof Error ? e.message : String(e);
      updateItem(placeholder.id, { status: "error", content: "" });
      setBusy(isAbortError(e) ? "idle" : "error");
      setLastError(isAbortError(e) ? null : msg);
    }
  }, [api, appendItem, busy, draft, flushResponseToUi, updateItem]);

  const onKeyDown = useCallback(
    (ev: React.KeyboardEvent<HTMLTextAreaElement>) => {
      if (ev.key !== "Enter") return;
      if (ev.shiftKey) return;
      ev.preventDefault();
      void submit();
    },
    [submit]
  );

  const canSend = busy === "idle" && draft.trim().length > 0;
  const showTyping = busy === "submitting" || busy === "streaming";
  const jumpToLatest = useCallback(() => scrollToBottom(true), [scrollToBottom]);

  const retryLast = useCallback(() => {
    setBusy("idle");
    setLastError(null);
    setNotionLastError(null);
  }, []);

  return (
    <section className={`ceoChatbox ${className ?? ""}`.trim()}>
      <header className="ceoHeader">
        <div className="ceoHeaderTitleRow">
          <div className="ceoHeaderTitle">{ui.headerTitle}</div>
          <div className="ceoHeaderActions">
            {!isPinnedToBottom && (
              <button className="ceoHeaderButton" onClick={jumpToLatest}>
                {ui.jumpToLatestLabel}
              </button>
            )}

            {enableVoice && voiceSupported ? (
              <button
                className="ceoHeaderButton"
                onClick={toggleVoice}
                disabled={busy === "submitting" || busy === "streaming"}
                title={listening ? "Stop voice input" : "Start voice input"}
              >
                {listening ? "Voice: ON" : "Voice"}
              </button>
            ) : null}

            {(busy === "submitting" || busy === "streaming" || notionLoading) && (
              <button className="ceoHeaderButton" onClick={stopCurrent}>
                Stop
              </button>
            )}
          </div>
        </div>
        <div className="ceoHeaderSubtitle">{ui.headerSubtitle}</div>
      </header>

      <div className="ceoViewport" ref={viewportRef}>
        <div className="ceoList">
          {items.map((it) => {
            if (it.kind === "message") {
              const rowSide = it.role === "ceo" ? "right" : "left";
              const dotCls =
                it.status === "error"
                  ? "ceoStatusDot err"
                  : it.status === "final"
                    ? "ceoStatusDot ok"
                    : "ceoStatusDot";

              return (
                <div className={`ceoRow ${rowSide}`} key={it.id}>
                  <div className={`ceoBubble ${it.role}`}>
                    {it.role === "system" && it.status === "streaming" && !it.content ? (
                      <span className="ceoTyping">
                        <span>{ui.processingLabel}</span>
                        <span className="ceoDots" aria-hidden="true">
                          <span className="ceoDot" />
                          <span className="ceoDot" />
                          <span className="ceoDot" />
                        </span>
                      </span>
                    ) : (
                      typeof it.content === "string" ? renderTextWithNotionLink(it.content) : it.content
                    )}
                    <div className="ceoMeta">
                      <span className={dotCls} />
                      <span>{formatTime(it.createdAt)}</span>
                    </div>
                  </div>
                </div>
              );
            }

            const badgeClass =
              it.state === "BLOCKED" ? "blocked" : it.state === "APPROVED" ? "approved" : "executed";

            const badgeText =
              it.state === "BLOCKED" ? ui.blockedLabel : it.state === "APPROVED" ? ui.approvedLabel : ui.executedLabel;

            const proposedCommands: ProposedCmd[] = ((it as any)?.proposedCommands as ProposedCmd[]) ?? [];
            const hasApprovalId = Boolean((it as any)?.approvalRequestId);

            return (
              <div className="ceoRow left" key={it.id}>
                <div className="govCard">
                  <div className="govTop">
                    <div className="govTitle">{it.title ?? ""}</div>
                    <div className={`govBadge ${badgeClass}`}>{badgeText}</div>
                  </div>

                  <div className="govBody">
                    {it.summary ? <div className="govSummary">{it.summary}</div> : null}

                    {proposedCommands.length > 0 ? (
                      <div style={{ marginTop: 10 }}>
                        <ul className="govReasons" style={{ marginTop: 0 }}>
                          {proposedCommands.map((p, idx) => {
                            const label = proposalLabel(p, idx);

                            return (
                              <li key={`${it.id}_p_${idx}`}>
                                <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                                  <span style={{ fontWeight: 600 }}>{label}</span>

                                  <div style={{ display: "flex", gap: 8, marginLeft: "auto", flexWrap: "wrap" }}>
                                    <button
                                      className="govButton"
                                      onClick={() => void handleApproveProposal(p)}
                                      disabled={busy === "submitting" || busy === "streaming" || notionLoading}
                                      title="Create execution and approve"
                                    >
                                      Approve
                                    </button>

                                    <button
                                      className="govButton"
                                      onClick={() => removeItem(it.id)}
                                      disabled={busy === "submitting" || busy === "streaming" || notionLoading}
                                      title="Dismiss (no backend action)"
                                    >
                                      Dismiss
                                    </button>

                                    <button
                                      className="govButton"
                                      onClick={() => void handleCreateExecutionFromProposal(p)}
                                      disabled={busy === "submitting" || busy === "streaming" || notionLoading}
                                      title="Create execution only (BLOCKED)"
                                    >
                                      Create (Blocked)
                                    </button>
                                  </div>
                                </div>
                              </li>
                            );
                          })}
                        </ul>
                      </div>
                    ) : null}

                    {hasApprovalId ? (
                      <div className="govActions">
                        <button className="govButton" onClick={() => handleOpenApprovals((it as any).approvalRequestId)}>
                          {ui.openApprovalsLabel}
                        </button>

                        {it.state === "BLOCKED" ? (
                          <>
                            <button
                              className="govButton"
                              onClick={() => void handleApprove((it as any).approvalRequestId)}
                              disabled={busy === "submitting" || busy === "streaming" || notionLoading}
                            >
                              {ui.approveLabel}
                            </button>

                            <button
                              className="govButton"
                              onClick={() => void handleReject((it as any).approvalRequestId)}
                              disabled={busy === "submitting" || busy === "streaming" || notionLoading}
                              title="Requires backend support for /approval/reject"
                            >
                              Disapprove
                            </button>
                          </>
                        ) : null}
                      </div>
                    ) : null}
                  </div>
                </div>
              </div>
            );
          })}

          {lastError || notionLastError ? (
            <div className="ceoRow left">
              <div className="govCard">
                <div className="govTop">
                  <div className="govTitle">{""}</div>
                  <div className="govBadge blocked">{ui.blockedLabel}</div>
                </div>
                <div className="govBody">
                  <div className="govSummary">{notionLastError ? `Notion read: ${notionLastError}` : lastError}</div>
                  <div className="govActions">
                    <button className="govButton" onClick={retryLast}>
                      {ui.retryLabel}
                    </button>
                  </div>
                </div>
              </div>
            </div>
          ) : null}
        </div>
      </div>

      <footer className="ceoComposer">
        {/* NOTION READ PANEL */}
        <div
          style={{
            display: "flex",
            gap: 8,
            flexWrap: "wrap",
            alignItems: "center",
            padding: "8px 0 10px 0",
            borderTop: "1px solid rgba(255,255,255,0.08)",
            marginTop: 8,
          }}
        >
          <div style={{ fontWeight: 600, opacity: 0.9 }}>{(ui as any).searchNotionLabel ?? "Search Notion"}</div>

          <input
            value={notionQuery}
            onChange={(e) => setNotionQuery(e.target.value)}
            placeholder={(ui as any).searchQueryPlaceholder ?? 'Document title (e.g. "Outreach SOP")…'}
            disabled={notionLoading || busy === "submitting" || busy === "streaming"}
            style={{
              padding: "8px 10px",
              borderRadius: 10,
              border: "1px solid rgba(255,255,255,0.12)",
              background: "transparent",
              color: "inherit",
              flex: "1 1 320px",
              minWidth: 240,
            }}
          />

          <button
            className="ceoHeaderButton"
            onClick={() => void runNotionSearch()}
            disabled={notionLoading || busy === "submitting" || busy === "streaming" || !notionQuery.trim()}
            title="Read Notion page by title (backend)"
          >
            {notionLoading ? ((ui as any).searchingLabel ?? "Searching…") : ((ui as any).runSearchLabel ?? "Search")}
          </button>
        </div>

        {/* CHAT COMPOSER */}
        <div className="ceoComposerInner">
          <textarea
            className="ceoTextarea"
            value={draft}
            placeholder={ui.inputPlaceholder}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={onKeyDown}
            disabled={busy === "submitting" || busy === "streaming"}
            rows={1}
          />

          {enableVoice && voiceSupported ? (
            <button
              className="ceoSendBtn"
              onClick={toggleVoice}
              disabled={busy === "submitting" || busy === "streaming"}
              title={listening ? "Stop voice input" : "Start voice input"}
              style={{ width: 120 }}
            >
              {listening ? "Listening…" : "Voice"}
            </button>
          ) : null}

          <button className="ceoSendBtn" onClick={() => void submit()} disabled={!canSend}>
            {ui.sendLabel}
          </button>
        </div>

        <div className="ceoHintRow">
          <span>{""}</span>
          <span>{""}</span>
        </div>

        {showTyping ? (
          <span style={{ display: "none" }} aria-live="polite">
            {ui.processingLabel}
          </span>
        ) : null}
      </footer>
    </section>
  );
};

declare global {
  // eslint-disable-next-line @typescript-eslint/no-namespace
  namespace JSX {
    // eslint-disable-next-line @typescript-eslint/no-empty-interface
    interface IntrinsicElements {
      [elemName: string]: any;
    }
  }
}
