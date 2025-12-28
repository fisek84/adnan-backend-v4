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

  // Expose API for UI code that already exists in this file
  window.CEO_CHATBOX_API = {
    async sendCommand(payload) {
      const { status, data } = await postJson(ceoCommandUrl, payload);
      // Capture approval/proposal IDs if present
      if (data && data.context && data.context.last_approval_id) lastApprovalId = data.context.last_approval_id;
      if (data && data.last_approval_id) lastApprovalId = data.last_approval_id;
      if (data && data.last_proposal_id) lastProposalId = data.last_proposal_id;
      return { status, data };
    },

    async approve(approval_id) {
      const id = approval_id || lastApprovalId;
      if (!id) return { status: 400, data: { ok: false, error: "Missing approval_id" } };
      return postJson(approveUrl, { approval_id: id });
    },

    async executeProposal(proposal_id) {
      const id = proposal_id || lastProposalId;
      if (!id) return { status: 400, data: { ok: false, error: "Missing proposal_id" } };
      return postJson(proposalsExecuteUrl, { proposal_id: id });
    },

    _debug: {
      ceoCommandUrl,
      approveUrl,
      proposalsExecuteUrl,
      apiOrigin,
    },
  };
})();
