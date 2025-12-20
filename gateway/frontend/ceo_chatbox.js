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

    // legacy ostaje, ali je već skriven u index.html (#ceo-chat-legacy display:none)
    host.innerHTML = "";

    const root = document.createElement("div");
    root.className = "ceo-chatbox";

    const history = document.createElement("div");
    history.className = "ceo-chatbox-history";

    const empty = document.createElement("div");
    empty.className = "ceo-chatbox-empty";
    empty.textContent = "Napiši CEO komandu ispod. History je scroll, input je fiksno na dnu.";
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

    root.appendChild(history);
    root.appendChild(scrollBtn);
    root.appendChild(typing);
    root.appendChild(composer);
    host.appendChild(root);

    let lastApprovalId = null;
    let busy = false;
    let lastRole = null;

    function isNearBottom() {
      const threshold = 120;
      return history.scrollHeight - (history.scrollTop + history.clientHeight) < threshold;
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
      if (next) approveBtn.disabled = true;
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

    async function readErrorBody(res) {
      const ct = (res.headers.get("content-type") || "").toLowerCase();
      try {
        if (ct.includes("application/json")) {
          const j = await res.json();
          return JSON.stringify(j, null, 2);
        }
      } catch {}
      try {
        return await res.text();
      } catch {
        return "N/A";
      }
    }

    async function sendCommand() {
      const text = (textarea.value || "").trim();
      if (!text || busy) return;

      addMessage("ceo", text);
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
          const detail = await readErrorBody(res);
          addMessage("sys", `Greška: ${res.status}\n${detail || "N/A"}`, { state: "ERROR" });
          return;
        }

        const data = await res.json();
        lastApprovalId = data.approval_id || null;

        addMessage(
          "sys",
          "Zahtjev je u BLOCKED stanju i čeka eksplicitno odobrenje.",
          { state: "BLOCKED", approval_id: lastApprovalId || "–" }
        );

        approveBtn.disabled = !lastApprovalId;

        textarea.value = "";
        autosize();

        const snapBtn = document.getElementById("refresh-snapshot-btn");
        if (snapBtn) snapBtn.click();
      } catch (err) {
        addMessage("sys", "Greška pri slanju naredbe.", { state: "ERROR" });
      } finally {
        setBusy(false);
        textarea.focus();
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
          const detail = await readErrorBody(res);
          addMessage("sys", `Greška pri odobravanju: ${res.status}\n${detail || ""}`, { state: "ERROR" });
          return;
        }

        addMessage(
          "sys",
          "Zahtjev je odobren. Snapshot i KPI će prikazati rezultat.",
          { state: "APPROVED/EXECUTED", approval_id: lastApprovalId }
        );

        approveBtn.disabled = true;

        const snapBtn = document.getElementById("refresh-snapshot-btn");
        if (snapBtn) snapBtn.click();
      } catch (err) {
        addMessage("sys", "Greška pri odobravanju zahtjeva.", { state: "ERROR" });
      } finally {
        setBusy(false);
        textarea.focus();
      }
    }

    sendBtn.addEventListener("click", sendCommand);
    approveBtn.addEventListener("click", approveLatest);

    // start
    autosize();
    setTimeout(() => textarea.focus(), 60);

    console.log("[CEO_CHATBOX] mounted", { mountSelector, ceoCommandUrl, approveUrl });
  } catch (e) {
    console.error("[CEO_CHATBOX] init failed", e);
  }
})();
