// gateway/frontend/script.js

let lastApprovalId = null;
let lastProposalId = null;

(function () {
  // Read config from window
  const cfg = (window.CEO_CHATBOX_CONFIG || window.CEO_DASHBOARD_CONFIG || {});

  // Allow absolute base for API in production
  // Example: apiOrigin: "http://localhost:8000"
  const apiOrigin = (cfg.apiOrigin || cfg.apiBase || "").toString().trim();

  function resolveUrl(pathOrUrl) {
    if (!pathOrUrl) return pathOrUrl;
    const u = String(pathOrUrl);

    // already absolute
    if (/^https?:\/\//i.test(u)) return u;

    // if apiOrigin provided, prefix it
    if (apiOrigin) return apiOrigin.replace(/\/$/, "") + u;

    // fallback: relative (works only if same-origin or dev proxy)
    return u;
  }

  // Legacy endpoints (NOT CANON for Jan 2026 flow)
  const ceoCommandUrl = resolveUrl(cfg.ceoCommandUrl || "/api/ceo-console/command");
  const approveUrl = resolveUrl(cfg.approveUrl || "/api/ai-ops/approval/approve");
  const proposalsExecuteUrl = resolveUrl(cfg.proposalsExecuteUrl || "/api/proposals/execute");

  function getAuthToken() {
    // Priority:
    //  1) localStorage "CEO_APPROVAL_TOKEN"
    //  2) cfg.token
    //  3) empty
    return (
      (typeof localStorage !== "undefined" && localStorage.getItem("CEO_APPROVAL_TOKEN")) ||
      cfg.token ||
      ""
    );
  }

  function buildHeaders() {
    const headers = { "Content-Type": "application/json" };
    const token = getAuthToken();
    if (token) headers["Authorization"] = `Bearer ${token}`;
    return headers;
  }

  async function safeJson(resp) {
    const txt = await resp.text();
    try {
      return JSON.parse(txt);
    } catch {
      return { ok: false, parse_error: true, raw: txt, status: resp.status };
    }
  }

  async function postJson(url, body) {
    const resp = await fetch(url, {
      method: "POST",
      headers: buildHeaders(),
      body: JSON.stringify(body || {}),
      // If you use cookies/session auth, uncomment:
      // credentials: "include",
      mode: "cors",
    });
    const data = await safeJson(resp);
    return { status: resp.status, data };
  }

  // Expose API for any legacy UI code that still references it.
  // CANON SAFETY:
  // - No implicit reuse of lastApprovalId/lastProposalId
  // - Disallow non-canonical proposal execute endpoint
  window.CEO_CHATBOX_API = {
    async sendCommand(payload) {
      const { status, data } = await postJson(ceoCommandUrl, payload);

      // Capture IDs for debugging only (NOT as implicit fallbacks)
      if (data && data.context && data.context.last_approval_id) lastApprovalId = data.context.last_approval_id;
      if (data && data.last_approval_id) lastApprovalId = data.last_approval_id;
      if (data && data.last_proposal_id) lastProposalId = data.last_proposal_id;

      return { status, data };
    },

    async approve(approval_id) {
      // CANON: approval must be explicit; never fallback to stale lastApprovalId
      if (!approval_id) {
        return {
          status: 400,
          data: {
            ok: false,
            error:
              "Missing approval_id (canon requires explicit approval_id; implicit lastApprovalId fallback is disabled).",
            debug_lastApprovalId: lastApprovalId,
          },
        };
      }
      return postJson(approveUrl, { approval_id });
    },

    async executeProposal(_proposal_id) {
      // NOT CANON: proposalsExecuteUrl is not part of CEO_CONSOLE_EXECUTION_FLOW.md
      return {
        status: 410,
        data: {
          ok: false,
          error:
            "Endpoint /api/proposals/execute is disabled (not canonical). Use /api/execute/raw with a selected proposal, then /api/ai-ops/approval/approve.",
          debug_lastProposalId: lastProposalId,
          proposalsExecuteUrl,
        },
      };
    },

    _debug: {
      ceoCommandUrl,
      approveUrl,
      proposalsExecuteUrl,
      apiOrigin,
      lastApprovalId: () => lastApprovalId,
      lastProposalId: () => lastProposalId,
    },
  };
})();
