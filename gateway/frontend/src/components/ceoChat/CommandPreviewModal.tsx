// gateway/frontend/src/components/ceoChat/CommandPreviewModal.tsx
import React, { useMemo } from "react";

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

  const blocks = useMemo(() => {
    const out: Array<{ label: string; payload: any }> = [];

    if (notion && typeof notion === "object") {
      out.push({ label: "Notion property_specs (what executor receives)", payload: notion.property_specs });
      out.push({ label: "Notion properties_preview (what would be sent)", payload: notion.properties_preview });
    }

    out.push({ label: "Command (resolved / unwrapped)", payload: command ?? data?.command ?? data });
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
            blocks.map((b, i) => (
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
          )}
        </div>
      </div>
    </div>
  );
};
