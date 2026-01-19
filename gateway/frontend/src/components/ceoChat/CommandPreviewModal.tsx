// gateway/frontend/src/components/ceoChat/CommandPreviewModal.tsx
import React, { useMemo, useState } from "react";

type Props = {
  open: boolean;
  title?: string;
  loading?: boolean;
  error?: string | null;
  data?: any;
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

export const CommandPreviewModal: React.FC<Props> = ({ open, title, loading, error, data, onClose }) => {
  const header = (title || "Preview") as string;

  const notion = data?.notion;
  const command = data?.command;

  const [showRaw, setShowRaw] = useState(false);

  const propertiesPreview: Record<string, any> | null =
    notion && typeof notion === "object" && notion.properties_preview && typeof notion.properties_preview === "object"
      ? (notion.properties_preview as Record<string, any>)
      : null;

  const propertySpecs: Record<string, any> | null =
    notion && typeof notion === "object" && notion.property_specs && typeof notion.property_specs === "object"
      ? (notion.property_specs as Record<string, any>)
      : null;

  const columns = useMemo(() => {
    const keys = Object.keys(propertiesPreview || propertySpecs || {});
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
  }, [propertiesPreview, propertySpecs]);

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
                        <tr>
                          {columns.map((c) => {
                            const v = (propertiesPreview || ({} as any))?.[c];
                            const display = propertiesPreview ? renderNotionValue(v) : clampJson(propertySpecs?.[c] ?? null, 2000);
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
                      </tbody>
                    </table>
                  </div>
                )}
              </div>

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
