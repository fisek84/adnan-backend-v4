// gateway/frontend/ceo_chatbox.js
(function () {
  try {
    // ------------------------------
    // CANON SAFETY: legacy chatbox MUST NOT run alongside React app
    // ------------------------------
    // Rule:
    // - Default: DO NOT mount legacy UI.
    // - Allow only if explicitly enabled via:
    //   window.__EVO_UI__.enableLegacyChatbox === true
    //
    // This prevents double UI / stale proposal bugs (A typed, B executed).
    const cfg = (window.__EVO_UI__ = window.__EVO_UI__ || {});

    const explicitlyEnabled = cfg.enableLegacyChatbox === true;

    // If React root exists, assume React app owns the page. Do not mount legacy unless explicitly enabled.
    const reactRoot = document.getElementById("root");
    const reactLikelyMounted = !!(reactRoot && reactRoot.childNodes && reactRoot.childNodes.length > 0);

    if (!explicitlyEnabled && reactRoot) {
      // Even if React isn't mounted yet, this build is React-first. Avoid legacy mount.
      console.log("[CEO_CHATBOX][legacy] skipped: React root detected; enableLegacyChatbox !== true");
      return;
    }

    // Prevent multiple mounts
    if (window.__CEO_CHATBOX_APP__) return;
    window.__CEO_CHATBOX_APP__ = true;

    const mountSelector = cfg.mountSelector || "#ceo-left-panel";

    // ------------------------------
    // CANON endpoints
    // ------------------------------
    const chatUrl = cfg.chatUrl || "/api/chat";
    const ceoStatusUrl = cfg.ceoStatusUrl || "/api/ceo-console/status";
    const executeRawUrl = cfg.executeRawUrl || "/api/execute/raw";
    const approveUrl = cfg.approveUrl || "/api/ai-ops/approval/approve";

    const headers = Object.assign({ "Content-Type": "application/json" }, cfg.headers || {});

    // --- stable session_id (persist in localStorage) ---
    const SESSION_STORAGE_KEY = cfg.sessionStorageKey || "ceo_console_session_id";

    function genSessionId() {
      try {
        if (typeof crypto !== "undefined" && crypto.randomUUID) return crypto.randomUUID();
      } catch {
        // ignore
      }
      return "sess_" + Math.random().toString(36).slice(2) + "_" + Date.now().toString(36);
    }

    function getOrCreateSessionId() {
      try {
        if (cfg.session_id && typeof cfg.session_id === "string") return cfg.session_id;

        const existing = localStorage.getItem(SESSION_STORAGE_KEY);
        if (existing && typeof existing === "string") return existing;

        const created = genSessionId();
        localStorage.setItem(SESSION_STORAGE_KEY, created);
        return created;
      } catch {
        return cfg.session_id || genSessionId();
      }
    }

    cfg.session_id = getOrCreateSessionId();
    // --- /session_id ---

    const host = document.querySelector(mountSelector);
    if (!host) {
      console.log("[CEO_CHATBOX][legacy] skipped: mount element not found", { mountSelector });
      return;
    }

    host.innerHTML = "";

    const root = document.createElement("div");
    root.className = "ceo-chatbox";

    const history = document.createElement("div");
    history.className = "ceo-chatbox-history";

    const empty = document.createElement("div");
    empty.className = "ceo-chatbox-empty";
    empty.textContent = "Legacy chatbox (debug only). Chat is read-only; execution is approval-gated.";
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
    textarea.placeholder = "Unesi poruku CEO Advisor-u… (Enter = pošalji, Shift+Enter = novi red)";

    const sendBtn = document.createElement("button");
    sendBtn.className = "ceo-chatbox-btn primary";
    sendBtn.type = "button";
    sendBtn.textContent = "Pošalji";

    const approveBtn = document.createElement("button");
    approveBtn.className = "ceo-chatbox-btn";
    approveBtn.type = "button";
    approveBtn.textContent = "Odobri";
    approveBtn.disabled = true;
    approveBtn.title = "Odobri zadnju BLOCKED komandu (approval_id).";

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
    let currentApprovalId = null;

    function isNearBottom() {
      const threshold = 120;
      return history.scrollHeight - (history.scrollTop + history.clientHeight) < threshold;
    }

    function scrollToBottom(force = false) {
      if (force || isNearBottom()) history.scrollTop = history.scrollHeight;
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
      approveBtn.disabled = next || !currentApprovalId;
    }

    function autosize() {
      textarea.style.height = "44px";
      textarea.style.height = Math.min(textarea.scrollHeight, 160) + "px";
    }

    textarea.addEventListener("input", autosize);
    textarea.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey && !e.ctrlKey && !e.altKey && !e.metaKey) {
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

    // NOTE:
    // This legacy UI is debug-only; it should not be used for canonical execution in production.
    async function executeProposal(proposal) {
      if (busy) return;
      setBusy(true);

      try {
        const payload = proposal;

        const res = await fetch(executeRawUrl, {
          method: "POST",
          headers,
          body: JSON.stringify(payload),
        });

        const raw = await readBodyAsText(res);
        if (!res.ok) {
          addMessage("sys", `Execute/raw greška: ${res.status}\n${raw || "N/A"}`, { state: "ERROR" });
          return;
        }

        const data = safeJsonParse(raw) || {};
        const approvalId = data.approval_id || (data.approval && data.approval.approval_id) || null;

        currentApprovalId = approvalId;
        approveBtn.disabled = !currentApprovalId;

        addMessage(
          "sys",
          approvalId
            ? `Komanda registrovana (BLOCKED). approval_id=${approvalId}`
            : `Komanda registrovana. (nema approval_id u response)`,
          { state: approvalId ? "BLOCKED" : "OK" }
        );
      } catch (err) {
        const msg = err instanceof Error ? err.message : String(err);
        addMessage("sys", `Execute/raw greška.\n${msg}`, { state: "ERROR" });
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
          addMessage("sys", `Approve greška: ${res.status}\n${raw || "N/A"}`, { state: "ERROR" });
          return;
        }

        const data = safeJsonParse(raw) || {};
        const state = data.execution_state || (data.approval && data.approval.status) || "APPROVED";

        addMessage("sys", `Approve OK. ${state}`, { state });

        currentApprovalId = null;
        approveBtn.disabled = true;

        const statusData = await fetchLatestStatus();
        if (statusData && statusData.ok) addMessage("sys", "Snapshot osvježen (status OK).", { state: "OK" });
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
        label.textContent = `${idx + 1}) ${cmd} | ${status}${risk ? ` | risk=${risk}` : ""}`;

        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = "ceo-chatbox-btn";
        btn.textContent = "Create execution (BLOCKED)";
        btn.addEventListener("click", () => executeProposal(p));

        row.appendChild(label);
        row.appendChild(btn);
        wrap.appendChild(row);
      });

      return wrap;
    }

    async function sendCommand() {
      const text = (textarea.value || "").trim();
      if (!text || busy) return;

      addMessage("ceo", text);
      setBusy(true);

      try {
        const statusData = await fetchLatestStatus();

        const payload = {
          message: text,
          preferred_agent_id: cfg.preferred_agent_id || "ceo_advisor",
          metadata: {
            initiator: cfg.initiator || "ceo_chat",
            source: "ceo_chatbox_legacy",
            session_id: cfg.session_id || getOrCreateSessionId(),
            context_hint: statusData || cfg.context_hint || null,
          },
        };

        const res = await fetch(chatUrl, {
          method: "POST",
          headers,
          body: JSON.stringify(payload),
        });

        const raw = await readBodyAsText(res);
        if (!res.ok) {
          addMessage("sys", `Greška (chat): ${res.status}\n${raw || "N/A"}`, { state: "ERROR" });
          return;
        }

        const data = safeJsonParse(raw) || {};

        const textOut =
          (typeof data.text === "string" && data.text.trim()) ||
          (typeof data.summary === "string" && data.summary.trim()) ||
          (typeof data.message === "string" && data.message.trim()) ||
          (raw && raw.trim()) ||
          "Nema odgovora.";

        const proposed = Array.isArray(data.proposed_commands) ? data.proposed_commands : [];

        const row = addMessage("sys", textOut, { state: "CHAT" });

        const proposalsNode = renderProposalsWithButtons(proposed);
        if (proposalsNode) {
          const msgEl = row.querySelector(".ceo-chatbox-msg");
          if (msgEl) msgEl.appendChild(proposalsNode);
        }

        textarea.value = "";
        autosize();
      } catch (err) {
        const msg = err instanceof Error ? err.message : String(err);
        addMessage("sys", `Greška pri slanju poruke.\n${msg}`, { state: "ERROR" });
      } finally {
        setBusy(false);
        textarea.focus();
      }
    }

    sendBtn.addEventListener("click", sendCommand);

    autosize();
    setTimeout(() => textarea.focus(), 60);

    console.log("[CEO_CHATBOX][legacy] mounted (debug-only)", {
      mountSelector,
      chatUrl,
      ceoStatusUrl,
      executeRawUrl,
      approveUrl,
      session_id: cfg.session_id,
      initiator: cfg.initiator || "ceo_chat",
      enableLegacyChatbox: cfg.enableLegacyChatbox === true,
      reactRootDetected: !!reactRoot,
      reactLikelyMounted,
    });
  } catch (e) {
    console.error("[CEO_CHATBOX][legacy] init failed", e);
  }
})();
