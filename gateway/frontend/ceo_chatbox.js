// gateway/frontend/ceo_chatbox.js
(function () {
  try {
    if (window.__CEO_CHATBOX_APP__) return;
    window.__CEO_CHATBOX_APP__ = true;

    const cfg = (window.__EVO_UI__ = window.__EVO_UI__ || {});
    const mountSelector = cfg.mountSelector || "#ceo-left-panel";
    const ceoCommandUrl = cfg.ceoCommandUrl || "/ceo/command";
    const approveUrl = cfg.approveUrl || "/api/ai-ops/approval/approve";
    const headers = Object.assign({ "Content-Type": "application/json" }, cfg.headers || {});

    const host = document.querySelector(mountSelector);
    if (!host) return;

    // ---- Styles (ChatGPT-like) ----
    const style = document.createElement("style");
    style.textContent = `
      :root {
        --ceo-bg: rgba(0,0,0,.20);
        --ceo-surface: rgba(255,255,255,.04);
        --ceo-border: rgba(255,255,255,.10);
        --ceo-border-strong: rgba(255,255,255,.14);
        --ceo-text: rgba(255,255,255,.92);
        --ceo-muted: rgba(255,255,255,.68);
        --ceo-muted2: rgba(255,255,255,.58);
        --ceo-shadow: 0 14px 40px rgba(0,0,0,.35);
        --ceo-radius: 14px;
        --ceo-radius-lg: 18px;
        --ceo-green: rgba(34,197,94,1);
      }

      @keyframes ceoFadeIn {
        from { opacity: 0; transform: translateY(6px); }
        to { opacity: 1; transform: translateY(0); }
      }

      .ceo-chat {
        height: 100%;
        min-height: 0;
        display: flex;
        flex-direction: column;
        gap: 10px;
      }

      /* HISTORY */
      .ceo-chat-history {
        flex: 1;
        min-height: 0;
        overflow: auto;
        padding: 18px 16px;
        border: 1px solid var(--ceo-border);
        background: var(--ceo-bg);
        border-radius: var(--ceo-radius-lg);
        box-shadow: inset 0 0 0 1px rgba(0,0,0,.08);
        scroll-behavior: smooth;
      }

      .ceo-empty {
        color: var(--ceo-muted2);
        font-size: 13px;
        line-height: 1.45;
        padding: 10px 6px 14px 6px;
        user-select: none;
      }

      .ceo-msg {
        display: grid;
        grid-template-columns: 36px 1fr;
        gap: 12px;
        align-items: start;
        margin: 10px 0;
        animation: ceoFadeIn 140ms ease-out;
      }

      .ceo-msg.ceo { }
      .ceo-msg.sys { }

      .ceo-avatar {
        width: 34px;
        height: 34px;
        border-radius: 10px;
        display: flex;
        align-items: center;
        justify-content: center;
        font-weight: 800;
        font-size: 12px;
        border: 1px solid var(--ceo-border);
        background: rgba(255,255,255,.06);
        color: rgba(255,255,255,.88);
        box-shadow: 0 4px 18px rgba(0,0,0,.22);
      }

      .ceo-avatar.ceo {
        background: rgba(255,255,255,.04);
      }
      .ceo-avatar.sys {
        background: rgba(255,255,255,.07);
      }

      .ceo-bubble {
        border-radius: 16px;
        border: 1px solid var(--ceo-border);
        background: rgba(0,0,0,.16);
        padding: 12px 14px;
        color: var(--ceo-text);
        font-size: 14px;
        line-height: 1.5;
        white-space: pre-wrap;
      }

      .ceo-bubble.sys {
        background: rgba(255,255,255,.06);
      }

      /* Grouping: continuation message = no avatar column */
      .ceo-msg.cont {
        grid-template-columns: 36px 1fr;
        margin-top: 6px;
      }
      .ceo-msg.cont .ceo-avatar {
        visibility: hidden;
      }
      .ceo-msg.cont .ceo-bubble {
        border-top-left-radius: 10px;
        border-top-right-radius: 10px;
      }

      /* Meta pills */
      .ceo-meta {
        margin-top: 10px;
        display: flex;
        flex-wrap: wrap;
        gap: 8px;
      }
      .ceo-pill {
        display: inline-flex;
        align-items: center;
        gap: 8px;
        padding: 6px 10px;
        border-radius: 999px;
        border: 1px solid var(--ceo-border);
        background: rgba(0,0,0,.14);
        color: var(--ceo-muted);
        font-size: 12px;
      }
      .ceo-pill strong {
        color: rgba(255,255,255,.88);
        font-weight: 800;
      }

      /* Typing indicator */
      .ceo-typing {
        display: none;
        align-items: center;
        gap: 10px;
        color: var(--ceo-muted);
        font-size: 12px;
        padding: 0 6px;
        user-select: none;
      }
      .ceo-dots {
        display: inline-flex;
        gap: 4px;
      }
      .ceo-dots span {
        width: 6px; height: 6px; border-radius: 999px;
        background: rgba(255,255,255,.45);
        animation: ceoDot 900ms infinite ease-in-out;
      }
      .ceo-dots span:nth-child(2){ animation-delay: 150ms; }
      .ceo-dots span:nth-child(3){ animation-delay: 300ms; }
      @keyframes ceoDot {
        0%, 80%, 100% { transform: translateY(0); opacity: .55; }
        40% { transform: translateY(-3px); opacity: 1; }
      }

      /* Composer (sticky bottom) */
      .ceo-composer {
        position: sticky;
        bottom: 0;
        border: 1px solid var(--ceo-border);
        background: rgba(0,0,0,.26);
        border-radius: var(--ceo-radius-lg);
        padding: 12px;
        display: flex;
        align-items: flex-end;
        gap: 10px;
        box-shadow: var(--ceo-shadow);
        backdrop-filter: blur(10px);
      }

      .ceo-textarea {
        flex: 1;
        min-height: 46px;
        max-height: 180px;
        resize: none;
        outline: none;
        border-radius: 14px;
        border: 1px solid var(--ceo-border-strong);
        background: rgba(0,0,0,.24);
        color: var(--ceo-text);
        padding: 12px 12px;
        line-height: 1.35;
        font-size: 14px;
      }
      .ceo-textarea::placeholder { color: rgba(255,255,255,.42); }

      .ceo-textarea:focus {
        border-color: rgba(34,197,94,.35);
        box-shadow: 0 0 0 3px rgba(34,197,94,.10);
      }

      .ceo-actions {
        display: flex;
        align-items: center;
        gap: 8px;
        flex: 0 0 auto;
      }

      .ceo-btn {
        height: 46px;
        border-radius: 14px;
        border: 1px solid var(--ceo-border);
        background: rgba(255,255,255,.08);
        color: rgba(255,255,255,.92);
        font-weight: 800;
        padding: 0 12px;
        cursor: pointer;
        transition: transform 120ms ease, background 120ms ease, border-color 120ms ease, opacity 120ms ease;
        user-select: none;
        white-space: nowrap;
      }

      .ceo-btn:hover {
        background: rgba(255,255,255,.10);
        border-color: rgba(255,255,255,.18);
        transform: translateY(-1px);
      }
      .ceo-btn:active { transform: translateY(0); }

      .ceo-btn.primary {
        background: rgba(34,197,94,.18);
        border-color: rgba(34,197,94,.32);
      }
      .ceo-btn.primary:hover {
        background: rgba(34,197,94,.22);
        border-color: rgba(34,197,94,.40);
      }

      .ceo-btn:disabled {
        opacity: .55;
        cursor: not-allowed;
        transform: none;
      }

      /* Floating "scroll to bottom" */
      .ceo-scroll {
        position: sticky;
        bottom: 74px;
        margin-left: auto;
        width: fit-content;
        display: none;
        z-index: 2;
      }
      .ceo-scroll button {
        border-radius: 999px;
        padding: 8px 10px;
        border: 1px solid var(--ceo-border);
        background: rgba(0,0,0,.35);
        color: rgba(255,255,255,.88);
        cursor: pointer;
        font-weight: 800;
      }
      .ceo-scroll button:hover {
        background: rgba(0,0,0,.45);
      }
    `;
    document.head.appendChild(style);

    // ---- DOM ----
    host.innerHTML = "";
    const root = document.createElement("div");
    root.className = "ceo-chat";

    const history = document.createElement("div");
    history.className = "ceo-chat-history";

    const empty = document.createElement("div");
    empty.className = "ceo-empty";
    empty.textContent = ""; // intentionally empty (no welcome block)
    history.appendChild(empty);

    const scrollWrap = document.createElement("div");
    scrollWrap.className = "ceo-scroll";
    const scrollBtn = document.createElement("button");
    scrollBtn.type = "button";
    scrollBtn.textContent = "↓";
    scrollWrap.appendChild(scrollBtn);

    const typing = document.createElement("div");
    typing.className = "ceo-typing";
    typing.innerHTML = `<span>SYSTEM obrađuje</span><span class="ceo-dots"><span></span><span></span><span></span></span>`;

    const composer = document.createElement("div");
    composer.className = "ceo-composer";

    const textarea = document.createElement("textarea");
    textarea.className = "ceo-textarea";
    textarea.placeholder =
      cfg.placeholder ||
      'Unesi CEO COMMAND… (Enter = pošalji, Shift+Enter = novi red)';

    const actions = document.createElement("div");
    actions.className = "ceo-actions";

    const sendBtn = document.createElement("button");
    sendBtn.className = "ceo-btn primary";
    sendBtn.type = "button";
    sendBtn.textContent = cfg.sendLabel || "Pošalji";

    const approveBtn = document.createElement("button");
    approveBtn.className = "ceo-btn";
    approveBtn.type = "button";
    approveBtn.textContent = cfg.approveLabel || "Odobri";
    approveBtn.disabled = true;

    actions.appendChild(sendBtn);
    actions.appendChild(approveBtn);

    composer.appendChild(textarea);
    composer.appendChild(actions);

    root.appendChild(history);
    root.appendChild(scrollWrap);
    root.appendChild(typing);
    root.appendChild(composer);
    host.appendChild(root);

    // ---- State ----
    let lastApprovalId = null;
    let busy = false;
    let lastRole = null;

    // ---- Helpers ----
    function isNearBottom() {
      const threshold = 90;
      return history.scrollHeight - history.scrollTop - history.clientHeight < threshold;
    }

    function scrollToBottom(force) {
      if (force || isNearBottom()) {
        history.scrollTop = history.scrollHeight;
        scrollWrap.style.display = "none";
      } else {
        scrollWrap.style.display = "block";
      }
    }

    function setBusy(next) {
      busy = next;
      sendBtn.disabled = next;
      textarea.disabled = next;
      approveBtn.disabled = next || !lastApprovalId;
      typing.style.display = next ? "flex" : "none";
    }

    function autosize() {
      textarea.style.height = "46px";
      textarea.style.height = Math.min(textarea.scrollHeight, 180) + "px";
    }

    function extractTextFromBackend(data) {
      if (!data || typeof data !== "object") return "";
      return (
        data.system_message ||
        data.message ||
        data.detail ||
        data.response ||
        data.text ||
        data.output_text ||
        ""
      );
    }

    function addMessage(role, text, meta) {
      if (empty && empty.textContent === "") {
        // keep empty node but do not show content; remove it once first message comes
        empty.remove();
      }

      const cont = lastRole === role;
      const row = document.createElement("div");
      row.className = "ceo-msg " + (role === "ceo" ? "ceo" : "sys") + (cont ? " cont" : "");

      const avatar = document.createElement("div");
      avatar.className = "ceo-avatar " + (role === "ceo" ? "ceo" : "sys");
      avatar.textContent = role === "ceo" ? "CEO" : "SYS";

      const bubble = document.createElement("div");
      bubble.className = "ceo-bubble " + (role === "ceo" ? "ceo" : "sys");
      bubble.textContent = text || "";

      if (meta && (meta.state || meta.approval_id)) {
        const metaRow = document.createElement("div");
        metaRow.className = "ceo-meta";

        if (meta.state) {
          const pill = document.createElement("span");
          pill.className = "ceo-pill";
          pill.innerHTML = `<strong>Status</strong> ${meta.state}`;
          metaRow.appendChild(pill);
        }
        if (meta.approval_id) {
          const pill = document.createElement("span");
          pill.className = "ceo-pill";
          pill.innerHTML = `<strong>approval_id</strong> ${meta.approval_id}`;
          metaRow.appendChild(pill);
        }

        bubble.appendChild(metaRow);
      }

      row.appendChild(avatar);
      row.appendChild(bubble);

      history.appendChild(row);
      lastRole = role;

      scrollToBottom(false);
      return bubble;
    }

    // ---- Events ----
    history.addEventListener("scroll", () => {
      if (isNearBottom()) scrollWrap.style.display = "none";
      else scrollWrap.style.display = "block";
    });

    scrollBtn.addEventListener("click", () => scrollToBottom(true));

    textarea.addEventListener("input", autosize);

    textarea.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey && !e.ctrlKey && !e.altKey && !e.metaKey) {
        e.preventDefault();
        sendBtn.click();
      }
    });

    // ---- Core actions ----
    async function sendCommand() {
      const text = (textarea.value || "").trim();
      if (!text || busy) return;

      addMessage("ceo", text);
      textarea.value = "";
      autosize();

      lastApprovalId = null;
      approveBtn.disabled = true;
      setBusy(true);

      try {
        const res = await fetch(ceoCommandUrl, {
          method: "POST",
          headers,
          body: JSON.stringify({
            input_text: text,
            smart_context: null,
            source: "ceo_dashboard",
          }),
        });

        if (!res.ok) {
          const detail = await res.text();
          addMessage("sys", detail || "", { state: "ERROR" });
          return;
        }

        const data = await res.json();
        lastApprovalId = data.approval_id || null;

        const backendText = extractTextFromBackend(data);
        const sysText = backendText || ""; // avoid extra explanatory boilerplate
        addMessage("sys", sysText, {
          state: "BLOCKED",
          approval_id: lastApprovalId || "–",
        });

        approveBtn.disabled = !lastApprovalId;

        // refresh snapshot on right side (reuse existing button if present)
        const snapBtn = document.getElementById("refresh-snapshot-btn");
        if (snapBtn) snapBtn.click();
      } catch (e) {
        addMessage("sys", "", { state: "ERROR" });
      } finally {
        setBusy(false);
      }
    }

    async function approveLatest() {
      if (!lastApprovalId || busy) return;
      setBusy(true);

      try {
        const res = await fetch(approveUrl, {
          method: "POST",
          headers,
          body: JSON.stringify({ approval_id: lastApprovalId }),
        });

        if (!res.ok) {
          const detail = await res.text();
          addMessage("sys", detail || "", { state: "ERROR", approval_id: lastApprovalId });
          return;
        }

        // no agent details; only governance signal
        const data = await res.json().catch(() => null);
        const backendText = extractTextFromBackend(data);
        addMessage("sys", backendText || "", {
          state: "APPROVED/EXECUTED",
          approval_id: lastApprovalId,
        });

        approveBtn.disabled = true;

        const snapBtn = document.getElementById("refresh-snapshot-btn");
        if (snapBtn) snapBtn.click();
      } catch (e) {
        addMessage("sys", "", { state: "ERROR", approval_id: lastApprovalId });
      } finally {
        setBusy(false);
      }
    }

    sendBtn.addEventListener("click", sendCommand);
    approveBtn.addEventListener("click", approveLatest);

    // Focus
    setTimeout(() => textarea.focus(), 50);

    // Logging (keep)
    console.log("[CEO_CHATBOX] mounted", { mountSelector, ceoCommandUrl, approveUrl });
  } catch (e) {
    console.error("[CEO_CHATBOX] init failed", e);
  }
})();
