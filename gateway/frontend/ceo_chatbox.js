// gateway/frontend/ceo_chatbox.js
(function () {
  // Pokreni tek kad je DOM sigurno spreman
  function boot() {
    try {
      // Guard: ako je već mountano, ne diraj
      if (window.__CEO_CHATBOX_APP__) return;
      window.__CEO_CHATBOX_APP__ = true;

      const cfg = (window.__EVO_UI__ = window.__EVO_UI__ || {});
      const mountSelector = cfg.mountSelector || "#ceo-left-panel";
      const ceoCommandUrl = cfg.ceoCommandUrl || "/ceo/command";
      const approveUrl = cfg.approveUrl || "/api/ai-ops/approval/approve";
      const headers = Object.assign(
        { "Content-Type": "application/json" },
        cfg.headers || {}
      );

      const host = document.querySelector(mountSelector);
      if (!host) {
        console.error("[CEO_CHATBOX] mount not found:", mountSelector);
        return;
      }

      // 1) HARD-HIDE: sakrij sve što je u istoj ceo-chat-panel sekciji osim mount-a
      // Ovo garantuje da legacy UI nestane, bez obzira na ID mismatch/rename.
      const panel = host.closest(".ceo-chat-panel") || host.parentElement;
      if (panel) {
        Array.from(panel.children).forEach((child) => {
          if (child !== host) child.style.display = "none";
        });
      }

      // 2) Forciraj da mount ima visinu (da se chatbox vidi)
      host.style.display = "block";
      host.style.width = "100%";
      host.style.minHeight = "520px";
      host.style.height = "calc(100vh - 260px)"; // dovoljno za sticky composer

      // 3) CSS (ChatGPT-like)
      const style = document.createElement("style");
      style.textContent = `
        .ceo-chatbox { display:flex; flex-direction:column; height: 100%; }
        .ceo-chatbox-history {
          flex:1; overflow:auto; padding: 14px;
          border: 1px solid rgba(255,255,255,.10);
          border-radius: 14px;
          background: rgba(0,0,0,.10);
        }
        .ceo-chatbox-row { display:flex; gap:12px; margin: 10px 0; }
        .ceo-chatbox-badge {
          width: 34px; height: 34px; border-radius: 10px;
          display:flex; align-items:center; justify-content:center;
          font-weight: 800; font-size: 12px;
          border: 1px solid rgba(255,255,255,.12);
          background: rgba(255,255,255,.04);
          color: rgba(255,255,255,.90);
          flex: 0 0 auto;
        }
        .ceo-chatbox-msg {
          flex:1;
          white-space: pre-wrap;
          line-height: 1.45;
          font-size: 14px;
          color: rgba(255,255,255,.92);
          padding: 10px 12px;
          border-radius: 12px;
          border: 1px solid rgba(255,255,255,.10);
          background: rgba(0,0,0,.12);
        }
        .ceo-chatbox-msg.ceo { background: rgba(0,0,0,.16); }
        .ceo-chatbox-msg.sys { background: rgba(255,255,255,.06); }

        .ceo-chatbox-meta {
          margin-top: 8px;
          display:flex;
          gap:10px;
          align-items:center;
          flex-wrap: wrap;
        }
        .ceo-chatbox-pill {
          display:inline-flex;
          align-items:center;
          gap:8px;
          padding:6px 10px;
          border-radius:999px;
          border: 1px solid rgba(255,255,255,.12);
          background: rgba(0,0,0,.12);
          color: rgba(255,255,255,.78);
          font-size: 12px;
        }
        .ceo-chatbox-pill strong { color: rgba(255,255,255,.92); font-weight: 800; }

        .ceo-chatbox-composer {
          position: sticky;
          bottom: 0;
          margin-top: 12px;
          border: 1px solid rgba(255,255,255,.10);
          border-radius: 14px;
          background: rgba(0,0,0,.22);
          padding: 10px;
          display:flex;
          gap: 10px;
          align-items: flex-end;
        }
        .ceo-chatbox-textarea {
          flex:1;
          resize:none;
          border: 1px solid rgba(255,255,255,.12);
          border-radius: 12px;
          background: rgba(0,0,0,.20);
          color: rgba(255,255,255,.92);
          padding: 10px 12px;
          line-height: 1.35;
          font-size: 14px;
          max-height: 160px;
          min-height: 44px;
          outline: none;
        }
        .ceo-chatbox-btn {
          border-radius: 12px;
          padding: 10px 12px;
          border: 1px solid rgba(255,255,255,.12);
          background: rgba(255,255,255,.08);
          color: rgba(255,255,255,.92);
          font-weight: 800;
          cursor: pointer;
          white-space: nowrap;
        }
        .ceo-chatbox-btn:disabled { opacity: .55; cursor: not-allowed; }
        .ceo-chatbox-btn.primary {
          background: rgba(34,197,94,.18);
          border-color: rgba(34,197,94,.35);
        }
        .ceo-chatbox-typing {
          opacity:.75;
          font-size: 12px;
          margin-top: 8px;
          color: rgba(255,255,255,.68);
        }
      `;
      document.head.appendChild(style);

      // 4) DOM render
      host.innerHTML = "";

      const root = document.createElement("div");
      root.className = "ceo-chatbox";

      const history = document.createElement("div");
      history.className = "ceo-chatbox-history";

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
      approveBtn.textContent = "Odobri zadnji";
      approveBtn.disabled = true;

      composer.appendChild(textarea);
      composer.appendChild(sendBtn);
      composer.appendChild(approveBtn);

      root.appendChild(history);
      root.appendChild(typing);
      root.appendChild(composer);

      host.appendChild(root);

      let lastApprovalId = null;
      let busy = false;

      function scrollToBottom() {
        history.scrollTop = history.scrollHeight;
      }

      function addMessage(role, text, meta) {
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
        scrollToBottom();
      }

      function setBusy(next) {
        busy = next;
        sendBtn.disabled = next;
        textarea.disabled = next;
        typing.style.display = next ? "block" : "none";
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
            addMessage("sys", `Greška: ${res.status}\n${detail || "N/A"}`, {
              state: "ERROR",
            });
            return;
          }

          const data = await res.json();
          lastApprovalId = data.approval_id || null;

          addMessage(
            "sys",
            "Naredba je primljena i prevedena. Zahtjev je u BLOCKED stanju i čeka eksplicitno odobrenje.",
            { state: "BLOCKED", approval_id: lastApprovalId || "–" }
          );

          if (lastApprovalId) approveBtn.disabled = false;

          textarea.value = "";
          autosize();

          // refresh snapshot (desno)
          const snapBtn = document.getElementById("refresh-snapshot-btn");
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
            addMessage(
              "sys",
              `Greška pri odobravanju: ${res.status}\n${detail || ""}`,
              { state: "ERROR" }
            );
            return;
          }

          addMessage(
            "sys",
            "Zahtjev je odobren. Execution će biti vidljiv kroz snapshot/metrike (bez prikaza agent detalja).",
            { state: "APPROVED/EXECUTED", approval_id: lastApprovalId }
          );

          approveBtn.disabled = true;

          const snapBtn = document.getElementById("refresh-snapshot-btn");
          if (snapBtn) snapBtn.click();
        } catch (err) {
          addMessage("sys", "Greška pri odobravanju zahtjeva.", { state: "ERROR" });
        } finally {
          setBusy(false);
        }
      }

      sendBtn.addEventListener("click", sendCommand);
      approveBtn.addEventListener("click", approveLatest);

      addMessage(
        "sys",
        "Dobrodošli u CEO Command. CEO → SYSTEM kanal: unos prirodnog jezika, bez implicitnog izvršavanja. Tok: BLOCKED → APPROVAL → EXECUTED.",
        { state: "WHOLE" }
      );

      setTimeout(() => textarea.focus(), 50);

      console.log("[CEO_CHATBOX] mounted", {
        mountSelector,
        ceoCommandUrl,
        approveUrl,
      });
    } catch (e) {
      console.error("[CEO_CHATBOX] init failed", e);
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
