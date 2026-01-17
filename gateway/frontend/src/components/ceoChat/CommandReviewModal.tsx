// gateway/frontend/src/components/ceoChat/CommandReviewModal.tsx
import React, { useEffect, useMemo, useRef, useState } from "react";

type ReviewMode = "approve" | "fill_missing";

export type CommandReviewContract = {
  type: "command_review";
  mode: ReviewMode;
  title?: string;
  summary?: string;

  missing_fields?: string[];
  fields_schema?: Record<
    string,
    {
      type?: "select" | "text" | string;
      required?: boolean;
      options?: string[];
      placeholder?: string;
      label?: string;
    }
  >;

  draft?: Record<string, any>;

  // MUST be 1:1 identical to proposed_commands[0]
  proposed_command: Record<string, any>;
};

type Props = {
  open: boolean;
  onClose: () => void;

  review: CommandReviewContract | null;

  onApprove: (proposedCommand: Record<string, any>) => void;
  onDismiss: () => void;

  // for fill_missing: pass patch with canonical field keys (e.g. { Status: "Active", Priority: "High" })
  onSubmitMissingInfo: (patch: Record<string, any>) => void;
};

function clampJson(obj: any, maxLen = 12000): string {
  let s = "";
  try {
    s = JSON.stringify(obj ?? {}, null, 2);
  } catch {
    s = String(obj ?? "");
  }
  if (s.length <= maxLen) return s;
  return s.slice(0, maxLen) + "\n...(truncated)...";
}

function isNonEmptyString(x: any): x is string {
  return typeof x === "string" && x.trim().length > 0;
}

function pickFieldLabel(fieldKey: string, schema?: any): string {
  const lbl = schema?.label;
  if (isNonEmptyString(lbl)) return lbl.trim();
  return fieldKey;
}

function requiredFieldsFromReview(review: CommandReviewContract): string[] {
  const mf = Array.isArray(review.missing_fields) ? review.missing_fields.filter((x) => typeof x === "string") : [];
  if (mf.length) return mf;

  const sch = review.fields_schema && typeof review.fields_schema === "object" ? review.fields_schema : {};
  const required = Object.entries(sch)
    .filter(([, v]) => Boolean((v as any)?.required))
    .map(([k]) => k);
  return required;
}

