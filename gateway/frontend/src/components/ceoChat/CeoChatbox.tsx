// gateway/frontend/src/components/ceoChat/CeoChatbox.tsx
import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type {
  ChatItem,
  ChatMessageItem,
  GovernanceEventItem,
  NormalizedConsoleResponse,
  UiStrings,
  CeoCommandRequest,
} from "./types";
import type { CeoConsoleApi } from "./api";
import { createCeoConsoleApi } from "./api";
import { defaultStrings } from "./strings";
import { useAutoScroll } from "./hooks";
import "./CeoChatbox.css";

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
  approveUrl?: string; // if not provided, we fall back to /api/ai-ops/approval/approve
  executeRawUrl?: string; // if not provided, we fall back to /api/execute/raw
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

const toGovernanceCard = (
  resp: NormalizedConsoleResponse
): GovernanceEventItem | null => {
  if (!resp.governance) return null;
  return {
    id: uid(),
    kind: "governance",
    createdAt: now(),
    state: resp.governance.state,
    title: resp.governance.title,
    summary: resp.governance.summary,
    reasons: resp.governance.reasons,
    approvalRequestId: resp.governance.approvalRequestId,
    requestId: resp.requestId,
  };
};

// ---------
// EXTRA: extract proposed_commands from normalized response (defensive)
// ---------
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
  if (!x || typeof x !== "object") return "";
  const keys = ["systemText", "summary", "text", "message", "output_text", "outputText"];
  for (const k of keys) {
    const v = (x as any)[k];
    if (typeof v === "string" && v.trim()) return v.trim();
  }
  return "";
};

