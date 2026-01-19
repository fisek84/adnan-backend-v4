// gateway/frontend/src/components/ceoChat/CommandPreviewModal.tsx
import React, { useEffect, useMemo, useState } from "react";

type Props = {
  open: boolean;
  title?: string;
  loading?: boolean;
  error?: string | null;
  data?: any;
  onApplyPatch?: (patch: Record<string, any>) => void;
  onClose: () => void;
};

function clampJson(obj: any, maxLen = 16000): string {
  let s = "";
  try {
    s = JSON.stringify(obj ?? {}, null, 2);
  } catch {
    s = String(obj ?? "");
  }
  if (s.length <= maxLen) return s;
  return s.slice(0, maxLen) + "\n...(truncated)...";
}

export const CommandPreviewModal: React.FC<Props> = ({ open, title, loading, error, data, onApplyPatch, onClose }) => {
  const header = (title || "Preview") as string;

  const notion = data?.notion;
  const command = data?.command;
  const notionRows: any[] | null = Array.isArray((notion as any)?.rows) ? ((notion as any).rows as any[]) : null;

  const [showRaw, setShowRaw] = useState(false);
  const [showAllFields, setShowAllFields] = useState(false);
  const [patchLocal, setPatchLocal] = useState<Record<string, string>>({});

  useEffect(() => {
    if (!open) return;
    setPatchLocal({});
    setShowAllFields(false);
  }, [open, data]);

  const propertiesPreview: Record<string, any> | null =
    notion && typeof notion === "object" && notion.properties_preview && typeof notion.properties_preview === "object"
      ? (notion.properties_preview as Record<string, any>)
      : null;

  const propertySpecs: Record<string, any> | null =
    notion && typeof notion === "object" && notion.property_specs && typeof notion.property_specs === "object"
      ? (notion.property_specs as Record<string, any>)
      : null;

  const review = data?.review && typeof data.review === "object" ? data.review : null;
  const reviewSchema: Record<string, any> | null =
    review?.fields_schema && typeof review.fields_schema === "object" ? (review.fields_schema as Record<string, any>) : null;
  const reviewMissing: string[] = Array.isArray(review?.missing_fields)
    ? (review.missing_fields as any[]).filter((x) => typeof x === "string")
    : [];

  // Only support patching fields that backend can currently apply reliably.
  const supportedPatchFields = ["Status", "Priority", "Deadline", "Due Date", "Description"];

  const editableFields = useMemo(() => {
    const schemaKeys = Object.keys(reviewSchema || {}).filter((k) => supportedPatchFields.includes(k));
    if (!schemaKeys.length) return [];

    const preferred = supportedPatchFields.filter((k) => schemaKeys.includes(k));
    const base = reviewMissing.filter((k) => schemaKeys.includes(k));
    const picked = base.length ? base : preferred;
    return showAllFields ? schemaKeys : picked.length ? picked : schemaKeys;
  }, [reviewSchema, reviewMissing, showAllFields]);

  function fieldOptions(fieldKey: string): string[] {
    const fs: any = (reviewSchema as any)?.[fieldKey] ?? {};
    const opts = Array.isArray(fs?.options) ? fs.options.filter((x: any) => typeof x === "string") : [];
    return opts;
  }

  function currentValueForField(fieldKey: string): string {
    if (typeof patchLocal?.[fieldKey] === "string") return patchLocal[fieldKey];
    if (propertiesPreview) {
      const pv = propertiesPreview[fieldKey];
      if (pv?.select?.name) return String(pv.select.name);
      if (pv?.status?.name) return String(pv.status.name);
      if (pv?.date?.start) return String(pv.date.start);
      if (Array.isArray(pv?.rich_text)) return renderNotionValue(pv);
    }
    if (propertySpecs) {
      const sp = propertySpecs[fieldKey];
      if (sp?.name) return String(sp.name);
      if (sp?.start) return String(sp.start);
      if (sp?.text) return String(sp.text);
    }
    return "";
  }

  const columns = useMemo(() => {
    // Batch preview columns: union of per-row columns.
    if (notionRows && notionRows.length > 0) {
      const colSet = new Set<string>();
      colSet.add("op_id");
      colSet.add("intent");
      colSet.add("db_key");

      for (const r of notionRows) {
        const pp = r?.properties_preview && typeof r.properties_preview === "object" ? r.properties_preview : null;
        const ps = r?.property_specs && typeof r.property_specs === "object" ? r.property_specs : null;
        const src = pp || ps || {};
        for (const k of Object.keys(src)) colSet.add(k);
      }

      const keys = Array.from(colSet);
      const preferred = [
        "op_id",
        "intent",
        "db_key",
        "Goal Ref",
        "Project Ref",
        "Parent Goal Ref",
        "Name",
        "Title",
        "Status",
        "Priority",
        "Owner",
        "Deadline",
        "Due Date",
        "Project",
        "Goal",
        "Description",
      ];
      const ordered: string[] = [];
      for (const p of preferred) if (keys.includes(p)) ordered.push(p);
      for (const k of keys) if (!ordered.includes(k)) ordered.push(k);
      return ordered;
    }

    const keys = Object.keys(propertiesPreview || propertySpecs || reviewSchema || {});
    // Prefer a Notion-ish order
    const preferred = [
      "Name",
      "Title",
      "Status",
      "Priority",
      "Owner",
      "Deadline",
      "Due Date",
      "Project",
      "Goal",
      "Description",
    ];
    const ordered: string[] = [];
    for (const p of preferred) if (keys.includes(p)) ordered.push(p);
    for (const k of keys) if (!ordered.includes(k)) ordered.push(k);
    return ordered;
  }, [propertiesPreview, propertySpecs, reviewSchema, notionRows]);

  function renderNotionValue(v: any): string {
    if (!v || typeof v !== "object") return "";

    if (Array.isArray(v.title)) {
      const parts = v.title
        .map((t: any) => t?.plain_text || t?.text?.content || "")
        .filter((x: any) => typeof x === "string" && x.trim());
      return parts.join("");
    }

    if (Array.isArray(v.rich_text)) {
      const parts = v.rich_text
        .map((t: any) => t?.plain_text || t?.text?.content || "")
        .filter((x: any) => typeof x === "string" && x.trim());
      return parts.join("");
    }

    if (v.select && typeof v.select === "object") {
      const n = v.select.name;
      return typeof n === "string" ? n : "";
    }

    if (v.status && typeof v.status === "object") {
      const n = v.status.name;
      return typeof n === "string" ? n : "";
    }

    if (v.date && typeof v.date === "object") {
      const s = v.date.start;
      return typeof s === "string" ? s : "";
    }

    if (Array.isArray(v.relation)) {
      return `${v.relation.length} relation(s)`;
    }

    // fallback
    return clampJson(v, 2000);
  }

  const rawBlocks = useMemo(() => {
    const out: Array<{ label: string; payload: any }> = [];
    out.push({ label: "Command (resolved / unwrapped)", payload: command ?? data?.command ?? data });
    if (notion && typeof notion === "object") {
      out.push({ label: "Notion property_specs", payload: notion.property_specs });
      out.push({ label: "Notion properties_preview", payload: notion.properties_preview });
    }
    return out;
  }, [data, notion, command]);

  if (!open) return null;

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={header}
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
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
          width: "min(860px, 96vw)",
          maxHeight: "92vh",
          borderRadius: 18,
          border: "1px solid rgba(255,255,255,0.10)",
          background: "rgba(15, 23, 32, 0.98)",
          backdropFilter: "blur(14px)",
          boxShadow: "0 18px 60px rgba(0,0,0,0.55)",
          overflow: "hidden",
          color: "rgba(255,255,255,0.92)",
          fontFamily:
            'ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial, "Apple Color Emoji","Segoe UI Emoji"',
        }}
      >
        <div
          style={{
            padding: "14px 16px",
            borderBottom: "1px solid rgba(255,255,255,0.08)",
            display: "flex",
            alignItems: "center",
            gap: 12,
          }}
        >
          <div style={{ fontWeight: 700, fontSize: 14 }}>{header}</div>
          <div style={{ marginLeft: "auto", display: "flex", gap: 8 }}>
            <button
              onClick={() => setShowRaw((v) => !v)}
              style={{
                padding: "8px 10px",
                borderRadius: 10,
                border: "1px solid rgba(255,255,255,0.12)",
                background: "rgba(255,255,255,0.06)",
                color: "rgba(255,255,255,0.92)",
                cursor: "pointer",
              }}
              title="Toggle raw JSON view"
              disabled={loading}
            >
              {showRaw ? "Hide JSON" : "Show JSON"}
            </button>
            <button
              onClick={() => {
                try {
                  void navigator.clipboard.writeText(clampJson(data));
                } catch {
                  // ignore
                }
              }}
              style={{
                padding: "8px 10px",
                borderRadius: 10,
                border: "1px solid rgba(255,255,255,0.12)",
                background: "rgba(255,255,255,0.06)",
                color: "rgba(255,255,255,0.92)",
                cursor: "pointer",
              }}
              title="Copy full preview JSON"
              disabled={loading}
            >
              Copy JSON
            </button>
            <button
              onClick={onClose}
              style={{
                padding: "8px 10px",
                borderRadius: 10,
                border: "1px solid rgba(255,255,255,0.12)",
                background: "rgba(255,255,255,0.06)",
                color: "rgba(255,255,255,0.92)",
                cursor: "pointer",
              }}
            >
              Close
            </button>
          </div>
        </div>

        <div style={{ padding: 16, overflow: "auto", maxHeight: "calc(92vh - 58px)" }}>
          {loading ? (
            <div style={{ opacity: 0.85 }}>Loading preview…</div>
          ) : error ? (
            <div style={{ color: "#ffb3b3" }}>{error}</div>
          ) : (
            <>
              <div style={{ marginBottom: 12 }}>
                <div style={{ fontWeight: 700, fontSize: 13, marginBottom: 8 }}>Notion table preview</div>

                {columns.length === 0 ? (
                  <div style={{ opacity: 0.85 }}>
                    No Notion properties detected in preview.
                  </div>
                ) : (
                  <div
                    style={{
                      borderRadius: 14,
                      border: "1px solid rgba(255,255,255,0.08)",
                      background: "rgba(255,255,255,0.04)",
                      overflow: "auto",
                    }}
                  >
                    <table
                      style={{
                        width: "100%",
                        borderCollapse: "separate",
                        borderSpacing: 0,
                        minWidth: 760,
                        fontSize: 12,
                      }}
                    >
                      <thead>
                        <tr>
                          {columns.map((c) => (
                            <th
                              key={c}
                              style={{
                                textAlign: "left",
                                padding: "10px 12px",
                                position: "sticky",
                                top: 0,
                                background: "rgba(15, 23, 32, 0.98)",
                                borderBottom: "1px solid rgba(255,255,255,0.10)",
                                fontWeight: 700,
                                color: "rgba(255,255,255,0.88)",
                                whiteSpace: "nowrap",
                              }}
                            >
                              {c}
                            </th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {notionRows && notionRows.length > 0 ? (
                          notionRows.map((r, ridx) => (
                            <tr key={r?.op_id || ridx}>
                              {columns.map((c) => {
                                const isMeta = c === "op_id" || c === "intent" || c === "db_key";
                                const pp = r?.properties_preview && typeof r.properties_preview === "object" ? r.properties_preview : null;
                                const ps = r?.property_specs && typeof r.property_specs === "object" ? r.property_specs : null;

                                const v = pp ? pp?.[c] : null;
                                const display = isMeta
                                  ? String(r?.[c] ?? "")
                                  : pp
                                    ? renderNotionValue(v)
                                    : ps
                                      ? clampJson(ps?.[c] ?? null, 2000)
                                      : "";

                                return (
                                  <td
                                    key={`${ridx}_${c}`}
                                    style={{
                                      padding: "10px 12px",
                                      borderBottom: "1px solid rgba(255,255,255,0.06)",
                                      color: "rgba(255,255,255,0.90)",
                                      verticalAlign: "top",
                                      maxWidth: 320,
                                      whiteSpace: "pre-wrap",
                                      wordBreak: "break-word",
                                    }}
                                  >
                                    {display || "—"}
                                  </td>
                                );
                              })}
                            </tr>
                          ))
                        ) : (
                          <tr>
                            {columns.map((c) => {
                              const v = (propertiesPreview || ({} as any))?.[c];
                              const display = propertiesPreview
                                ? renderNotionValue(v)
                                : propertySpecs
                                  ? clampJson(propertySpecs?.[c] ?? null, 2000)
                                  : currentValueForField(c);
                              return (
                                <td
                                  key={c}
                                  style={{
                                    padding: "10px 12px",
                                    borderBottom: "1px solid rgba(255,255,255,0.06)",
                                    color: "rgba(255,255,255,0.90)",
                                    verticalAlign: "top",
                                    maxWidth: 320,
                                    whiteSpace: "pre-wrap",
                                    wordBreak: "break-word",
                                  }}
                                >
                                  {display || "—"}
                                </td>
                              );
                            })}
                          </tr>
                        )}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>

              {reviewSchema && editableFields.length > 0 ? (
                <div
                  style={{
                    marginBottom: 14,
                    borderRadius: 14,
                    border: "1px solid rgba(255,255,255,0.08)",
                    background: "rgba(255,255,255,0.03)",
                    padding: 12,
                  }}
                >
                  <div style={{ display: "flex", alignItems: "center", gap: 10, justifyContent: "space-between" }}>
                    <div>
                      <div style={{ fontWeight: 700, fontSize: 13 }}>Complete fields</div>
                      <div style={{ fontSize: 12, opacity: 0.75 }}>
                        These values will be applied to the proposal before approval.
                      </div>
                    </div>
                    <button
                      onClick={() => setShowAllFields((p) => !p)}
                      style={{
                        padding: "8px 10px",
                        borderRadius: 10,
                        border: "1px solid rgba(255,255,255,0.12)",
                        background: "rgba(255,255,255,0.06)",
                        color: "rgba(255,255,255,0.92)",
                        cursor: "pointer",
                      }}
                      title="Show more fields"
                      disabled={loading}
                    >
                      {showAllFields ? "Hide extra" : "Show all"}
                    </button>
                  </div>

                  <div style={{ height: 10 }} />

                  <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
                    {editableFields.map((fieldKey) => {
                      const opts = fieldOptions(fieldKey);
                      const val = currentValueForField(fieldKey);
                      const missing = reviewMissing.includes(fieldKey);

                      return (
                        <div key={fieldKey} style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                          <div style={{ fontSize: 12, color: "rgba(255,255,255,0.78)" }}>
                            {fieldKey} {missing ? <span style={{ opacity: 0.7 }}>*</span> : null}
                          </div>
                          {opts.length > 0 ? (
                            <select
                              value={val}
                              onChange={(e) => setPatchLocal((p) => ({ ...p, [fieldKey]: e.target.value }))}
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
                              {opts.map((o) => (
                                <option key={o} value={o} style={{ color: "#000" }}>
                                  {o}
                                </option>
                              ))}
                            </select>
                          ) : (
                            <input
                              value={val}
                              onChange={(e) => setPatchLocal((p) => ({ ...p, [fieldKey]: e.target.value }))}
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
                        </div>
                      );
                    })}
                  </div>

                  <div style={{ height: 12 }} />
                  <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
                    <button
                      onClick={() => {
                        const out: Record<string, any> = {};
                        for (const k of supportedPatchFields) {
                          const v = patchLocal?.[k];
                          if (typeof v === "string" && v.trim()) out[k] = v.trim();
                        }
                        if (Object.keys(out).length === 0) return;
                        if (!onApplyPatch) return;
                        onApplyPatch(out);
                      }}
                      style={{
                        padding: "8px 10px",
                        borderRadius: 10,
                        border: "1px solid rgba(255,255,255,0.12)",
                        background: "rgba(59,130,246,0.20)",
                        color: "rgba(255,255,255,0.92)",
                        cursor: "pointer",
                      }}
                      title="Apply these values to proposal and refresh preview"
                      disabled={loading || !onApplyPatch}
                    >
                      Update preview
                    </button>
                  </div>
                </div>
              ) : null}

              {showRaw
                ? rawBlocks.map((b, i) => (
                    <div key={i} style={{ marginBottom: 14 }}>
                      <div style={{ fontWeight: 700, fontSize: 13, marginBottom: 6 }}>{b.label}</div>
                      <pre
                        style={{
                          margin: 0,
                          padding: 12,
                          borderRadius: 14,
                          border: "1px solid rgba(255,255,255,0.08)",
                          background: "rgba(255,255,255,0.04)",
                          overflow: "auto",
                          fontSize: 12,
                          lineHeight: 1.35,
                          whiteSpace: "pre-wrap",
                          wordBreak: "break-word",
                          color: "rgba(255,255,255,0.90)",
                        }}
                      >
                        {clampJson(b.payload)}
                      </pre>
                    </div>
                  ))
                : null}
            </>
          )}
        </div>
      </div>
    </div>
  );
};