export const CommandReviewModal: React.FC<Props> = ({
  open,
  onClose,
  review,
  onApprove,
  onDismiss,
  onSubmitMissingInfo,
}) => {
  const [local, setLocal] = useState<Record<string, any>>({});
  const [touched, setTouched] = useState<Record<string, boolean>>({});
  const [showAllFields, setShowAllFields] = useState(false);

  const [pos, setPos] = useState<{ x: number; y: number }>({ x: 0, y: 0 });
  const dragRef = useRef<{
    startX: number;
    startY: number;
    originX: number;
    originY: number;
    dragging: boolean;
  } | null>(null);

  const mode: ReviewMode = (review?.mode as ReviewMode) || "approve";

  const step = mode === "fill_missing" ? 1 : 2; // 0 Draft, 1 Missing info, 2 Ready, 3 Approved
  const steps = ["Draft", "Missing info", "Ready for approval", "Approved"];

  const requiredFields = useMemo(() => {
    if (!review) return [];
    if (mode !== "fill_missing") return [];
    return requiredFieldsFromReview(review);
  }, [review, mode]);

  const title = (review?.title as string) || "Command Review";
  const summary = (review?.summary as string) || "";
  const proposed = review?.proposed_command ?? null;

  const schema = useMemo(() => {
    const fs = review?.fields_schema;
    return fs && typeof fs === "object" ? fs : {};
  }, [review]);

  const schemaKeys = useMemo(() => Object.keys(schema || {}), [schema]);

  const fieldsToRender = useMemo(() => {
    // fill_missing: prvo required
    if (mode === "fill_missing") return requiredFields;

    // approve: prikaži bar nešto (schemaKeys) + opcija da pokaže sve
    if (showAllFields) return schemaKeys;

    // default u approve modu: pokaži "osnovna" ako postoje u schema
    const preferred = ["Status", "Priority", "Owner", "Deadline"].filter((k) => schemaKeys.includes(k));
    return preferred.length ? preferred : schemaKeys;
  }, [mode, requiredFields, schemaKeys, showAllFields]);

  useEffect(() => {
    if (!open || !review) return;

    // Prefill from review.draft if present
    const draft = review.draft && typeof review.draft === "object" ? review.draft : {};
    const init: Record<string, any> = {};

    const fs = review.fields_schema && typeof review.fields_schema === "object" ? review.fields_schema : {};
    const initKeys = mode === "fill_missing" ? requiredFieldsFromReview(review) : Object.keys(fs || {});

    for (const k of initKeys) {
      if (draft[k] !== undefined) init[k] = draft[k];
    }
    setLocal(init);
    setTouched({});
  }, [open, review, mode]);

  const errors = useMemo(() => {
    if (!review || mode !== "fill_missing") return {};
    const e: Record<string, string> = {};
    for (const k of requiredFields) {
      const v = local?.[k];
      const isEmpty = v === undefined || v === null || (typeof v === "string" && !v.trim());
      if (isEmpty) e[k] = "Required";
    }
    return e;
  }, [review, mode, requiredFields, local]);

  const canSubmit = mode === "approve" ? Boolean(review && proposed) : Object.keys(errors).length === 0;

  if (!open || !review) return null;

  const close = () => {
    onClose();
  };

  const handleDismiss = () => {
    onDismiss();
    close();
  };

  const handleApprove = () => {
    if (!proposed) return;
    onApprove(proposed);
    close();
  };

  const handleSubmitMissing = () => {
    const patch: Record<string, any> = {};
    for (const k of requiredFields) patch[k] = local?.[k];
    onSubmitMissingInfo(patch);
    close();
  };

  const onOverlayClick = (e: React.MouseEvent<HTMLDivElement>) => {
    const st = dragRef.current;
    if (st?.dragging) return;

    // click outside closes (enterprise modal behavior)
    if (e.target === e.currentTarget) close();
  };

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={title}
      onClick={onOverlayClick}
      style={{
        position: "fixed",
        inset: 0,
        zIndex: 9999,
        background: "rgba(0,0,0,0.55)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: 16,
      }}
    >
      <div
        style={{
          width: "min(720px, 96vw)",
          borderRadius: 18,
          border: "1px solid rgba(255,255,255,0.10)",
          background: "rgba(15, 23, 32, 0.98)",
          backdropFilter: "blur(14px)",
          boxShadow: "0 18px 60px rgba(0,0,0,0.55)",
          overflow: "hidden",
          color: "rgba(255,255,255,0.92)",
          fontFamily:
            'ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial, "Apple Color Emoji","Segoe UI Emoji"',
          position: "fixed",
          left: "50%",
          top: "12%",
          transform: `translate(-50%, 0px) translate(${pos.x}px, ${pos.y}px)`,
        }}
      >
        {/* Header */}
        <div
          onPointerDown={(e) => {
            // only primary button
            if ((e as any).button !== undefined && (e as any).button !== 0) return;
            // ignore if started on a button
            const target = e.target as HTMLElement;
            if (target?.closest?.("button")) return;

            (e.currentTarget as any).setPointerCapture?.(e.pointerId);

            dragRef.current = {
              startX: e.clientX,
              startY: e.clientY,
              originX: pos.x,
              originY: pos.y,
              dragging: true,
            };
          }}
          onPointerMove={(e) => {
            const st = dragRef.current;
            if (!st?.dragging) return;
            const dx = e.clientX - st.startX;
            const dy = e.clientY - st.startY;
            setPos({ x: st.originX + dx, y: st.originY + dy });
          }}
          onPointerUp={() => {
            const st = dragRef.current;
            if (st) st.dragging = false;
          }}
          style={{
            padding: "14px 16px",
            borderBottom: "1px solid rgba(255,255,255,0.08)",
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            gap: 12,
            cursor: "grab",
            userSelect: "none",
            touchAction: "none",
          }}
        >
          <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
            <div style={{ fontSize: 13, fontWeight: 650, letterSpacing: 0.2 }}>{title}</div>
            {summary ? (
              <div style={{ fontSize: 12, color: "rgba(255,255,255,0.64)", lineHeight: 1.4 }}>{summary}</div>
            ) : null}

            <div style={{ display: "flex", gap: 8, marginTop: 8, flexWrap: "wrap" }}>
              {steps.map((s, i) => {
                const active = i === step;
                const done = i < step;
                return (
                  <div
                    key={s}
                    style={{
                      fontSize: 11,
                      padding: "4px 8px",
                      borderRadius: 999,
                      border: "1px solid rgba(255,255,255,0.12)",
                      background: done
                        ? "rgba(34,197,94,0.16)"
                        : active
                          ? "rgba(59,130,246,0.16)"
                          : "rgba(255,255,255,0.04)",
                      color: "rgba(255,255,255,0.86)",
                      opacity: done || active ? 1 : 0.7,
                    }}
                  >
                    {s}
                  </div>
                );
              })}
            </div>
          </div>

          <button
            onClick={close}
            style={{
              border: "1px solid rgba(255,255,255,0.12)",
              background: "rgba(255,255,255,0.04)",
              color: "rgba(255,255,255,0.92)",
              borderRadius: 10,
              padding: "6px 10px",
              fontSize: 12,
              cursor: "pointer",
            }}
          >
            Close
          </button>
        </div>

        {/* Body */}
        <div style={{ padding: 16, display: "flex", flexDirection: "column", gap: 14 }}>
          {schemaKeys.length > 0 ? (
            <div
              style={{
                border: "1px solid rgba(255,255,255,0.08)",
                background: "rgba(255,255,255,0.03)",
                borderRadius: 14,
                padding: 12,
              }}
            >
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10 }}>
                <div style={{ fontSize: 12, fontWeight: 650 }}>
                  {mode === "fill_missing" ? "Missing information" : "Fields"}
                </div>

                {mode !== "fill_missing" && schemaKeys.length > 0 ? (
                  <button
                    onClick={() => setShowAllFields((p) => !p)}
                    style={{
                      border: "1px solid rgba(255,255,255,0.12)",
                      background: "rgba(255,255,255,0.02)",
                      color: "rgba(255,255,255,0.86)",
                      borderRadius: 10,
                      padding: "6px 10px",
                      fontSize: 12,
                      cursor: "pointer",
                      opacity: schemaKeys.length ? 1 : 0.7,
                    }}
                  >
                    {showAllFields ? "Hide extra fields" : "Show all fields"}
                  </button>
                ) : null}
              </div>

              <div style={{ height: 10 }} />

              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
                {fieldsToRender.map((fieldKey) => {
                  const fs: any = (schema as any)?.[fieldKey] ?? {};
                  const label = pickFieldLabel(fieldKey, fs);
                  const required = Boolean(fs?.required);
                  const options: string[] = Array.isArray(fs?.options)
                    ? fs.options.filter((x: any) => typeof x === "string")
                    : [];

                  const value = local?.[fieldKey] ?? "";
                  const showErr = Boolean(touched?.[fieldKey]) && Boolean((errors as any)?.[fieldKey]);

                  return (
                    <div key={fieldKey} style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                      <div style={{ fontSize: 12, color: "rgba(255,255,255,0.78)" }}>
                        {label} {required ? <span style={{ opacity: 0.7 }}>*</span> : null}
                      </div>

                      {options.length > 0 ? (
                        <select
                          value={String(value)}
                          onBlur={() => setTouched((p) => ({ ...p, [fieldKey]: true }))}
                          onChange={(e) => setLocal((p) => ({ ...p, [fieldKey]: e.target.value }))}
                          style={{
                            border: "1px solid rgba(255,255,255,0.12)",
                            background: "rgba(255,255,255,0.02)",
                            color: "rgba(255,255,255,0.92)",
                            borderRadius: 12,
                            padding: "10px 10px",
                            fontSize: 13,
                            outline: "none",
                          }}
                        >
                          <option value="" disabled>
                            Select...
                          </option>
                          {options.map((opt) => (
                            <option key={opt} value={opt} style={{ color: "#000" }}>
                              {opt}
                            </option>
                          ))}
                        </select>
                      ) : (
                        <input
                          value={String(value)}
                          onBlur={() => setTouched((p) => ({ ...p, [fieldKey]: true }))}
                          onChange={(e) => setLocal((p) => ({ ...p, [fieldKey]: e.target.value }))}
                          placeholder={typeof fs?.placeholder === "string" ? fs.placeholder : ""}
                          style={{
                            border: "1px solid rgba(255,255,255,0.12)",
                            background: "rgba(255,255,255,0.02)",
                            color: "rgba(255,255,255,0.92)",
                            borderRadius: 12,
                            padding: "10px 10px",
                            fontSize: 13,
                            outline: "none",
                          }}
                        />
                      )}

                      {showErr ? (
                        <div style={{ fontSize: 11, color: "rgba(245, 158, 11, 0.92)" }}>
                          {(errors as any)?.[fieldKey]}
                        </div>
                      ) : null}
                    </div>
                  );
                })}
              </div>
            </div>
          ) : null}

          <div
            style={{
              border: "1px solid rgba(255,255,255,0.08)",
              background: "rgba(255,255,255,0.02)",
              borderRadius: 14,
              padding: 12,
            }}
          >
            <div style={{ fontSize: 12, fontWeight: 650, marginBottom: 10 }}>Proposed command (opaque)</div>
            <pre
              style={{
                margin: 0,
                whiteSpace: "pre-wrap",
                wordBreak: "break-word",
                fontSize: 12,
                lineHeight: 1.55,
                color: "rgba(255,255,255,0.82)",
              }}
            >
              {clampJson(proposed)}
            </pre>
          </div>
        </div>

        {/* Footer */}
        <div
          style={{
            padding: "14px 16px",
            borderTop: "1px solid rgba(255,255,255,0.08)",
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            gap: 10,
          }}
        >
          <button
            onClick={handleDismiss}
            style={{
              border: "1px solid rgba(255,255,255,0.12)",
              background: "rgba(255,255,255,0.02)",
              color: "rgba(255,255,255,0.92)",
              borderRadius: 12,
              padding: "10px 12px",
              fontSize: 12,
              cursor: "pointer",
            }}
          >
            Dismiss
          </button>

          {mode === "approve" ? (
            <button
              onClick={handleApprove}
              disabled={!canSubmit}
              style={{
                border: "1px solid rgba(255,255,255,0.12)",
                background: "rgba(255,255,255,0.06)",
                color: "rgba(255,255,255,0.92)",
                borderRadius: 12,
                padding: "10px 12px",
                fontSize: 12,
                cursor: canSubmit ? "pointer" : "not-allowed",
                opacity: canSubmit ? 1 : 0.55,
              }}
            >
              Review &amp; Approve
            </button>
          ) : (
            <button
              onClick={handleSubmitMissing}
              disabled={!canSubmit}
              style={{
                border: "1px solid rgba(255,255,255,0.12)",
                background: "rgba(255,255,255,0.06)",
                color: "rgba(255,255,255,0.92)",
                borderRadius: 12,
                padding: "10px 12px",
                fontSize: 12,
                cursor: canSubmit ? "pointer" : "not-allowed",
                opacity: canSubmit ? 1 : 0.55,
              }}
            >
              Continue to approval
            </button>
          )}
        </div>
      </div>
    </div>
  );
};

export default CommandReviewModal;