export const CeoChatbox: React.FC<CeoChatboxProps> = ({
  ceoCommandUrl,
  approveUrl,
  executeRawUrl,
  headers,
  strings,
  onOpenApprovals,
  className,
}) => {
  const ui = useMemo(
    () => ({ ...defaultStrings, ...(strings ?? {}) }),
    [strings]
  );

  const api: CeoConsoleApi = useMemo(
    () => createCeoConsoleApi({ ceoCommandUrl, approveUrl, headers }),
    [ceoCommandUrl, approveUrl, headers]
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
    setItems((prev) =>
      prev.map((x) =>
        x.id === id
          ? ({ ...x, ...(patch as any) } as ChatItem)
          : x
      )
    );
  }, []);

  const stopCurrent = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    setBusy("idle");
  }, []);

  const flushResponseToUi = useCallback(
    async (placeholderId: string, resp: NormalizedConsoleResponse) => {
      if (resp.stream) {
        setBusy("streaming");
        updateItem(placeholderId, { content: "", status: "streaming" });

        let acc = "";
        try {
          for await (const chunk of resp.stream) {
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

      // IMPORTANT: backend često vraća summary; systemText je normalizacija
      const sysText = String(
        (resp as any).systemText ?? (resp as any).summary ?? (resp as any).text ?? ""
      );

      updateItem(placeholderId, { content: sysText, status: "final" });

      const gov = toGovernanceCard(resp);
      if (gov) appendItem(gov);

      setBusy("idle");
      setLastError(null);
    },
    [appendItem, updateItem, isPinnedToBottom, scrollToBottom]
  );

  // ---------
  // AUTO EXECUTION: execute/raw + approve, based on proposed_commands
  // ---------
  const autoExecuteFirstProposed = useCallback(
    async (resp: NormalizedConsoleResponse, signal: AbortSignal) => {
      const proposed = _extractProposedCommands(resp as any);
      if (!proposed.length) return null;

      const first = proposed[0];
      const cmd = first.command_type;

      // Only auto-execute a whitelisted safe command
      if (cmd !== "refresh_snapshot") return null;

      const execUrl = executeRawUrl ?? "/api/execute/raw";
      const appUrl = approveUrl ?? "/api/ai-ops/approval/approve";

      const mergedHeaders: Record<string, string> = {
        "Content-Type": "application/json",
        ...(headers ?? {}),
      };

      const execBody = {
        command: cmd,
        intent: cmd,
        params:
          first.payload && typeof first.payload === "object" && !Array.isArray(first.payload)
            ? first.payload
            : { source: "ceo_dashboard" },
        initiator: "ceo",
        read_only: false,
        metadata: { origin: "ceo_chatbox_auto" },
      };

      const execRes = await fetch(execUrl, {
        method: "POST",
        headers: mergedHeaders,
        body: JSON.stringify(execBody),
        signal,
      });

      const execText = await execRes.text();
      if (!execRes.ok) {
        throw new Error(
          `execute/raw failed (${execRes.status}): ${execText || "no body"}`
        );
      }

      let execJson: any = {};
      try {
        execJson = execText ? JSON.parse(execText) : {};
      } catch {
        execJson = {};
      }

      const approvalId: string | null =
        typeof execJson?.approval_id === "string" && execJson.approval_id
          ? execJson.approval_id
          : null;

      // Ako nema approval_id, vrati rezultat executor-a
      if (!approvalId) return execJson;

      const approveRes = await fetch(appUrl, {
        method: "POST",
        headers: mergedHeaders,
        body: JSON.stringify({ approval_id: approvalId }),
        signal,
      });

      const approveText = await approveRes.text();
      if (!approveRes.ok) {
        throw new Error(
          `approve failed (${approveRes.status}): ${approveText || "no body"}`
        );
      }

      let approveJson: any = {};
      try {
        approveJson = approveText ? JSON.parse(approveText) : {};
      } catch {
        approveJson = {};
      }

      return approveJson;
    },
    [approveUrl, executeRawUrl, headers]
  );

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
      // Legacy request shape (api layer treba normalizovati na backend {text,...})
      const req: CeoCommandRequest = {
        input_text: trimmed,
        smart_context: {},
        source: "ceo_dashboard",
      };

      const resp = await api.sendCommand(req, controller.signal);

      // 1) prikazi odgovor odmah
      await flushResponseToUi(placeholder.id, resp);

      // 2) pokušaj auto-exec (proposal -> execute/raw -> approve)
      try {
        const execResult = await autoExecuteFirstProposed(resp, controller.signal);
        if (execResult) {
          const text =
            _pickText(execResult) ||
            (execResult?.execution_state
              ? `Izvršeno: ${execResult.execution_state}`
              : "Izvršeno.");

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
          content: `Ne mogu automatski izvršiti proposal.\n${msg}`,
          status: "final",
          createdAt: now(),
          requestId: clientRequestId,
        } as ChatMessageItem);
      }

      abortRef.current = null;
      setBusy("idle");
      setLastError(null);
    } catch (e) {
      abortRef.current = null;
      const msg = e instanceof Error ? e.message : String(e);
      updateItem(placeholder.id, { status: "error", content: "" });
      setBusy("error");
      setLastError(msg);
    }
  }, [
    api,
    appendItem,
    autoExecuteFirstProposed,
    busy,
    draft,
    flushResponseToUi,
    updateItem,
  ]);

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

  const handleOpenApprovals = useCallback(
    (approvalRequestId?: string) => {
      if (onOpenApprovals) onOpenApprovals(approvalRequestId);
      else {
        window.dispatchEvent(
          new CustomEvent("ceo:openApprovals", {
            detail: { approvalRequestId },
          })
        );
      }
    },
    [onOpenApprovals]
  );

  const handleApprove = useCallback(
    async (approvalId: string) => {
      if (!approveUrl) {
        handleOpenApprovals(approvalId);
        return;
      }

      if (busy === "submitting" || busy === "streaming") return;

      setBusy("submitting");
      setLastError(null);

      const placeholder = makeSystemProcessingItem(approvalId);
      appendItem(placeholder);

      const controller = new AbortController();
      abortRef.current = controller;

      try {
        const resp = await api.approve(approvalId, controller.signal);
        abortRef.current = null;
        await flushResponseToUi(placeholder.id, resp);
      } catch (e) {
        abortRef.current = null;
        const msg = e instanceof Error ? e.message : String(e);
        updateItem(placeholder.id, { status: "error", content: "" });
        setBusy("error");
        setLastError(msg);
      }
    },
    [
      api,
      appendItem,
      approveUrl,
      busy,
      flushResponseToUi,
      handleOpenApprovals,
      updateItem,
    ]
  );

  const retryLast = useCallback(() => {
    setBusy("idle");
    setLastError(null);
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
            {(busy === "submitting" || busy === "streaming") && (
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
                    {it.role === "system" &&
                    it.status === "streaming" &&
                    !it.content ? (
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
              it.state === "BLOCKED"
                ? "blocked"
                : it.state === "APPROVED"
                ? "approved"
                : "executed";

            const badgeText =
              it.state === "BLOCKED"
                ? ui.blockedLabel
                : it.state === "APPROVED"
                ? ui.approvedLabel
                : ui.executedLabel;

            return (
              <div className="ceoRow left" key={it.id}>
                <div className="govCard">
                  <div className="govTop">
                    <div className="govTitle">{it.title ?? ""}</div>
                    <div className={`govBadge ${badgeClass}`}>{badgeText}</div>
                  </div>

                  <div className="govBody">
                    {it.summary ? (
                      <div className="govSummary">{it.summary}</div>
                    ) : null}

                    {it.reasons && it.reasons.length > 0 ? (
                      <ul className="govReasons">
                        {it.reasons.map((r, idx) => (
                          <li key={`${it.id}_r_${idx}`}>{r}</li>
                        ))}
                      </ul>
                    ) : null}

                    <div className="govActions">
                      <button
                        className="govButton"
                        onClick={() => handleOpenApprovals(it.approvalRequestId)}
                      >
                        {ui.openApprovalsLabel}
                      </button>

                      {it.state === "BLOCKED" && it.approvalRequestId ? (
                        <button
                          className="govButton"
                          onClick={() => handleApprove(it.approvalRequestId!)}
                          disabled={busy === "submitting" || busy === "streaming"}
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

          {lastError ? (
            <div className="ceoRow left">
              <div className="govCard">
                <div className="govTop">
                  <div className="govTitle">{""}</div>
                  <div className="govBadge blocked">{ui.blockedLabel}</div>
                </div>
                <div className="govBody">
                  <div className="govSummary">{lastError}</div>
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
          <button
            className="ceoSendBtn"
            onClick={() => void submit()}
            disabled={!canSend}
          >
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

/**
 * HARD FIX (local, file-level):
 * Ako TypeScript u projektu trenutno nema React JSX types, VSCode prijavi:
 * "no interface JSX.IntrinsicElements exists" i podcrta SVE JSX elemente.
 * Ovaj blok uklanja tu blokadu da fajl kompilira odmah.
 *
 * (Kad središ dependency/tsconfig kasnije, ovaj blok možeš obrisati.)
 */
declare global {
  // eslint-disable-next-line @typescript-eslint/no-namespace
  namespace JSX {
    // eslint-disable-next-line @typescript-eslint/no-empty-interface
    interface IntrinsicElements {
      [elemName: string]: any;
    }
  }
}
