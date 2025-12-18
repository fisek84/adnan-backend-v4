// gateway/frontend/script.js

(function () {
  const API_BASE = ""; // isti origin; ako imaš proxy ili drugi host, promijeni ovdje

  async function getJson(path) {
    const res = await fetch(API_BASE + path, {
      method: "GET",
      headers: { "Content-Type": "application/json" },
    });

    if (!res.ok) {
      const text = await res.text();
      throw new Error("GET " + path + " failed: " + res.status + " " + text);
    }
    return res.json();
  }

  async function postJson(path, body) {
    const res = await fetch(API_BASE + path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || {}),
    });

    if (!res.ok) {
      const text = await res.text();
      throw new Error("POST " + path + " failed: " + res.status + " " + text);
    }
    return res.json();
  }

  async function fetchCeoSnapshot() {
    return getJson("/api/ceo/console/snapshot");
  }

  async function fetchPendingApprovals() {
    return getJson("/api/ai-ops/approval/pending");
  }

  async function approveApproval(approvalId, approvedBy, note) {
    return postJson("/api/ai-ops/approval/approve", {
      approval_id: approvalId,
      approved_by: approvedBy || "ceo_dashboard",
      note: note || null,
    });
  }

  // ------------------------------------------------------------------
  // RENDER CEO APPROVALS PANEL
  // ------------------------------------------------------------------

  function renderApprovalsPanel(container, snapshot, pending, error, loading, approvingId) {
    if (!container) return;

    const sys = snapshot && snapshot.system ? snapshot.system : null;
    const approvals = snapshot && snapshot.approvals ? snapshot.approvals : null;

    let statsHtml = "";
    if (approvals) {
      statsHtml = `
        <div style="display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px;margin-bottom:12px;">
          ${statBox("Total approvals", approvals.total)}
          ${statBox("Pending", approvals.pending_count)}
          ${statBox("Approved", approvals.approved_count)}
          ${statBox("Rejected", approvals.rejected_count)}
          ${statBox("Failed", approvals.failed_count)}
        </div>
      `;
    }

    let errorHtml = "";
    if (error) {
      errorHtml = `
        <div style="margin-bottom:8px;padding:8px 10px;border-radius:6px;border:1px solid #fecaca;background:#fef2f2;color:#b91c1c;font-size:12px;">
          ${escapeHtml(error)}
        </div>
      `;
    }

    let pendingHtml = "";
    if (!pending || pending.length === 0) {
      pendingHtml = `
        <div style="padding:12px;border-radius:8px;border:1px dashed #d1d5db;font-size:13px;color:#6b7280;">
          Trenutno nema pending approvals.
        </div>
      `;
    } else {
      pendingHtml = pending
        .map(function (appr) {
          const cmd = appr.command || {};
          const meta = cmd.metadata || {};

          const createdAt = appr.created_at || meta.created_at;
          const createdLabel = createdAt
            ? new Date(createdAt).toLocaleString()
            : "n/a";

          const title =
            meta.title ||
            meta.summary ||
            cmd.intent ||
            cmd.command ||
            "AICommand";

          const isApproving = approvingId === appr.approval_id;

          return `
            <div style="display:flex;flex-direction:column;gap:8px;margin-bottom:6px;padding:8px 10px;border-radius:8px;border:1px solid #e5e7eb;background:#ffffff;">
              <div style="flex:1;min-width:0;">
                <div style="display:flex;align-items:center;gap:6px;margin-bottom:4px;">
                  <span style="
                    display:inline-flex;
                    align-items:center;
                    border-radius:999px;
                    padding:2px 8px;
                    font-size:11px;
                    font-weight:500;
                    background:#fef3c7;
                    color:#92400e;
                  ">
                    Pending
                  </span>
                  <span style="font-weight:500;font-size:13px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">
                    ${escapeHtml(String(title))}
                  </span>
                </div>
                <div style="font-size:11px;color:#6b7280;display:flex;flex-wrap:wrap;gap:8px;">
                  <span>ID: ${escapeHtml(String(appr.approval_id || ""))}</span>
                  <span>Exec: ${escapeHtml(String(appr.execution_id || ""))}</span>
                  <span>Created: ${escapeHtml(String(createdLabel))}</span>
                </div>
              </div>
              <div>
                <button
                  type="button"
                  data-approval-id="${escapeHtml(String(appr.approval_id || ""))}"
                  style="
                    padding:4px 10px;
                    font-size:12px;
                    border-radius:6px;
                    border:none;
                    cursor:pointer;
                    color:#ffffff;
                    background:${isApproving ? "#16a34a80" : "#16a34a"};
                  "
                  ${isApproving ? "disabled" : ""}
                >
                  ${isApproving ? "Odobravam..." : "Odobri"}
                </button>
              </div>
            </div>
          `;
        })
        .join("");
    }

    const headerSubtitle = sys
      ? `${escapeHtml(sys.name)} · v${escapeHtml(sys.version)} · ${escapeHtml(
          sys.release_channel
        )}`
      : "";

    container.innerHTML = `
      <div style="border-radius:12px;border:1px solid #e5e7eb;background:#f9fafb;padding:16px;box-shadow:0 1px 2px rgba(15,23,42,0.08);">
        <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:12px;">
          <div>
            <div style="font-size:18px;font-weight:600;margin-bottom:2px;">
              Approvals &amp; pipeline
            </div>
            <div style="font-size:12px;color:#6b7280;">
              ${headerSubtitle}
            </div>
          </div>
          <button
            type="button"
            id="ceo-approvals-refresh"
            style="
              padding:4px 10px;
              font-size:12px;
              border-radius:6px;
              border:1px solid #d1d5db;
              background:#ffffff;
              cursor:pointer;
              ${loading ? "opacity:0.6;" : ""}
            "
            ${loading ? "disabled" : ""}
          >
            ${loading ? "Osvježavam..." : "Osvježi"}
          </button>
        </div>

        ${errorHtml}

        ${statsHtml}

        <div style="margin-top:4px;margin-bottom:6px;font-size:13px;font-weight:600;color:#374151;">
          Pending approvals
        </div>

        <div id="ceo-approvals-list">
          ${pendingHtml}
        </div>
      </div>
    `;

    // attach event handlers for buttons
    const refreshBtn = document.getElementById("ceo-approvals-refresh");
    if (refreshBtn) {
      refreshBtn.addEventListener("click", function () {
        loadData(); // defined below
      });
    }

    const buttons = container.querySelectorAll("button[data-approval-id]");
    buttons.forEach(function (btn) {
      btn.addEventListener("click", function (ev) {
        const id = ev.currentTarget.getAttribute("data-approval-id");
        if (!id) return;
        handleApproveClick(id); // defined below
      });
    });
  }

  function statBox(label, value) {
    return `
      <div style="display:flex;flex-direction:column;border-radius:8px;border:1px solid #e5e7eb;padding:8px 10px;font-size:13px;background:#ffffff;">
        <span style="color:#6b7280;">${escapeHtml(label)}</span>
        <span style="margin-top:2px;font-size:16px;font-weight:600;">${value}</span>
      </div>
    `;
  }

  function escapeHtml(str) {
    return String(str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  // ------------------------------------------------------------------
  // PANEL CONTROLLER
  // ------------------------------------------------------------------

  let currentContainer = null;
  let currentSnapshot = null;
  let currentPending = [];
  let currentError = null;
  let currentLoading = false;
  let currentApprovingId = null;

  async function loadData() {
    if (!currentContainer) return;

    try {
      currentLoading = true;
      currentError = null;
      renderApprovalsPanel(
        currentContainer,
        currentSnapshot,
        currentPending,
        currentError,
        currentLoading,
        currentApprovingId
      );

      const [snap, pendingRes] = await Promise.all([
        fetchCeoSnapshot(),
        fetchPendingApprovals(),
      ]);

      currentSnapshot = snap;
      currentPending = (pendingRes && pendingRes.approvals) || [];
      currentLoading = false;

      renderApprovalsPanel(
        currentContainer,
        currentSnapshot,
        currentPending,
        currentError,
        currentLoading,
        currentApprovingId
      );
    } catch (e) {
      console.error(e);
      currentError = e && e.message ? e.message : "Greška pri učitavanju podataka";
      currentLoading = false;

      renderApprovalsPanel(
        currentContainer,
        currentSnapshot,
        currentPending,
        currentError,
        currentLoading,
        currentApprovingId
      );
    }
  }

  async function handleApproveClick(approvalId) {
    if (!approvalId) return;
    if (!currentContainer) return;

    const ok = window.confirm(
      "Odobri izvršenje?\n\nApproval ID: " + approvalId
    );
    if (!ok) return;

    try {
      currentApprovingId = approvalId;
      renderApprovalsPanel(
        currentContainer,
        currentSnapshot,
        currentPending,
        currentError,
        currentLoading,
        currentApprovingId
      );

      await approveApproval(approvalId, "ceo_dashboard");

      currentApprovingId = null;
      await loadData();
    } catch (e) {
      console.error(e);
      currentError = e && e.message ? e.message : "Greška pri odobravanju";
      currentApprovingId = null;

      renderApprovalsPanel(
        currentContainer,
        currentSnapshot,
        currentPending,
        currentError,
        currentLoading,
        currentApprovingId
      );
    }
  }

  // ------------------------------------------------------------------
  // INIT
  // ------------------------------------------------------------------

  document.addEventListener("DOMContentLoaded", function () {
    const container = document.getElementById("ceo-approvals-panel");
    if (!container) {
      console.warn(
        "[CEO APPROVALS] Container #ceo-approvals-panel nije pronađen u DOM-u."
      );
      return;
    }

    currentContainer = container;
    loadData();
  });
})();
  