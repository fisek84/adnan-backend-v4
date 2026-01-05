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
  executeRawUrl?: string; // POST { command,intent,params,initiator,read_only,metadata }
  headers?: Record<string, string>;
  strings?: Partial<UiStrings>;
  onOpenApprovals?: (approvalRequestId?: string) => void;
  className?: string;
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

type ProposedCmd = {
  command_type: string;
  payload: Record<string, any>;
  required_approval?: boolean;
  status?: string;
};

const _extractProposedCommands = (resp: any): ProposedCmd[] => {
  const candidates = [
    resp?.proposed_commands,
    resp?.proposedCommands,
    resp?.raw?.proposed_commands,
    resp?.raw?.proposedCommands,
    resp?.result?.proposed_commands,
    resp?.result?.proposedCommands,
    resp?.governance?.proposed_commands,
  ];

  for (const c of candidates) {
    if (!Array.isArray(c)) continue;
    const out: ProposedCmd[] = [];
    for (const x of c) {
      if (!x || typeof x !== "object") continue;
      const command_type = String(
        x.command_type ?? x.commandType ?? x.command ?? x.command_name ?? ""
      ).trim();
      const payloadRaw = x.payload ?? x.args ?? x.params ?? {};
      const payload =
        payloadRaw && typeof payloadRaw === "object" && !Array.isArray(payloadRaw)
          ? payloadRaw
          : {};
      if (!command_type) continue;
      out.push({
        command_type,
        payload,
        required_approval: Boolean(
          x.required_approval ?? x.requires_approval ?? x.requiresApproval ?? true
        ),
        status: typeof x.status === "string" ? x.status : undefined,
      });
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

const _looksLikeFailedAgentRun = (resp: any): boolean => {
  const t = String(resp?.systemText ?? resp?.text ?? resp?.summary ?? "").toLowerCase() || "";
  if (t.includes("agent execution failed")) return true;
  if (t.includes("failed") && t.includes("agent")) return true;
  const preferred = String(resp?.raw?.trace?.preferred_agent_id ?? "").toLowerCase();
  if (preferred === "notion_ops" && t.includes("failed")) return true;
  return false;
};

function safeJsonStringify(x: any, maxLen = 6000): string {
  try {
    const s = JSON.stringify(x, null, 2);
    if (s.length <= maxLen) return s;
    return s.slice(0, maxLen) + "\n…(truncated)…";
  } catch {
    return String(x ?? "");
  }
}

function isAbortError(e: unknown): boolean {
  const msg = e instanceof Error ? e.message : String(e ?? "");
  return msg.toLowerCase().includes("aborted") || msg.toLowerCase().includes("abort");
}

export const CeoChatbox: React.FC<CeoChatboxProps> = ({
  ceoCommandUrl,
  approveUrl,
  executeRawUrl,
  headers,
  strings,
  onOpenApprovals,
  className,
}) => {
  const ui = useMemo(() => ({ ...defaultStrings, ...(strings ?? {}) }), [strings]);

  // Ensure api always has a usable approveUrl (avoid undefined inside api.ts).
  const effectiveApproveUrl = approveUrl?.trim() ? approveUrl : "/api/ai-ops/approval/approve";

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

      const sysText = (resp as any).systemText ?? (resp as any).summary ?? (resp as any).text ?? "";
      updateItem(placeholderId, { content: sysText, status: "final" });

      const gov = toGovernanceCard(resp);
      if (gov) appendItem(gov);

      const proposals = _extractProposedCommands(resp as any);
      if (proposals.length > 0) {
        appendItem({
          id: uid(),
          kind: "governance",
          createdAt: now(),
          state: "BLOCKED",
          title: "Proposed commands",
          summary: "Select a proposal to create an approval and execute (governance gate).",
          reasons: proposals.map((p) => p.command_type),
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

  // Optional: auto execute only refresh_snapshot
  const autoExecuteFirstProposed = useCallback(
    async (resp: NormalizedConsoleResponse, signal: AbortSignal) => {
      const proposed = _extractProposedCommands(resp as any);
      if (!proposed.length) return null;

      const first = proposed[0];
      const cmd = first.command_type;
      if (cmd !== "refresh_snapshot") return null;

      const execUrl = resolveUrl(executeRawUrl, "/api/execute/raw");
      const appUrl = resolveUrl(effectiveApproveUrl, "/api/ai-ops/approval/approve");

      const execBody = {
        command: cmd,
        intent: cmd,
        params: { source: "ceo_dashboard", ...(first.payload || {}) },
        initiator: "ceo",
        read_only: false,
        metadata: { origin: "ceo_chatbox_auto" },
      };

      const execJson = await postJson(execUrl, execBody, signal);

      const approvalId: string | null =
        typeof execJson?.approval_id === "string" && execJson.approval_id ? execJson.approval_id : null;

      if (!approvalId) return execJson;

      const approveJson = await postJson(appUrl, { approval_id: approvalId }, signal);
      return approveJson;
    },
    [effectiveApproveUrl, executeRawUrl, postJson, resolveUrl]
  );

  const handleOpenApprovals = useCallback(
    (approvalRequestId?: string) => {
      if (onOpenApprovals) onOpenApprovals(approvalRequestId);
      else {
        window.dispatchEvent(new CustomEvent("ceo:openApprovals", { detail: { approvalRequestId } }));
      }
    },
    [onOpenApprovals]
  );

  const handleCreateApprovalFromProposal = useCallback(
    async (proposal: ProposedCmd) => {
      if (busy === "submitting" || busy === "streaming") return;

      setBusy("submitting");
      setLastError(null);

      const placeholder = makeSystemProcessingItem("proposal");
      appendItem(placeholder);

      const controller = new AbortController();
      abortRef.current = controller;

      try {
        const execUrl = resolveUrl(executeRawUrl, "/api/execute/raw");
        const execBody = {
          command: proposal.command_type,
          intent: proposal.command_type,
          params: proposal.payload || {},
          initiator: "ceo",
          read_only: false,
          metadata: { origin: "ceo_chatbox_proposal", proposal_command_type: proposal.command_type },
        };

        const execJson = await postJson(execUrl, execBody, controller.signal);

        const approvalId: string | null =
          typeof execJson?.approval_id === "string" && execJson.approval_id ? execJson.approval_id : null;

        const msg = approvalId?.trim() ? `Approval created: ${approvalId}` : _pickText(execJson) || "Approval created.";
        updateItem(placeholder.id, { content: msg, status: "final" });

        abortRef.current = null;
        setBusy("idle");
        setLastError(null);

        if (approvalId) handleOpenApprovals(approvalId);
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

  const handleApproveAndExecuteProposal = useCallback(
    async (proposal: ProposedCmd) => {
      if (busy === "submitting" || busy === "streaming") return;

      setBusy("submitting");
      setLastError(null);

      const placeholder = makeSystemProcessingItem("proposal_execute");
      appendItem(placeholder);

      const controller = new AbortController();
      abortRef.current = controller;

      try {
        const execUrl = resolveUrl(executeRawUrl, "/api/execute/raw");
        const appUrl = resolveUrl(effectiveApproveUrl, "/api/ai-ops/approval/approve");

        const execBody = {
          command: proposal.command_type,
          intent: proposal.command_type,
          params: proposal.payload || {},
          initiator: "ceo",
          read_only: false,
          metadata: { origin: "ceo_chatbox_proposal", proposal_command_type: proposal.command_type },
        };

        const execJson = await postJson(execUrl, execBody, controller.signal);

        const approvalId: string | null =
          typeof execJson?.approval_id === "string" && execJson.approval_id ? execJson.approval_id : null;

        if (!approvalId) {
          const msg =
            _pickText(execJson) || (execJson?.execution_state ? `Execution: ${execJson.execution_state}` : "Executed.");
          updateItem(placeholder.id, { content: msg, status: "final" });
          abortRef.current = null;
          setBusy("idle");
          setLastError(null);
          return;
        }

        const approveJson = await postJson(appUrl, { approval_id: approvalId }, controller.signal);

        const msg =
          _pickText(approveJson) ||
          (approveJson?.execution_state ? `Execution: ${approveJson.execution_state}` : "Approved & executed.");

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
    [appendItem, effectiveApproveUrl, busy, executeRawUrl, postJson, resolveUrl, updateItem]
  );

  // ------------------------------
  // NOTION SEARCH (generic DB)
  // ------------------------------
  const [notionDbs, setNotionDbs] = useState<Record<string, string>>({});
  const [notionDbKey, setNotionDbKey] = useState<string>("__ALL__");
  const [notionContains, setNotionContains] = useState<string>("");
  const [notionLoading, setNotionLoading] = useState<boolean>(false);
  const [notionLastError, setNotionLastError] = useState<string | null>(null);

  const reloadNotionDatabases = useCallback(
    async (signal?: AbortSignal) => {
      setNotionLastError(null);
      setNotionLoading(true);
      try {
        const res = await (api as any).listNotionDatabases?.(signal);
        const dbs = res?.databases && typeof res.databases === "object" ? res.databases : {};
        setNotionDbs(dbs);
      } catch (e) {
        const msg = e instanceof Error ? e.message : String(e);
        if (!isAbortError(e)) setNotionLastError(msg);
      } finally {
        setNotionLoading(false);
      }
    },
    [api]
  );

  useEffect(() => {
    const controller = new AbortController();
    void reloadNotionDatabases(controller.signal);
    return () => controller.abort();
  }, [reloadNotionDatabases]);

  const runNotionSearch = useCallback(async () => {
    const q = notionContains.trim();
    if (!q) {
      setNotionLastError("Unesi tekst za pretragu (contains).");
      return;
    }
    if (busy === "submitting" || busy === "streaming") return;

    const dbKeys = Object.keys(notionDbs || {});
    const keysToSearch = notionDbKey === "__ALL__" ? dbKeys : notionDbKey ? [notionDbKey] : [];

    if (!keysToSearch.length) {
      setNotionLastError("Nema dostupnih Notion baza (db_key list je prazna).");
      return;
    }

    setNotionLastError(null);
    setNotionLoading(true);

    const placeholder = makeSystemProcessingItem("notion_search");
    appendItem(placeholder);

    const controller = new AbortController();
    abortRef.current = controller;

    try {
      // PO BAZI: hvataj error i nastavi
      const results: Record<string, any> = {};

      for (const k of keysToSearch) {
        try {
          // Best-effort filter: Name.title.contains (najčešći)
          const spec = {
            db_key: k,
            filter: {
              property: "Name",
              title: { contains: q },
            },
            page_size: 10,
          };

          const r = await (api as any).notionBulkQuery?.({ queries: [spec] }, controller.signal);
          results[k] = r;
        } catch (e) {
          const msg = e instanceof Error ? e.message : String(e);
          results[k] = { ok: false, error: msg };
          if (isAbortError(e)) break;
        }
      }

      const text =
        `Notion Search (contains="${q}")\n` +
        `Baze: ${keysToSearch.join(", ")}\n\n` +
        safeJsonStringify(results);

      updateItem(placeholder.id, { content: text, status: "final" });

      abortRef.current = null;
      setNotionLoading(false);
      setBusy("idle");
      setLastError(null);
    } catch (e) {
      abortRef.current = null;
      const msg = e instanceof Error ? e.message : String(e);
      updateItem(placeholder.id, { status: "error", content: "" });
      setNotionLoading(false);
      setBusy(isAbortError(e) ? "idle" : "error");
      setNotionLastError(isAbortError(e) ? null : msg);
      setLastError(isAbortError(e) ? null : msg);
    }
  }, [api, appendItem, busy, notionContains, notionDbKey, notionDbs, updateItem]);

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
        text: trimmed,
        initiator: "ceo_dashboard",
        context_hint: {},
      };

      let resp = await api.sendCommand(req, controller.signal);

      const proposals1 = _extractProposedCommands(resp as any);
      if (
        proposals1.length < 1 &&
        (_looksLikeFailedAgentRun(resp as any) ||
          String((resp as any)?.systemText ?? "").toLowerCase().includes("failed"))
      ) {
        const chatUrl = resolveUrl(undefined, "/api/chat");
        const chatJson = await postJson(
          chatUrl,
          { message: trimmed, initiator: "ceo_dashboard", context_hint: req.context_hint },
          controller.signal
        );

        resp = {
          systemText: (chatJson?.text as any) ?? (chatJson?.summary as any) ?? (chatJson?.message as any) ?? "",
          raw: chatJson,
          proposed_commands: chatJson?.proposed_commands ?? chatJson?.proposedCommands ?? [],
        } as any;
      }

      abortRef.current = null;

      await flushResponseToUi(placeholder.id, resp);

      try {
        const execResult = await autoExecuteFirstProposed(resp, controller.signal);
        if (execResult) {
          const text =
            _pickText(execResult) ||
            (execResult?.execution_state ? `Izvršeno: ${execResult.execution_state}` : "Izvršeno.");

          appendItem({
            id: uid(),
            kind: "message",
            role: "system",
            content: text,
            status: "final",
            createdAt: now(),
            requestId: clientRequestId,
          } as ChatMessageItem);
        }
      } catch (e) {
        const msg = e instanceof Error ? e.message : String(e);
        appendItem({
          id: uid(),
          kind: "message",
          role: "system",
          content: `Auto-exec nije uspio.\n${msg}`,
          status: "final",
          createdAt: now(),
          requestId: clientRequestId,
        } as ChatMessageItem);
      }

      setBusy("idle");
      setLastError(null);
    } catch (e) {
      abortRef.current = null;
      const msg = e instanceof Error ? e.message : String(e);
      updateItem(placeholder.id, { status: "error", content: "" });
      setBusy(isAbortError(e) ? "idle" : "error");
      setLastError(isAbortError(e) ? null : msg);
    }
  }, [api, appendItem, autoExecuteFirstProposed, busy, draft, flushResponseToUi, postJson, resolveUrl, updateItem]);

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
                it.status === "error" ? "ceoStatusDot err" : it.status === "final" ? "ceoStatusDot ok" : "ceoStatusDot";

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
                      it.content
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

            const badgeText = it.state === "BLOCKED" ? ui.blockedLabel : it.state === "APPROVED" ? ui.approvedLabel : ui.executedLabel;

            const proposedCommands: ProposedCmd[] = ((it as any)?.proposedCommands as ProposedCmd[]) ?? [];

            return (
              <div className="ceoRow left" key={it.id}>
                <div className="govCard">
                  <div className="govTop">
                    <div className="govTitle">{it.title ?? ""}</div>
                    <div className={`govBadge ${badgeClass}`}>{badgeText}</div>
                  </div>

                  <div className="govBody">
                    {it.summary ? <div className="govSummary">{it.summary}</div> : null}

                    {it.reasons && it.reasons.length > 0 ? (
                      <ul className="govReasons">
                        {it.reasons.map((r, idx) => (
                          <li key={`${it.id}_r_${idx}`}>{r}</li>
                        ))}
                      </ul>
                    ) : null}

                    {proposedCommands.length > 0 ? (
                      <div style={{ marginTop: 10 }}>
                        <div className="govSummary" style={{ marginBottom: 8 }}>
                          Proposals (requires approval):
                        </div>

                        <ul className="govReasons" style={{ marginTop: 0 }}>
                          {proposedCommands.map((p, idx) => (
                            <li key={`${it.id}_p_${idx}`}>
                              <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                                <span style={{ fontWeight: 600 }}>{p.command_type}</span>
                                {p.required_approval ? <span style={{ opacity: 0.8 }}>(approval)</span> : null}
                              </div>

                              <div style={{ display: "flex", gap: 8, marginTop: 8, flexWrap: "wrap" }}>
                                <button
                                  className="govButton"
                                  onClick={() => void handleApproveAndExecuteProposal(p)}
                                  disabled={busy === "submitting" || busy === "streaming" || notionLoading}
                                >
                                  Approve & Execute
                                </button>

                                <button
                                  className="govButton"
                                  onClick={() => void handleCreateApprovalFromProposal(p)}
                                  disabled={busy === "submitting" || busy === "streaming" || notionLoading}
                                >
                                  Create Approval
                                </button>
                              </div>
                            </li>
                          ))}
                        </ul>
                      </div>
                    ) : null}

                    <div className="govActions">
                      <button className="govButton" onClick={() => handleOpenApprovals(it.approvalRequestId)}>
                        {ui.openApprovalsLabel}
                      </button>

                      {it.state === "BLOCKED" && it.approvalRequestId ? (
                        <button
                          className="govButton"
                          onClick={() => void handleApprove(it.approvalRequestId!)}
                          disabled={busy === "submitting" || busy === "streaming" || notionLoading}
                        >
                          {ui.approveLabel}
                        </button>
                      ) : null}
                    </div>
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
                  <div className="govSummary">{notionLastError ? `Notion search: ${notionLastError}` : lastError}</div>
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
        {/* NOTION SEARCH PANEL */}
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

          <select
            value={notionDbKey}
            onChange={(e) => setNotionDbKey(e.target.value)}
            disabled={notionLoading || busy === "submitting" || busy === "streaming"}
            style={{
              padding: "8px 10px",
              borderRadius: 10,
              border: "1px solid rgba(255,255,255,0.12)",
              background: "transparent",
              color: "inherit",
              minWidth: 180,
            }}
            title={(ui as any).chooseDatabaseLabel ?? "Database"}
          >
            <option value="__ALL__">ALL databases</option>
            {Object.keys(notionDbs || {})
              .sort()
              .map((k) => (
                <option key={k} value={k}>
                  {k}
                </option>
              ))}
          </select>

          <input
            value={notionContains}
            onChange={(e) => setNotionContains(e.target.value)}
            placeholder={(ui as any).searchQueryPlaceholder ?? 'Search text…'}
            disabled={notionLoading || busy === "submitting" || busy === "streaming"}
            style={{
              padding: "8px 10px",
              borderRadius: 10,
              border: "1px solid rgba(255,255,255,0.12)",
              background: "transparent",
              color: "inherit",
              flex: "1 1 280px",
              minWidth: 220,
            }}
          />

          <button
            className="ceoHeaderButton"
            onClick={() => void runNotionSearch()}
            disabled={notionLoading || busy === "submitting" || busy === "streaming" || !notionContains.trim()}
            title="POST /notion-ops/bulk/query"
          >
            {notionLoading ? ((ui as any).searchingLabel ?? "Searching…") : ((ui as any).runSearchLabel ?? "Search")}
          </button>

          <button
            className="ceoHeaderButton"
            onClick={() => {
              const controller = new AbortController();
              abortRef.current = controller;
              void reloadNotionDatabases(controller.signal);
            }}
            disabled={notionLoading || busy === "submitting" || busy === "streaming"}
            title="Reload list of databases"
          >
            {(ui as any).loadDatabasesLabel ?? "Load databases"}
          </button>

          <div style={{ opacity: 0.7, fontSize: 12 }}>DBs: {Object.keys(notionDbs || {}).length}</div>
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
