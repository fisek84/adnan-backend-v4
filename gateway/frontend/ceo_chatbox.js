// gateway/frontend/ceo_chatbox.js
(function () {
  try {
    if (window.__CEO_CHATBOX_APP__) return;
    window.__CEO_CHATBOX_APP__ = true;

    const cfg = (window.__EVO_UI__ = window.__EVO_UI__ || {});
    const mountSelector = cfg.mountSelector || "#ceo-left-panel";

    // CEO Console canonical endpoints (backend router prefix: /api/ceo-console/*)
    const ceoCommandUrl = cfg.ceoCommandUrl || "/api/ceo-console/command";
    const ceoStatusUrl = cfg.ceoStatusUrl || "/api/ceo-console/status";

    // NOTE: CEO Console flow is read-only; it returns proposed_commands (BLOCKED) without approval_id.
    // approveUrl is intentionally not used here to avoid misleading UX.
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

    // Approve button removed/disabled intentionally (CEO Console returns proposals, not approvals)
    const approveBtn = document.createElement("button");
    approveBtn.className = "ceo-chatbox-btn";
    approveBtn.type = "button";
    approveBtn.textContent = "Odobri";
    approveBtn.disabled = true;
    approveBtn.title =
      "CEO Console je read-only. Nema approval_id u ovom flow-u (samo proposed_commands = BLOCKED).";

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

      if (meta && (meta.state || meta.extra)) {
        const metaRow = document.createElement("div");
        metaRow.className = "ceo-chatbox-meta";

        if (meta.state) {
          const pill = document.createElement("span");
          pill.className = "ceo-chatbox-pill";
          pill.innerHTML = `<strong>Status:</strong> ${meta.state}`;
          metaRow.appendChild(pill);
        }
        if (meta.extra) {
          const pill = document.createElement("span");
          pill.className = "ceo-chatbox-pill";
          pill.innerHTML = meta.extra;
          metaRow.appendChild(pill);
        }

        msg.appendChild(metaRow);
      }

      const stayAtBottom = isNearBottom();
      history.appendChild(row);
      lastRole = role;

      scrollToBottom(stayAtBottom);
      updateScrollBtn();
    }

    function setBusy(next) {
      busy = next;
      sendBtn.disabled = next;
      textarea.disabled = next;
      typing.style.display = next ? "block" : "none";
      // approve always disabled in this flow
      approveBtn.disabled = true;
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

    function formatProposedCommands(proposed) {
      if (!Array.isArray(proposed) || proposed.length === 0) return "";
      const lines = proposed
        .map((p, i) => {
          const cmd = p && (p.command_type || p.command || "");
          const status = (p && p.status) || "BLOCKED";
          const risk = (p && (p.risk_hint || p.risk)) || "";
          return `${i + 1}) ${cmd || "unknown_command"} | ${status}${
            risk ? ` | risk=${risk}` : ""
          }`;
        })
        .join("\n");
      return `\n\nProposed commands (BLOCKED)\n${lines}`;
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
        const payload = {
          text,
          initiator: cfg.initiator || "ceo_dashboard",
          // session_id is optional; if you have one in cfg, include it
          session_id: cfg.session_id || undefined,
          // context_hint is optional; backend will fallback to server snapshot if not provided
          context_hint: cfg.context_hint || undefined,
        };

        const res = await fetch(ceoCommandUrl, {
          method: "POST",
          headers,
          body: JSON.stringify(payload),
        });

        const raw = await readBodyAsText(res);
        if (!res.ok) {
          addMessage(
            "sys",
            `Greška: ${res.status}\n${raw || "N/A"}`,
            { state: "ERROR" }
          );
          return;
        }

        const data = safeJsonParse(raw) || {};
        const summary =
          (typeof data.summary === "string" && data.summary.trim()) ||
          (typeof data.text === "string" && data.text.trim()) ||
          (raw && raw.trim()) ||
          "Nema odgovora.";

        const proposed = data.proposed_commands || [];
        const extra = formatProposedCommands(proposed);

        addMessage("sys", summary + extra, { state: "OK" });

        textarea.value = "";
        autosize();

        // If page has a snapshot refresh button, trigger it (optional)
        const snapBtn = document.getElementById("refresh-snapshot-btn");
        if (snapBtn) snapBtn.click();
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
    });
  } catch (e) {
    console.error("[CEO_CHATBOX] init failed", e);
  }
})();
