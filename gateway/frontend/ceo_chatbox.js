// gateway/frontend/ceo_chatbox.js
(function () {
  const APP_FLAG = "__CEO_CHATBOX_APP__";
  const ROOT_ID = "ceo-chatbox-root";
  const STYLE_ID = "ceo-chatbox-style";
  const REMOUNT_DEBOUNCE_MS = 80;

  try {
    // Allow self-heal remounts, but prevent double-mount within same DOM.
    if (!window[APP_FLAG]) window[APP_FLAG] = { mounted: false, remountTimer: null };

    const cfg = (window.__EVO_UI__ = window.__EVO_UI__ || {});
    const mountSelector = cfg.mountSelector || "#ceo-left-panel";
    const ceoCommandUrl = cfg.ceoCommandUrl || "/ceo/command";
    const approveUrl = cfg.approveUrl || "/api/ai-ops/approval/approve";
    const headers = Object.assign({ "Content-Type": "application/json" }, cfg.headers || {});

    function $(id) {
      return document.getElementById(id);
    }

    function safeHideLegacy() {
      // Hide only the specific legacy elements or their *small* local wrappers.
      // DO NOT use broad closest() that can accidentally hide the entire left card.
      const legacyIds = [
        "ceo-history",
        "ceo-command-input",
        "send-command-btn",
        "approve-latest-btn",
        "refresh-snapshot-btn",
        "command-status-chip",
        "command-status-text",
        "last-execution-state",
        "last-approval-id",
      ];

      legacyIds.forEach((id) => {
        const el = $(id);
        if (!el) return;

        // Prefer hiding a tight wrapper if present; otherwise hide the element itself.
        const wrapper =
          el.closest && (el.closest(".chat-input-bar") || el.closest(".command-actions-row") || el.closest(".command-status"));

        if (wrapper && wrapper !== document.body && wrapper !== document.documentElement) {
          wrapper.style.display = "none";
        } else {
          el.style.display = "none";
        }
      });
    }

    function ensureChatGptLayout(host) {
      // Force host to be a proper "chat viewport": column flex with min-height:0 so children can scroll.
      host.style.display = "flex";
      host.style.flexDirection = "column";
      host.style.minHeight = "0";
      host.style.height = "100%";

      // Walk up a few parents and apply min-height:0 so nested flex doesn't break scrolling.
      let p = host.parentElement;
      let depth = 0;
      while (p && depth < 6) {
        const cs = window.getComputedStyle(p);
        // If parent is flex/grid container, min-height:0 is required for descendants to scroll.
        if (cs.display === "flex" || cs.display === "grid") {
          p.style.minHeight = "0";
          // If it's the left card body, enforce column.
          if (cs.display === "flex" && cs.flexDirection === "column") {
            p.style.minHeight = "0";
          }
        }
        depth += 1;
        p = p.parentElement;
      }

      // Try to slightly reduce left column width (only if we can safely detect a 2-column container).
      // We look for an ancestor whose display is flex and has >=2 direct children.
      let a = host;
      for (let i = 0; i < 8 && a; i++) {
        const parent = a.parentElement;
        if (!parent) break;
        const pcs = window.getComputedStyle(parent);

        if (pcs.display === "flex" && parent.children && parent.children.length >= 2) {
          // Identify which child contains our host.
          const kids = Array.from(parent.children);
          const leftChild = kids.find((k) => k.contains(host));
          const rightChild = kids.find((k) => k !== leftChild);

          if (leftChild && rightChild) {
            // Only adjust if both children are visible blocks (avoid messing with nested flex rows).
            leftChild.style.flex = "0 0 53%";
            rightChild.style.flex = "1 1 47%";
            // ensure right can scroll internally if needed
            rightChild.style.minWidth = "0";
            leftChild.style.minWidth = "0";
            break;
          }
        }
        a = parent;
      }
    }

    function injectStyles() {
      if (document.getElementById(STYLE_ID)) return;

      const style = document.createElement("style");
      style.id = STYLE_ID;
      style.textContent = `
        /* ChatGPT-like micro-layout */
        .ceo-chatbox { display:flex; flex-direction:column; min-height:0; height:100%; }
        .ceo-chatbox-history {
          flex:1; min-height:0; overflow:auto;
          padding: 18px 18px 14px 18px;
          border: 1px solid rgba(255,255,255,.10);
          border-radius: 16px;
          background: rgba(0,0,0,.10);
          scroll-behavior: smooth;
          overscroll-behavior: contain;
        }

        /* Scrollbar similar feel */
        .ceo-chatbox-history::-webkit-scrollbar { width: 10px; }
        .ceo-chatbox-history::-webkit-scrollbar-track { background: transparent; }
        .ceo-chatbox-history::-webkit-scrollbar-thumb {
          background: rgba(255,255,255,.12);
          border-radius: 999px;
          border: 2px solid transparent;
          background-clip: padding-box;
        }
        .ceo-chatbox-history::-webkit-scrollbar-thumb:hover { background: rgba(255,255,255,.18); background-clip: padding-box; }

        .ceo-chatbox-row { display:flex; gap:12px; margin: 10px 0; align-items:flex-start; }
        .ceo-chatbox-row.grouped { margin-top: 2px; }
        .ceo-chatbox-badge {
          width: 34px; height: 34px; border-radius: 12px;
          display:flex; align-items:center; justify-content:center;
          font-weight: 800; font-size: 11px;
          border: 1px solid rgba(255,255,255,.14);
          background: rgba(255,255,255,.04);
          color: rgba(255,255,255,.90);
          flex: 0 0 auto;
          margin-top: 2px;
        }
        .ceo-chatbox-row.grouped .ceo-chatbox-badge { visibility: hidden; }

        .ceo-chatbox-msg {
          flex:1;
          white-space: pre-wrap;
          line-height: 1.52;
          font-size: 14px;
          color: rgba(255,255,255,.92);
          padding: 12px 14px;
          border-radius: 14px;
          border: 1px solid rgba(255,255,255,.10);
          background: rgba(0,0,0,.14);
          animation: ceoFadeIn .12s ease-out;
        }
        .ceo-chatbox-msg.ceo { background: rgba(0,0,0,.18); }
        .ceo-chatbox-msg.sys { background: rgba(255,255,255,.06); }

        @keyframes ceoFadeIn { from { opacity: .0; transform: translateY(2px); } to { opacity: 1; transform: translateY(0); } }

        .ceo-chatbox-meta { margin-top: 10px; display:flex; gap:10px; align-items:center; flex-wrap: wrap; }
        .ceo-chatbox-pill {
          display:inline-flex; align-items:center; gap:8px;
          padding:6px 10px; border-radius:999px;
          border: 1px solid rgba(255,255,255,.12);
          background: rgba(0,0,0,.12);
          color: rgba(255,255,255,.78);
          font-size: 12px;
        }
        .ceo-chatbox-pill strong { color: rgba(255,255,255,.92); font-weight: 800; }

        /* Composer fixed to bottom of left panel (ChatGPT behavior) */
        .ceo-chatbox-composer {
          margin-top: 12px;
          border: 1px solid rgba(255,255,255,.10);
          border-radius: 16px;
          background: rgba(0,0,0,.24);
          padding: 10px;
          display:flex; gap: 10px; align-items: flex-end;
          position: sticky;
          bottom: 0;
          backdrop-filter: blur(6px);
        }
        .ceo-chatbox-textarea {
          flex:1; resize:none;
          border: 1px solid rgba(255,255,255,.12);
          border-radius: 14px;
          background: rgba(0,0,0,.22);
          color: rgba(255,255,255,.95);
          padding: 12px 12px;
          line-height: 1.35;
          font-size: 14px;
          max-height: 180px;
          min-height: 48px;
          outline: none;
          transition: border-color .12s ease, box-shadow .12s ease;
        }
        .ceo-chatbox-textarea:focus {
          border-color: rgba(34,197,94,.45);
          box-shadow: 0 0 0 3px rgba(34,197,94,.10);
        }

        .ceo-chatbox-btn {
          border-radius: 14px;
          padding: 11px 14px;
          border: 1px solid rgba(255,255,255,.12);
          background: rgba(255,255,255,.08);
          color: rgba(255,255,255,.92);
          font-weight: 800;
          cursor: pointer;
          transition: transform .06s ease, background .12s ease, border-color .12s ease, opacity .12s ease;
          user-select: none;
        }
        .ceo-chatbox-btn:hover { background: rgba(255,255,255,.11); }
        .ceo-chatbox-btn:active { transform: translateY(1px); }
        .ceo-chatbox-btn:disabled { opacity: .55; cursor: not-allowed; }
        .ceo-chatbox-btn.primary {
          background: rgba(34,197,94,.18);
          border-color: rgba(34,197,94,.35);
        }
        .ceo-chatbox-btn.primary:hover { background: rgba(34,197,94,.22); }

        .ceo-chatbox-typing { opacity:.75; font-size: 12px; margin-top: 8px; color: rgba(255,255,255,.68); }
        .ceo-chatbox-jump {
          position: absolute;
          right: 18px;
          bottom: 86px;
          border-radius: 999px;
          padding: 8px 10px;
          border: 1px solid rgba(255,255,255,.12);
          background: rgba(0,0,0,.28);
          color: rgba(255,255,255,.88);
          font-size: 12px;
          cursor: pointer;
          display:none;
          backdrop-filter: blur(6px);
        }
      `;
      document.head.appendChild(style);
    }

    function createApp(host) {
      // If already exists in DOM, do nothing.
      if (host.querySelector("#" + ROOT_ID)) return;

      injectStyles();
      ensureChatGptLayout(host);
      safeHideLegacy();

      host.innerHTML = "";

      const root = document.createElement("div");
      root.className = "ceo-chatbox";
      root.id = ROOT_ID;

      const historyWrap = document.createElement("div");
      historyWrap.style.position = "relative";
      historyWrap.style.minHeight = "0";
      historyWrap.style.flex = "1";

      const history = document.createElement("div");
      history.className = "ceo-chatbox-history";

      const jumpBtn = document.createElement("button");
      jumpBtn.className = "ceo-chatbox-jump";
      jumpBtn.type = "button";
      jumpBtn.textContent = "↓ Na dno";

      const typing = document.createElement("div");
      typing.className = "ceo-chatbox-typing";
      typing.style.display = "none";
      typing.textContent = "SYSTEM obrađuje zahtjev…";

      const composer = document.createElement("div");
      composer.className = "ceo-chatbox-composer";

      const textarea = document.createElement("textarea");
      textarea.className = "ceo-chatbox-textarea";
      textarea.placeholder = "Unesi CEO COMMAND… (Enter = pošalji, Shift+Enter = novi red)";

      const sendBtn = document.createElement("button");
      sendBtn.className = "ceo-chatbox-btn primary";
      sendBtn.type = "button";
      sendBtn.textContent = "Pošalji";

      const approveBtn = document.createElement("button");
      approveBtn.className = "ceo-chatbox-btn";
      approveBtn.type = "button";
      approveBtn.textContent = "Odobri";
      approveBtn.disabled = true;

      composer.appendChild(textarea);
      composer.appendChild(sendBtn);
      composer.appendChild(approveBtn);

      historyWrap.appendChild(history);
      historyWrap.appendChild(jumpBtn);

      root.appendChild(historyWrap);
      root.appendChild(typing);
      root.appendChild(composer);
      host.appendChild(root);

      let lastRole = null;
      let lastApprovalId = null;
      let busy = false;
      let userPinnedUp = false;

      function isNearBottom() {
        const threshold = 140;
        return history.scrollHeight - history.scrollTop - history.clientHeight < threshold;
      }

      function scrollToBottom(force) {
        if (!force && userPinnedUp) return;
        history.scrollTop = history.scrollHeight;
      }

      function updateJump() {
        const near = isNearBottom();
        userPinnedUp = !near;
        jumpBtn.style.display = userPinnedUp ? "inline-flex" : "none";
      }

      history.addEventListener("scroll", () => updateJump());
      jumpBtn.addEventListener("click", () => {
        userPinnedUp = false;
        scrollToBottom(true);
        updateJump();
      });

      function addMessage(role, text, meta) {
        const row = document.createElement("div");
        row.className = "ceo-chatbox-row";

        if (lastRole === role) row.classList.add("grouped");
        lastRole = role;

        const badge = document.createElement("div");
        badge.className = "ceo-chatbox-badge";
        badge.textContent = role === "ceo" ? "CEO" : "SYS";

        const msg = document.createElement("div");
        msg.className = "ceo-chatbox-msg " + (role === "ceo" ? "ceo" : "sys");
        msg.textContent = text;

        row.appendChild(badge);
        row.appendChild(msg);

        if (meta && (meta.state || meta.approval_id)) {
          const metaRow = document.createElement("div");
          metaRow.className = "ceo-chatbox-meta";

          if (meta.state) {
            const pill = document.createElement("span");
            pill.className = "ceo-chatbox-pill";
            pill.innerHTML = `<strong>Status:</strong> ${meta.state}`;
            metaRow.appendChild(pill);
          }
          if (meta.approval_id) {
            const pill = document.createElement("span");
            pill.className = "ceo-chatbox-pill";
            pill.innerHTML = `<strong>approval_id:</strong> ${meta.approval_id}`;
            metaRow.appendChild(pill);
          }
          msg.appendChild(metaRow);
        }

        history.appendChild(row);
        scrollToBottom(false);
        updateJump();
      }

      function setBusy(next) {
        busy = next;
        sendBtn.disabled = next;
        textarea.disabled = next;
        typing.style.display = next ? "block" : "none";
      }

      function autosize() {
        textarea.style.height = "48px";
        textarea.style.height = Math.min(textarea.scrollHeight, 180) + "px";
      }

      textarea.addEventListener("input", autosize);
      textarea.addEventListener("keydown", (e) => {
        if (e.key === "Enter" && !e.shiftKey && !e.ctrlKey && !e.altKey && !e.metaKey) {
          e.preventDefault();
          sendBtn.click();
        }
      });

      async function sendCommand() {
        const text = (textarea.value || "").trim();
        if (!text || busy) return;

        addMessage("ceo", text);
        setBusy(true);
        approveBtn.disabled = true;
        lastApprovalId = null;

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
            addMessage("sys", `Greška: ${res.status}\n${detail || "N/A"}`, { state: "ERROR" });
            return;
          }

          const data = await res.json();
          lastApprovalId = data.approval_id || null;

          // Minimal, bez “Dobrodošli …” i bez duplih status boxova
          addMessage(
            "sys",
            "Primljeno. Zahtjev je BLOCKED i čeka eksplicitno odobrenje.",
            { state: "BLOCKED", approval_id: lastApprovalId || "–" }
          );

          if (lastApprovalId) approveBtn.disabled = false;

          textarea.value = "";
          autosize();

          const snapBtn = $("refresh-snapshot-btn");
          if (snapBtn) snapBtn.click();
        } catch (err) {
          addMessage("sys", "Greška pri slanju naredbe.", { state: "ERROR" });
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
            addMessage("sys", `Greška pri odobravanju: ${res.status}\n${detail || ""}`, { state: "ERROR" });
            return;
          }

          addMessage("sys", "Odobreno. Execution je pokrenut (vidljivo kroz snapshot/KPI).", {
            state: "APPROVED/EXECUTED",
            approval_id: lastApprovalId,
          });

          approveBtn.disabled = true;

          const snapBtn = $("refresh-snapshot-btn");
          if (snapBtn) snapBtn.click();
        } catch (err) {
          addMessage("sys", "Greška pri odobravanju zahtjeva.", { state: "ERROR" });
        } finally {
          setBusy(false);
        }
      }

      sendBtn.addEventListener("click", sendCommand);
      approveBtn.addEventListener("click", approveLatest);

      // Focus input
      setTimeout(() => textarea.focus(), 50);

      // Init scroll state
      updateJump();

      console.log("[CEO_CHATBOX] mounted", { mountSelector, ceoCommandUrl, approveUrl });
    }

    function mountOrHeal() {
      const host = document.querySelector(mountSelector);
      if (!host) return;

      // If already present, just ensure layout.
      if (host.querySelector("#" + ROOT_ID)) {
        ensureChatGptLayout(host);
        return;
      }
      createApp(host);
    }

    function scheduleRemount() {
      const st = window[APP_FLAG];
      if (st.remountTimer) return;
      st.remountTimer = setTimeout(() => {
        st.remountTimer = null;
        mountOrHeal();
      }, REMOUNT_DEBOUNCE_MS);
    }

    // Initial mount
    mountOrHeal();

    // Self-heal if some other script re-renders / wipes the left panel after snapshots load
    const obs = new MutationObserver((mutations) => {
      for (const m of mutations) {
        if (m.type !== "childList") continue;
        // If our root got removed anywhere, remount.
        const removed = Array.from(m.removedNodes || []);
        if (removed.some((n) => n && n.id === ROOT_ID)) {
          scheduleRemount();
          return;
        }
      }
      // Also: if host exists but root missing (wiped), remount.
      const host = document.querySelector(mountSelector);
      if (host && !host.querySelector("#" + ROOT_ID)) {
        scheduleRemount();
      }
    });

    obs.observe(document.body, { childList: true, subtree: true });

    // Remount on visibility change (useful on slow initial loads)
    document.addEventListener("visibilitychange", () => {
      if (!document.hidden) scheduleRemount();
    });
  } catch (e) {
    console.error("[CEO_CHATBOX] init failed", e);
  }
})();
