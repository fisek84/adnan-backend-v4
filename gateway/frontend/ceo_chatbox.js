// gateway/frontend/ceo_chatbox.js
(function () {
  const APP_FLAG = "__CEO_CHATBOX_APP__";
  if (window[APP_FLAG]) return;
  window[APP_FLAG] = true;

  const cfg = (window.__EVO_UI__ = window.__EVO_UI__ || {});
  const mountSelector = cfg.mountSelector || "#ceo-left-panel";
  const ceoCommandUrl = cfg.ceoCommandUrl || "/ceo/command";
  const approveUrl = cfg.approveUrl || "/api/ai-ops/approval/approve";
  const headers = Object.assign(
    { "Content-Type": "application/json" },
    cfg.headers || {}
  );

  let lastApprovalId = null;
  let busy = false;

  function safeEl(sel) {
    try { return document.querySelector(sel); } catch { return null; }
  }

  function hideLegacyDom() {
    // sakrij legacy dio (ali ne briši DOM da script.js ne pukne)
    const legacyRoot =
      document.getElementById("ceo-chat-legacy") ||
      document.getElementById("ceo-chat-legacy-root");
    if (legacyRoot) legacyRoot.style.display = "none";
  }

  function ensureStyle() {
    if (document.getElementById("ceo-chatbox-style")) return;
    const style = document.createElement("style");
    style.id = "ceo-chatbox-style";
    style.textContent = `
      .ceo-chatbox{display:flex;flex-direction:column;height:100%;min-height:520px}
      .ceo-chatbox-history{
        flex:1;min-height:0;overflow:auto;padding:18px;
        border:1px solid rgba(255,255,255,.10);
        border-radius:18px;background:rgba(0,0,0,.10)
      }
      .ceo-chatbox-row{display:flex;gap:14px;margin:12px 0;align-items:flex-start}
      .ceo-chatbox-badge{
        width:34px;height:34px;border-radius:12px;display:flex;align-items:center;justify-content:center;
        font-weight:900;font-size:12px;letter-spacing:.2px;
        border:1px solid rgba(255,255,255,.12);
        background:rgba(255,255,255,.04);color:rgba(255,255,255,.85);flex:0 0 auto
      }
      .ceo-chatbox-msg{
        flex:1;white-space:pre-wrap;line-height:1.55;font-size:14px;
        color:rgba(255,255,255,.92);padding:12px 14px;border-radius:14px;
        border:1px solid rgba(255,255,255,.10);background:rgba(0,0,0,.12)
      }
      .ceo-chatbox-msg.ceo{background:rgba(0,0,0,.18)}
      .ceo-chatbox-msg.sys{background:rgba(255,255,255,.05)}
      .ceo-chatbox-composer{
        position:sticky;bottom:0;margin-top:14px;
        border:1px solid rgba(255,255,255,.10);border-radius:18px;background:rgba(0,0,0,.22);
        padding:12px;display:flex;gap:10px;align-items:flex-end
      }
      .ceo-chatbox-textarea{
        flex:1;resize:none;border:1px solid rgba(255,255,255,.12);
        border-radius:14px;background:rgba(0,0,0,.20);
        color:rgba(255,255,255,.92);padding:12px 14px;line-height:1.4;font-size:14px;
        max-height:180px;min-height:52px;outline:none;
      }
      .ceo-chatbox-textarea:focus{
        border-color: rgba(34,197,94,.45);
        box-shadow: 0 0 0 3px rgba(34,197,94,.14);
      }
      .ceo-chatbox-btn{
        border-radius:14px;padding:12px 14px;border:1px solid rgba(255,255,255,.12);
        background:rgba(255,255,255,.08);color:rgba(255,255,255,.92);font-weight:900;
        cursor:pointer;transition:transform 120ms ease, background 120ms ease, border-color 120ms ease, opacity 120ms ease;
        user-select:none;
      }
      .ceo-chatbox-btn:hover{background:rgba(255,255,255,.10);border-color:rgba(255,255,255,.18);transform:translateY(-1px)}
      .ceo-chatbox-btn:active{transform:translateY(0)}
      .ceo-chatbox-btn:disabled{opacity:.55;cursor:not-allowed;transform:none}
      .ceo-chatbox-btn.primary{background:rgba(34,197,94,.18);border-color:rgba(34,197,94,.35)}
      .ceo-chatbox-btn.primary:hover{background:rgba(34,197,94,.22);border-color:rgba(34,197,94,.45)}
      .ceo-chatbox-typing{opacity:.75;font-size:12px;margin-top:10px;color:rgba(255,255,255,.68)}
      .ceo-chatbox-placeholder{
        color: rgba(255,255,255,.45);
        font-size: 13px;
        padding: 10px 2px 2px;
      }
    `;
    document.head.appendChild(style);
  }

  function buildUI(host) {
    host.innerHTML = "";

    const root = document.createElement("div");
    root.className = "ceo-chatbox";
    root.setAttribute("data-ceo-chatbox-root", "1");

    const history = document.createElement("div");
    history.className = "ceo-chatbox-history";

    const placeholder = document.createElement("div");
    placeholder.className = "ceo-chatbox-placeholder";
    placeholder.textContent = "Unesi CEO COMMAND… (Enter = pošalji, Shift+Enter = novi red)";
    history.appendChild(placeholder);

    const typing = document.createElement("div");
    typing.className = "ceo-chatbox-typing";
    typing.style.display = "none";
    typing.textContent = "SYSTEM obrađuje zahtjev…";

    const composer = document.createElement("div");
    composer.className = "ceo-chatbox-composer";

    const textarea = document.createElement("textarea");
    textarea.className = "ceo-chatbox-textarea";
    textarea.placeholder =
      'Npr: Kreiraj centralni cilj "Implementirati FLP OS" sa due date 01.05.2025, prioritet Visok, status Aktivan...';

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
    root.appendChild(typing);
    root.appendChild(composer);

    host.appendChild(root);

    function scrollToBottom() {
      history.scrollTop = history.scrollHeight;
    }

    function setBusy(next) {
      busy = next;
      sendBtn.disabled = next;
      textarea.disabled = next;
      typing.style.display = next ? "block" : "none";
    }

    function autosize() {
      textarea.style.height = "52px";
      textarea.style.height = Math.min(textarea.scrollHeight, 180) + "px";
    }

    function addMessage(role, text) {
      const ph = history.querySelector(".ceo-chatbox-placeholder");
      if (ph) ph.remove();

      const row = document.createElement("div");
      row.className = "ceo-chatbox-row";

      const badge = document.createElement("div");
      badge.className = "ceo-chatbox-badge";
      badge.textContent = role === "ceo" ? "CEO" : "SYS";

      const msg = document.createElement("div");
      msg.className = "ceo-chatbox-msg " + (role === "ceo" ? "ceo" : "sys");
      msg.textContent = text;

      row.appendChild(badge);
      row.appendChild(msg);

      history.appendChild(row);
      scrollToBottom();
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
          addMessage("sys", `Greška: ${res.status}\n${detail || "N/A"}`);
          return;
        }

        const data = await res.json();
        lastApprovalId = data.approval_id || null;

        addMessage(
          "sys",
          lastApprovalId
            ? `BLOCKED. Čeka eksplicitno odobrenje.\napproval_id: ${lastApprovalId}`
            : `BLOCKED. Čeka eksplicitno odobrenje.\napproval_id: –`
        );

        if (lastApprovalId) approveBtn.disabled = false;

        textarea.value = "";
        autosize();

        const snapBtn = document.getElementById("refresh-snapshot-btn");
        if (snapBtn) snapBtn.click();
      } catch (err) {
        addMessage("sys", "Greška pri slanju naredbe.");
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
          addMessage("sys", `Greška pri odobravanju: ${res.status}\n${detail || ""}`);
          return;
        }

        addMessage("sys", `APPROVED/EXECUTED.\napproval_id: ${lastApprovalId}`);
        approveBtn.disabled = true;

        const snapBtn = document.getElementById("refresh-snapshot-btn");
        if (snapBtn) snapBtn.click();
      } catch (err) {
        addMessage("sys", "Greška pri odobravanju zahtjeva.");
      } finally {
        setBusy(false);
      }
    }

    sendBtn.addEventListener("click", sendCommand);
    approveBtn.addEventListener("click", approveLatest);

    setTimeout(() => textarea.focus(), 50);

    return { root };
  }

  function mountOrRepair() {
    const host = safeEl(mountSelector);
    if (!host) return;

    ensureStyle();
    hideLegacyDom();

    // if something cleared host after initial mount, rebuild
    const existingRoot = host.querySelector('[data-ceo-chatbox-root="1"]');
    if (existingRoot) return;

    buildUI(host);
  }

  // initial mount
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", mountOrRepair, { once: true });
  } else {
    mountOrRepair();
  }

  // self-heal: if any other script wipes the mount, we restore it
  const heal = () => mountOrRepair();
  setInterval(heal, 900); // light, safe watchdog
})();
