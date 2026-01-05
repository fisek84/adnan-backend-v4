// gateway/frontend/ceo_chatbox.js
(function () {
  try {
    // Guard: ako je već mountano, ne diraj
    if (window.__CEO_CHATBOX_APP__) return;
    window.__CEO_CHATBOX_APP__ = true;

    const cfg = (window.__EVO_UI__ = window.__EVO_UI__ || {});
    const mountSelector = cfg.mountSelector || "#ceo-left-panel";

    // CHAT (LLM) endpoint
    const chatUrl = cfg.chatUrl || "/api/chat";

    // EXECUTION (approval-gated) endpoints
    const executeRawUrl = cfg.executeRawUrl || "/api/execute/raw";
    const approveUrl = cfg.approveUrl || "/api/ai-ops/approval/approve";

    const headers = Object.assign({ "Content-Type": "application/json" }, cfg.headers || {});
    const host = document.querySelector(mountSelector);
    if (!host) return;

    // Sakrij legacy dio (ali ga NE brišemo da script.js ne pukne)
    const legacy = [
      document.getElementById("ceo-history"),
      document.getElementById("ceo-command-input"),
      document.getElementById("send-command-btn"),
      document.getElementById("approve-latest-btn"),
      document.getElementById("refresh-snapshot-btn"),
      document.getElementById("command-status-chip"),
      document.getElementById("command-status-text"),
      document.getElementById("last-execution-state"),
      document.getElementById("last-approval-id"),
    ];
    legacy.forEach((el) => {
      if (el && el.closest) {
        const block =
          el.closest(".chat-input-bar") ||
          el.closest(".command-status") ||
          el.closest(".command-actions-row") ||
          el.closest(".chat-history") ||
          el;
        block.style.display = "none";
      } else if (el) {
        el.style.display = "none";
      }
    });

    // CSS (minimal, ChatGPT-like, uklapa se u dark)
    const style = document.createElement("style");
    style.textContent = `
      .ceo-chatbox { display:flex; flex-direction:column; height: 100%; min-height: 420px; }
      .ceo-chatbox-history {
        flex:1; overflow:auto; padding: 14px; border: 1px solid rgba(255,255,255,.10);
        border-radius: 14px; background: rgba(0,0,0,.10);
      }
      .ceo-chatbox-row { display:flex; gap:12px; margin: 10px 0; }
      .ceo-chatbox-badge {
        width: 34px; height: 34px; border-radius: 10px; display:flex; align-items:center; justify-content:center;
        font-weight: 700; font-size: 12px; border: 1px solid rgba(255,255,255,.12);
        background: rgba(255,255,255,.04); color: rgba(255,255,255,.85); flex: 0 0 auto;
      }
      .ceo-chatbox-msg {
        flex:1; white-space: pre-wrap; line-height: 1.45; font-size: 14px;
        color: rgba(255,255,255,.92); padding: 10px 12px; border-radius: 12px;
        border: 1px solid rgba(255,255,255,.10); background: rgba(0,0,0,.12);
      }
      .ceo-chatbox-msg.ceo { background: rgba(0,0,0,.16); }
      .ceo-chatbox-msg.sys { background: rgba(255,255,255,.06); }
      .ceo-chatbox-meta { margin-top: 8px; display:flex; gap:10px; align-items:center; flex-wrap: wrap; }
      .ceo-chatbox-pill {
        display:inline-flex; align-items:center; gap:8px; padding:6px 10px; border-radius:999px;
        border: 1px solid rgba(255,255,255,.12); background: rgba(0,0,0,.12);
        color: rgba(255,255,255,.78); font-size: 12px;
      }
      .ceo-chatbox-pill strong { color: rgba(255,255,255,.92); font-weight: 700; }
      .ceo-chatbox-composer {
        position: sticky; bottom: 0; margin-top: 12px;
        border: 1px solid rgba(255,255,255,.10); border-radius: 14px; background: rgba(0,0,0,.22);
        padding: 10px; display:flex; gap: 10px; align-items: flex-end;
      }
      .ceo-chatbox-textarea {
        flex:1; resize:none; border: 1px solid rgba(255,255,255,.12);
        border-radius: 12px; background: rgba(0,0,0,.20);
        color: rgba(255,255,255,.92); padding: 10px 12px; line-height: 1.35; font-size: 14px;
        max-height: 160px; min-height: 44px; outline: none;
      }
      .ceo-chatbox-btn {
        border-radius: 12px; padding: 10px 12px; border: 1px solid rgba(255,255,255,.12);
        background: rgba(255,255,255,.08); color: rgba(255,255,255,.92); font-weight: 700;
        cursor: pointer;
      }
      .ceo-chatbox-btn:disabled { opacity: .55; cursor: not-allowed; }
      .ceo-chatbox-btn.primary { background: rgba(34,197,94,.18); border-color: rgba(34,197,94,.35); }
      .ceo-chatbox-typing { opacity:.75; font-size: 12px; margin-top: 8px; color: rgba(255,255,255,.68); }
    `;
    document.head.appendChild(style);

    // DOM
    host.innerHTML = "";
    const root = document.createElement("div");
    root.className = "ceo-chatbox";

    const history = document.createElement("div");
    history.className = "ceo-chatbox-history";

    const composer = document.createElement("div");
    composer.className = "ceo-chatbox-composer";

    const textarea = document.createElement("textarea");
    textarea.className = "ceo-chatbox-textarea";
    textarea.placeholder = 'Piši normalno (chat). Npr: "Ko si ti?", "Šta je prioritet danas?", "Kreiraj cilj ..."';

    const sendBtn = document.createElement("button");
    sendBtn.className = "ceo-chatbox-btn primary";
    sendBtn.type = "button";
    sendBtn.textContent = "Pošalji";

    const approveBtn = document.createElement("button");
    approveBtn.className = "ceo-chatbox-btn";
    approveBtn.type = "button";
    approveBtn.textContent = "Odobri predloženo";
    approveBtn.disabled = true;

    const typing = document.createElement("div");
    typing.className = "ceo-chatbox-typing";
    typing.style.display = "none";
    typing.textContent = "SYSTEM obrađuje…";

    composer.appendChild(textarea);
    composer.appendChild(sendBtn);
    composer.appendChild(approveBtn);

    root.appendChild(history);
    root.appendChild(typing);
    root.appendChild(composer);
    host.appendChild(root);

    // NON-BLOCKING: ne gasimo input/send; samo pokazujemo typing dok ima zahtjeva
    let pending = 0;

    // State for approvals
    let lastProposals = []; // proposals iz /api/chat
    let lastBlocked = []; // { approval_id, execution_id, state }

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

      if (meta && (meta.state || meta.approval_id || meta.execution_id || meta.count)) {
        const metaRow = document.createElement("div");
        metaRow.className = "ceo-chatbox-meta";

        if (meta.state) {
          const pill = document.createElement("span");
          pill.className = "ceo-chatbox-pill";
          pill.innerHTML = `<strong>Status:</strong> ${meta.state}`;
          metaRow.appendChild(pill);
        }
        if (typeof meta.count === "number") {
          const pill = document.createElement("span");
          pill.className = "ceo-chatbox-pill";
          pill.innerHTML = `<strong>proposals:</strong> ${meta.count}`;
          metaRow.appendChild(pill);
        }
        if (meta.execution_id) {
          const pill = document.createElement("span");
          pill.className = "ceo-chatbox-pill";
          pill.innerHTML = `<strong>execution_id:</strong> ${meta.execution_id}`;
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

    function setTyping(on) {
      typing.style.display = on ? "block" : "none";
    }

    function bumpPending(delta) {
      pending = Math.max(0, pending + delta);
      setTyping(pending > 0);
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

    // ---- Canon mapping helpers ----

    function proposalToAiCommand(proposal) {
      if (!proposal || typeof proposal !== "object") return null;

      // A) preferred: proposal.args.ai_command
      if (proposal.args && proposal.args.ai_command && typeof proposal.args.ai_command === "object") {
        const ai = proposal.args.ai_command;
        return {
          command: ai.command || ai.intent || null,
          intent: ai.intent || ai.command || null,
          params: ai.params || {},
        };
      }

      // A alt: proposal.args.command/intent/params
      if (proposal.args && (proposal.args.command || proposal.args.intent)) {
        return {
          command: proposal.args.command || proposal.args.intent || null,
          intent: proposal.args.intent || proposal.args.command || null,
          params: proposal.args.params || proposal.args.payload || {},
        };
      }

      // B) legacy: proposal.command_type + proposal.payload
      if (proposal.command_type) {
        return {
          command: proposal.command_type,
          intent: proposal.command_type,
          params: proposal.payload || {},
        };
      }

      return null;
    }

    function buildExecuteRawPayload(aiCommand) {
      return {
        command: aiCommand.command,
        intent: aiCommand.intent,
        params: aiCommand.params || {},
        initiator: "ceo",
        read_only: false,
        metadata: {
          source: "ceoChatbox",
          canon: "CEO_CONSOLE_APPROVAL_GATED_EXECUTION",
        },
      };
    }

    // ---- Chat (LLM) ----

    async function sendMessage() {
      const text = (textarea.value || "").trim();
      if (!text) return;

      addMessage("ceo", text);

      // clear immediately (non-blocking UX)
      textarea.value = "";
      autosize();

      // reset proposals UI state
      approveBtn.disabled = true;
      lastProposals = [];
      lastBlocked = [];

      bumpPending(+1);
      try {
        // KRITIČNO: bez metadata.canon u /api/chat
        const body = {
          message: text,
          preferred_agent_id: "ceo_advisor",
          metadata: {
            initiator: "ceo_dashboard",
            source: "ceoChatbox",
          },
        };

        const res = await fetch(chatUrl, {
          method: "POST",
          headers,
          body: JSON.stringify(body),
        });

        if (!res.ok) {
          const detail = await res.text();
          addMessage("sys", `Greška (chat): ${res.status}\n${detail || "N/A"}`, { state: "ERROR" });
          return;
        }

        const data = await res.json();

        // normal chat odgovor
        addMessage("sys", (data && data.text) || "(no text)", { state: "CHAT" });

        // proposals (ako ih ima)
        const proposals = Array.isArray(data.proposed_commands) ? data.proposed_commands : [];
        if (proposals.length > 0) {
          lastProposals = proposals;
          approveBtn.disabled = false;
          addMessage("sys", "Predložene su akcije koje zahtijevaju odobrenje.", {
            state: "PROPOSALS_READY",
            count: proposals.length,
          });
        }

        // optional: refresh snapshot desno (ako postoji)
        const snapBtn = document.getElementById("refresh-snapshot-btn");
        if (snapBtn) snapBtn.click();
      } catch (err) {
        addMessage("sys", "Greška pri chat pozivu.", { state: "ERROR" });
      } finally {
        bumpPending(-1);
      }
    }

    // ---- Approve & Execute (explicit click) ----

    async function approveProposals() {
      if (!Array.isArray(lastProposals) || lastProposals.length === 0) return;

      // eksplicitna akcija CEO-a
      approveBtn.disabled = true;

      for (let i = 0; i < lastProposals.length; i++) {
        const p = lastProposals[i];
        const ai = proposalToAiCommand(p);

        if (!ai || !ai.command || !ai.intent) {
          addMessage("sys", `Nevalidan proposal (index ${i}).`, { state: "ERROR" });
          continue;
        }

        bumpPending(+1);
        try {
          // 1) Create Approval (BLOCKED): /api/execute/raw
          const executeRes = await fetch(executeRawUrl, {
            method: "POST",
            headers,
            body: JSON.stringify(buildExecuteRawPayload(ai)),
          });

          if (!executeRes.ok) {
            const detail = await executeRes.text();
            addMessage("sys", `Greška (execute/raw): ${executeRes.status}\n${detail || ""}`, { state: "ERROR" });
            continue;
          }

          const execData = await executeRes.json();
          const approvalId = execData.approval_id || execData.approvalId || null;
          const executionId = execData.execution_id || execData.executionId || null;
          const state = execData.state || execData.execution_state || "BLOCKED";

          lastBlocked.push({ approval_id: approvalId, execution_id: executionId, state });

          addMessage("sys", "Zahtjev registrovan (BLOCKED) i čeka odobrenje.", {
            state: "BLOCKED",
            approval_id: approvalId || "–",
            execution_id: executionId || "–",
          });

          if (!approvalId) {
            addMessage("sys", "Nedostaje approval_id iz /api/execute/raw.", { state: "ERROR" });
            continue;
          }

          // 2) Approve & Execute: /api/ai-ops/approval/approve
          const approveRes = await fetch(approveUrl, {
            method: "POST",
            headers,
            body: JSON.stringify({ approval_id: approvalId }),
          });

          if (!approveRes.ok) {
            const detail = await approveRes.text();
            addMessage("sys", `Greška (approve): ${approveRes.status}\n${detail || ""}`, {
              state: "ERROR",
              approval_id: approvalId,
            });
            continue;
          }

          const approveData = await approveRes.json();
          const finalState =
            approveData.execution_state || approveData.state || approveData.status || "APPROVED/EXECUTED";

          addMessage("sys", "Odobreno i poslano u execution pipeline.", {
            state: finalState,
            approval_id: approvalId,
            execution_id: executionId || approveData.execution_id || "–",
          });

          // refresh snapshot desno
          const snapBtn = document.getElementById("refresh-snapshot-btn");
          if (snapBtn) snapBtn.click();
        } catch (err) {
          addMessage("sys", "Greška pri approval/execution toku.", { state: "ERROR" });
        } finally {
          bumpPending(-1);
        }
      }

      // clear proposals after processing
      lastProposals = [];
    }

    sendBtn.addEventListener("click", sendMessage);
    approveBtn.addEventListener("click", approveProposals);

    // Initial system message
    addMessage(
      "sys",
      "CEO Chat je aktivan (LLM). Ako agent predloži akcije (side-effects), pojaviće se dugme 'Odobri predloženo'. Chat ne šalje canon lock.",
      { state: "READY" }
    );

    // Focus input
    setTimeout(() => textarea.focus(), 50);

    console.log("[CEO_CHATBOX] mounted", { mountSelector, chatUrl, executeRawUrl, approveUrl });
  } catch (e) {
    console.error("[CEO_CHATBOX] init failed", e);
  }
})();
