// gateway/frontend/ceo_chatbox.js
(function () {
  try {
    if (window.__CEO_CHATBOX_APP__) return;
    window.__CEO_CHATBOX_APP__ = true;

    const cfg = (window.__EVO_UI__ = window.__EVO_UI__ || {});
    const mountSelector = cfg.mountSelector || "#ceo-left-panel";

    // CEO Console endpoints
    const ceoCommandUrl = cfg.ceoCommandUrl || "/api/ceo-console/command";
    const ceoStatusUrl = cfg.ceoStatusUrl || "/api/ceo-console/status";

    // CANON governance endpoints (enabled)
    const executeRawUrl = cfg.executeRawUrl || "/api/execute/raw";
    const approveUrl = cfg.approveUrl || "/api/ai-ops/approval/approve";

    const headers = Object.assign(
      { "Content-Type": "application/json" },
      cfg.headers || {}
    );

    const host = document.querySelector(mountSelector);
    if (!host) return;

    // legacy ostaje, ali je već skriven u index.html (#ceo-chat-legacy display:none)
    host.innerHTML = "";

    const root = document.createElement("div");
    root.className = "ceo-chatbox";

    const history = document.createElement("div");
    history.className = "ceo-chatbox-history";

    const empty = document.createElement("div");
    empty.className = "ceo-chatbox-empty";
    empty.textContent =
      "Napiši CEO komandu ispod. History je scroll, input je fiksno na dnu.";
    history.appendChild(empty);

    const scrollBtn = document.createElement("button");
    scrollBtn.className = "ceo-chatbox-scrollbtn";
    scrollBtn.type = "button";
    scrollBtn.textContent = "↓ Na dno";

    const typing = document.createElement("div");
    typing.className = "ceo-chatbox-typing";
    typing.style.display = "none";
    typing.textContent = "SYSTEM obrađuje zahtjev…";

    const composer = document.createElement("div");
    composer.className = "ceo-chatbox-composer";

    const textarea = document.createElement("textarea");
    textarea.className = "ceo-chatbox-textarea";
    textarea.placeholder =
      "Unesi CEO COMMAND… (Enter = pošalji, Shift+Enter = novi red)";

    const sendBtn = document.createElement("button");
    sendBtn.className = "ceo-chatbox-btn primary";
    sendBtn.type = "button";
    sendBtn.textContent = "Pošalji";

    // Approve button ENABLED (disabled only when there is no approval_id or when busy)
    const approveBtn = document.createElement("button");
    approveBtn.className = "ceo-chatbox-btn";
    approveBtn.type = "button";
    approveBtn.textContent = "Odobri";
    approveBtn.disabled = true;
    approveBtn.title = "Odobri zadnju izvršenu komandu (approval_id).";

    composer.appendChild(textarea);
    composer.appendChild(sendBtn);
    composer.appendChild(approveBtn);

    root.appendChild(history);
    root.appendChild(scrollBtn);
    root.appendChild(typing);
    root.appendChild(composer);
    host.appendChild(root);

    let busy = false;
    let lastRole = null;

    // governance state
    let currentApprovalId = null;

    function isNearBottom() {
      const threshold = 120;
      return (
        history.scrollHeight - (history.scrollTop + history.clientHeight) <
        threshold
      );
    }

    function scrollToBottom(force = false) {
      if (force || isNearBottom()) {
        history.scrollTop = history.scrollHeight;
      }
    }

    function updateScrollBtn() {
      scrollBtn.style.display = isNearBottom() ? "none" : "inline-flex";
    }

    history.addEventListener("scroll", updateScrollBtn);
    scrollBtn.addEventListener("click", () => scrollToBottom(true));

    function addMessage(role, text, meta) {
      if (empty && empty.parentNode) empty.parentNode.removeChild(empty);

      const row = document.createElement("div");
      row.className = "ceo-chatbox-row";

      const grouped = lastRole === role;
      if (grouped) row.classList.add("grouped");

      const badge = document.createElement("div");
      badge.className = "ceo-chatbox-badge";
      badge.textContent = role === "ceo" ? "CEO" : "SYS";
      if (grouped) badge.style.visibility = "hidden";

      const msg = document.createElement("div");
      msg.className = "ceo-chatbox-msg " + (role === "ceo" ? "ceo" : "sys");
      msg.textContent = text;

      row.appendChild(badge);
      row.appendChild(msg);

      if (meta && (meta.state || meta.extra_html)) {
        const metaRow = document.createElement("div");
        metaRow.className = "ceo-chatbox-meta";

        if (meta.state) {
          const pill = document.createElement("span");
          pill.className = "ceo-chatbox-pill";
          pill.innerHTML = `<strong>Status:</strong> ${meta.state}`;
          metaRow.appendChild(pill);
        }
        if (meta.extra_html) {
          const pill = document.createElement("span");
          pill.className = "ceo-chatbox-pill";
          pill.innerHTML = meta.extra_html;
          metaRow.appendChild(pill);
        }

        msg.appendChild(metaRow);
      }

      const stayAtBottom = isNearBottom();
      history.appendChild(row);
      lastRole = role;

      scrollToBottom(stayAtBottom);
      updateScrollBtn();

      return row;
    }

    function setBusy(next) {
      busy = next;
      sendBtn.disabled = next;
      textarea.disabled = next;
      typing.style.display = next ? "block" : "none";

      // approve enabled only if we have approval_id and not busy
      approveBtn.disabled = next || !currentApprovalId;
    }

    function autosize() {
      textarea.style.height = "44px";
      textarea.style.height = Math.min(textarea.scrollHeight, 160) + "px";
    }

    textarea.addEventListener("input", autosize);

    textarea.addEventListener("keydown", (e) => {
      if (
        e.key === "Enter" &&
        !e.shiftKey &&
        !e.ctrlKey &&
        !e.altKey &&
        !e.metaKey
      ) {
        e.preventDefault();
        sendBtn.click();
      }
    });

    async function readBodyAsText(res) {
      try {
        return await res.text();
      } catch {
        return "";
      }
    }

    function safeJsonParse(text) {
      try {
        return JSON.parse(text);
      } catch {
        return null;
      }
    }

    // NEW: fetch latest status snapshot from server (used as context_hint)
    async function fetchLatestStatus() {
      try {
        const res = await fetch(ceoStatusUrl, { method: "GET", headers });
        if (!res.ok) return null;
        const t = await readBodyAsText(res);
        return safeJsonParse(t) || null;
      } catch {
        return null;
      }
    }

    // More robust dashboard extraction (backend shapes vary)
    function extractDashboard(data) {
      if (!data || typeof data !== "object") return null;

      // Original expected path
      let dash =
        data?.context?.snapshot?.ceo_dashboard_snapshot?.dashboard || null;

      // Common alternates
      dash =
        dash ||
        data?.snapshot?.ceo_dashboard_snapshot?.dashboard ||
        data?.context?.ceo_dashboard_snapshot?.dashboard ||
        data?.ceo_dashboard_snapshot?.dashboard ||
        data?.dashboard ||
        null;

      // Sometimes status endpoint returns directly { dashboard: {...} } or { data: { dashboard: ... } }
      dash = dash || data?.data?.dashboard || null;

      return dash || null;
    }

    function formatDashboard(dash) {
      if (!dash) return "";
      const goals = Array.isArray(dash.goals) ? dash.goals : [];
      const tasks = Array.isArray(dash.tasks) ? dash.tasks : [];

      const gTop = goals
        .slice(0, 3)
        .map((g, i) => `${i + 1}) ${g.name || g.title || "?"} [${g.status || "?"}]`)
        .join("\n");

      const tTop = tasks
        .slice(0, 5)
        .map((t, i) => `${i + 1}) ${t.title || t.name || "?"} [${t.status || "?"}]`)
        .join("\n");

      return `\n\nGOALS (top 3)\n${gTop || "-"}\n\nTASKS (top 5)\n${tTop || "-"}`;
    }

    function pickExecutePayload(p) {
      // Prefer shapes that match your backend responses (payload_summary from approvals)
      if (p && p.payload_summary && typeof p.payload_summary === "object")
        return p.payload_summary;
      if (p && p.payload && typeof p.payload === "object") return p.payload;
      if (p && p.raw_payload && typeof p.raw_payload === "object")
        return p.raw_payload;

      const cmd = (p && (p.command_type || p.command)) || "unknown_command";
      return { command: cmd, intent: cmd, params: (p && p.params) || {} };
    }

    async function executeProposal(p) {
      if (busy) return;
      setBusy(true);

      try {
        const payload = pickExecutePayload(p);

        const res = await fetch(executeRawUrl, {
          method: "POST",
          headers,
          body: JSON.stringify(payload),
        });

        const raw = await readBodyAsText(res);
        if (!res.ok) {
          addMessage("sys", `Execute greška: ${res.status}\n${raw || "N/A"}`, {
            state: "ERROR",
          });
          return;
        }

        const data = safeJsonParse(raw) || {};
        const approvalId =
          data.approval_id ||
          (data.approval && data.approval.approval_id) ||
          null;

        currentApprovalId = approvalId;
        approveBtn.disabled = !currentApprovalId;

        addMessage(
          "sys",
          approvalId
            ? `Komanda poslana. BLOCKED (approval_id=${approvalId})`
            : `Komanda poslana. (nema approval_id u response)`,
          { state: approvalId ? "BLOCKED" : "OK" }
        );
      } catch (err) {
        const msg = err instanceof Error ? err.message : String(err);
        addMessage("sys", `Execute greška.\n${msg}`, { state: "ERROR" });
      } finally {
        setBusy(false);
      }
    }

    async function approveCurrent() {
      if (!currentApprovalId || busy) return;
      setBusy(true);

      try {
        const res = await fetch(approveUrl, {
          method: "POST",
          headers,
          body: JSON.stringify({ approval_id: currentApprovalId }),
        });

        const raw = await readBodyAsText(res);
        if (!res.ok) {
          addMessage("sys", `Approve greška: ${res.status}\n${raw || "N/A"}`, {
            state: "ERROR",
          });
          return;
        }

        const data = safeJsonParse(raw) || {};
        const state =
          data.execution_state ||
          (data.approval && data.approval.status) ||
          "APPROVED";

        addMessage("sys", `Approve OK. ${state}`, { state });

        // Clear approval_id after approval
        currentApprovalId = null;
        approveBtn.disabled = true;

        // NEW: immediately load status and show short confirmation
        const statusData = await fetchLatestStatus();
        if (statusData && statusData.ok) {
          const dash = extractDashboard(statusData);
          const dashText = dash ? formatDashboard(dash) : "";
          if (dashText) {
            addMessage("sys", `Snapshot osvježen.${dashText}`, { state: "OK" });
          } else {
            addMessage("sys", "Snapshot osvježen (status OK).", { state: "OK" });
          }
        }
      } catch (err) {
        const msg = err instanceof Error ? err.message : String(err);
        addMessage("sys", `Approve greška.\n${msg}`, { state: "ERROR" });
      } finally {
        setBusy(false);
      }
    }

    approveBtn.addEventListener("click", approveCurrent);

    function renderProposalsWithButtons(proposed) {
      if (!Array.isArray(proposed) || proposed.length === 0) return null;

      const wrap = document.createElement("div");
      wrap.className = "ceo-chatbox-proposals";

      proposed.forEach((p, idx) => {
        const cmd = (p && (p.command_type || p.command)) || "unknown_command";
        const status = (p && p.status) || "BLOCKED";
        const risk = (p && (p.risk_hint || p.risk)) || "";

        const row = document.createElement("div");
        row.style.display = "flex";
        row.style.gap = "8px";
        row.style.alignItems = "center";
        row.style.marginTop = "6px";

        const label = document.createElement("div");
        label.style.whiteSpace = "pre-wrap";
        label.textContent = `${idx + 1}) ${cmd} | ${status}${
          risk ? ` | risk=${risk}` : ""
        }`;

        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = "ceo-chatbox-btn";
        btn.textContent = "Execute (raw)";
        btn.addEventListener("click", () => executeProposal(p));

        row.appendChild(label);
        row.appendChild(btn);
        wrap.appendChild(row);
      });

      return wrap;
    }

    async function pingStatus() {
      try {
        const res = await fetch(ceoStatusUrl, { method: "GET", headers });
        if (!res.ok) return;
        const t = await readBodyAsText(res);
        const j = safeJsonParse(t);
        if (j && j.ok) {
          // optional: show status once
          // addMessage("sys", "CEO Console: online", { state: "OK" });
        }
      } catch {
        // ignore
      }
    }

    async function sendCommand() {
      const text = (textarea.value || "").trim();
      if (!text || busy) return;

      addMessage("ceo", text);
      setBusy(true);

      try {
        // NEW: always fetch latest status/snapshot and pass it to backend as context_hint
        const statusData = await fetchLatestStatus();

        const payload = {
          text,
          initiator: cfg.initiator || "ceo_dashboard",

          // session_id optional
          session_id: cfg.session_id || undefined,

          // NEW: Provide server status/snapshot as context hint, fallback to cfg.context_hint if provided
          context_hint: statusData || cfg.context_hint || undefined,

          // NEW (harmless if backend ignores): explicit scope hint
          snapshot_scope: cfg.snapshot_scope || "ceo_dashboard",
        };

        const res = await fetch(ceoCommandUrl, {
          method: "POST",
          headers,
          body: JSON.stringify(payload),
        });

        const raw = await readBodyAsText(res);
        if (!res.ok) {
          addMessage("sys", `Greška: ${res.status}\n${raw || "N/A"}`, {
            state: "ERROR",
          });
          return;
        }

        const data = safeJsonParse(raw) || {};

        // If snapshot exists, show it and ignore misleading summary/text
        const dash = extractDashboard(data) || extractDashboard(statusData);
        const dashText = dash ? formatDashboard(dash) : "";

        const summary =
          dashText ||
          (typeof data.summary === "string" && data.summary.trim()) ||
          (typeof data.text === "string" && data.text.trim()) ||
          (raw && raw.trim()) ||
          "Nema odgovora.";

        // Proposed commands from backend
        const proposed = Array.isArray(data.proposed_commands)
          ? data.proposed_commands
          : [];

        const row = addMessage("sys", summary, { state: "OK" });

        const proposalsNode = renderProposalsWithButtons(proposed);
        if (proposalsNode) {
          const msgEl = row.querySelector(".ceo-chatbox-msg");
          if (msgEl) msgEl.appendChild(proposalsNode);
        }

        textarea.value = "";
        autosize();
      } catch (err) {
        const msg = err instanceof Error ? err.message : String(err);
        addMessage("sys", `Greška pri slanju naredbe.\n${msg}`, {
          state: "ERROR",
        });
      } finally {
        setBusy(false);
        textarea.focus();
      }
    }

    sendBtn.addEventListener("click", sendCommand);

    // start
    autosize();
    setTimeout(() => textarea.focus(), 60);
    setTimeout(pingStatus, 50);

    console.log("[CEO_CHATBOX] mounted", {
      mountSelector,
      ceoCommandUrl,
      ceoStatusUrl,
      executeRawUrl,
      approveUrl,
    });
  } catch (e) {
    console.error("[CEO_CHATBOX] init failed", e);
  }
})();
