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
  executeRawUrl?: string; // POST canonical proposal payload (opaque)
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

function safeJsonStringify(x: any, maxLen = 6000): string {
  try {
    const s = JSON.stringify(x, null, 2);
    if (s.length <= maxLen) return s;
    return s.slice(0, maxLen) + "\n…(truncated)…";
  } catch {
    return String(x ?? "");
  }
}

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
          summary:
            "Select EXACTLY ONE proposal to create execution (BLOCKED). Then approve via approval_id (approval gate).",
          reasons: proposals.map((p, idx) => {
            const label =
              typeof (p as any)?.command === "string"
                ? (p as any).command
                : typeof (p as any)?.intent === "string"
                  ? (p as any).intent
                  : typeof (p as any)?.command_type === "string"
                    ? (p as any).command_type
                    : `proposal_${idx + 1}`;
            return label;
          }),
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

  const handleOpenApprovals = useCallback(
    (approvalRequestId?: string) => {
      if (onOpenApprovals) onOpenApprovals(approvalRequestId);
      else window.dispatchEvent(new CustomEvent("ceo:openApprovals", { detail: { approvalRequestId } }));
    },
    [onOpenApprovals]
  );

  /**
   * CANON step 1:
   * Create execution (BLOCKED) from the EXACT proposal object (opaque payload) returned by /api/chat.
   * DO NOT rebuild/transform the proposal.
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

        // CANON: send proposal object 1:1
        const execJson = await postJson(execUrl, proposal, controller.signal);

        const approvalId: string | null =
          typeof execJson?.approval_id === "string" && execJson.approval_id ? execJson.approval_id : null;

        const executionId: string | null =
          typeof execJson?.execution_id === "string" && execJson.execution_id ? execJson.execution_id : null;

        const msg = approvalId?.trim()
          ? `Execution created (BLOCKED). approval_id: ${approvalId}`
          : _pickText(execJson) || "Execution created.";

        updateItem(placeholder.id, { content: msg, status: "final" });

        if (approvalId) {
          appendItem({
            id: uid(),
            kind: "governance",
            createdAt: now(),
            state: "BLOCKED",
            title: "Execution pending approval",
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
   * CANON step 2:
   * Approve using explicit approval_id (no implicit cached IDs).
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
      // Expected API method (added in api.ts):
      // notionReadPageByTitle(query) => { ok, title, notion_url, content_markdown, error }
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
      const notionUrl =
        typeof res.notion_url === "string" && res.notion_url.trim() ? res.notion_url.trim() : "";

      const contentMd =
        typeof res.content_markdown === "string" && res.content_markdown ? res.content_markdown : "";

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
      // CANON: CeoCommandRequest (api.ts will build /api/chat payload)
      // IMPORTANT: preferred_agent_id should be top-level for AgentInput compatibility.
      const req: any = {
        text: trimmed,
        initiator: "ceo_chat",
        preferred_agent_id: "ceo_advisor",
        context_hint: {
          preferred_agent_id: "ceo_advisor",
        },
      };

      const resp = await api.sendCommand(req, controller.signal);

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
                          Proposals (select EXACTLY ONE by clicking its button):
                        </div>

                        <ul className="govReasons" style={{ marginTop: 0 }}>
                          {proposedCommands.map((p, idx) => {
                            const label =
                              typeof (p as any)?.command === "string"
                                ? (p as any).command
                                : typeof (p as any)?.intent === "string"
                                  ? (p as any).intent
                                  : typeof (p as any)?.command_type === "string"
                                    ? (p as any).command_type
                                    : `proposal_${idx + 1}`;

                            return (
                              <li key={`${it.id}_p_${idx}`}>
                                <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                                  <span style={{ fontWeight: 600 }}>{label}</span>
                                </div>

                                <div style={{ marginTop: 8, opacity: 0.85, fontSize: 12, whiteSpace: "pre-wrap" }}>
                                  {safeJsonStringify(p, 1200)}
                                </div>

                                <div style={{ display: "flex", gap: 8, marginTop: 10, flexWrap: "wrap" }}>
                                  <button
                                    className="govButton"
                                    onClick={() => void handleCreateExecutionFromProposal(p)}
                                    disabled={busy === "submitting" || busy === "streaming" || notionLoading}
                                  >
                                    Create execution (BLOCKED)
                                  </button>
                                </div>
                              </li>
                            );
                          })}
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
            title="POST /api/notion/read"
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
