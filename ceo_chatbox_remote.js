// gateway/frontend/ceo_chatbox.js
(function () {
  try {
    if (window.__CEO_CHATBOX_APP__) return;
    window.__CEO_CHATBOX_APP__ = true;

    const cfg = (window.__EVO_UI__ = window.__EVO_UI__ || {});
    const mountSelector = cfg.mountSelector || "#ceo-left-panel";

    // CHAT (LLM) endpoint (READ/PROPOSE ONLY backend-side)
    const chatUrl = cfg.chatUrl || "/api/chat";

    // EXECUTION (approval-gated) endpoints
    const executeRawUrl = cfg.executeRawUrl || "/api/execute/raw";
    const approveUrl = cfg.approveUrl || "/api/ai-ops/approval/approve";

    const headers = Object.assign({ "Content-Type": "application/json" }, cfg.headers || {});
    const host = document.querySelector(mountSelector);
    if (!host) return;

    // Hide legacy UI
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

    // CSS
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

      .ceo-proposals { margin-top: 10px; border-top: 1px dashed rgba(255,255,255,.12); padding-top: 10px; }
      .ceo-proposals-title { font-size: 12px; opacity: .85; margin-bottom: 8px; }
      .ceo-proposal-item {
        display:flex; gap:10px; align-items:flex-start;
        padding: 8px 10px; border-radius: 12px;
        border: 1px solid rgba(255,255,255,.10);
        background: rgba(0,0,0,.10);
        margin: 8px 0;
      }
      .ceo-proposal-radio { margin-top: 3px; }
      .ceo-proposal-body { flex:1; }
      .ceo-proposal-label { font-size: 12px; font-weight: 700; opacity: .92; margin-bottom: 6px; }
      .ceo-proposal-json { font-size: 11px; opacity: .85; white-space: pre-wrap; word-break: break-word; }
    `;
    document.head.appendChild(style);

    // DOM
    host.innerHTML = "";
    const root = document.createElement("div");
    root.className = "ceo-chatbox";

    const history = document.createElement("div");
    history.className = "ceo-chatbox-history";

    const typing = document.createElement("div");
    typing.className = "ceo-chatbox-typing";
    typing.style.display = "none";
    typing.textContent = "SYSTEM obrađuje…";

    const composer = document.createElement("div");
    composer.className = "ceo-chatbox-composer";

    const textarea = document.createElement("textarea");
    textarea.className = "ceo-chatbox-textarea";
    textarea.placeholder = 'Chat ili komanda. Primjeri:\n- "Ko si ti?"\n- "Kreiraj cilj ..."';

    const sendBtn = document.createElement("button");
    sendBtn.className = "ceo-chatbox-btn primary";
    sendBtn.type = "button";
    sendBtn.textContent = "Pošalji";

    const approveBtn = document.createElement("button");
    approveBtn.className = "ceo-chatbox-btn";
    approveBtn.type = "button";
    approveBtn.textContent = "Kreiraj execution (BLOCKED)";
    approveBtn.disabled = true;

    composer.appendChild(textarea);
    composer.appendChild(sendBtn);
    composer.appendChild(approveBtn);

    root.appendChild(history);
    root.appendChild(typing);
    root.appendChild(composer);
    host.appendChild(root);

    let pending = 0;

    // Source-of-truth state (MUST be reset on each chat submit)
    let lastChatProposals = [];
    let selectedProposalIndex = -1;

    // Approval-gated state for the currently selected proposal (exactly one)
    let pendingApprovalId = null;
    let pendingExecutionId = null;

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

    function resetProposalState() {
      lastChatProposals = [];
      selectedProposalIndex = -1;
      pendingApprovalId = null;
      pendingExecutionId = null;
      approveBtn.disabled = true;
      approveBtn.textContent = "Kreiraj execution (BLOCKED)";
    }

    function renderProposals() {
      // remove existing proposals panel if present
      const existing = history.querySelector(".ceo-proposals");
      if (existing) existing.remove();

      if (!Array.isArray(lastChatProposals) || lastChatProposals.length === 0) return;

      const panel = document.createElement("div");
      panel.className = "ceo-proposals";

      const title = document.createElement("div");
      title.className = "ceo-proposals-title";
      title.textContent = "Predložene akcije (odaberi tačno jednu):";
      panel.appendChild(title);

      lastChatProposals.forEach((p, idx) => {
        const item = document.createElement("div");
        item.className = "ceo-proposal-item";

        const radio = document.createElement("input");
        radio.type = "radio";
        radio.name = "ceo_proposal_select";
        radio.className = "ceo-proposal-radio";
        radio.checked = idx === selectedProposalIndex;
        radio.addEventListener("change", () => {
          selectedProposalIndex = idx;
          // Selecting a different proposal invalidates any pending approval state
          pendingApprovalId = null;
          pendingExecutionId = null;
          approveBtn.textContent = "Kreiraj execution (BLOCKED)";
          approveBtn.disabled = selectedProposalIndex < 0;
          renderProposals();
        });

        const body = document.createElement("div");
        body.className = "ceo-proposal-body";

        const label = document.createElement("div");
        label.className = "ceo-proposal-label";
        label.textContent = `Proposal #${idx + 1}`;

        const json = document.createElement("div");
        json.className = "ceo-proposal-json";
        try {
          json.textContent = JSON.stringify(p, null, 2);
        } catch (_) {
          json.textContent = String(p);
        }

        body.appendChild(label);
        body.appendChild(json);

        item.appendChild(radio);
        item.appendChild(body);

        panel.appendChild(item);
      });

      history.appendChild(panel);
      scrollToBottom();
    }

    function getSelectedProposal() {
      if (!Array.isArray(lastChatProposals)) return null;
      if (selectedProposalIndex < 0 || selectedProposalIndex >= lastChatProposals.length) return null;
      return lastChatProposals[selectedProposalIndex];
    }

    async function createExecutionBlockedFromSelectedProposal() {
      const proposal = getSelectedProposal();
      if (!proposal) {
        addMessage("sys", "Nije odabran nijedan proposal.", { state: "ERROR" });
        return;
      }

      bumpPending(+1);
      try {
        const executeRes = await fetch(executeRawUrl, {
          method: "POST",
          headers,
          // CANON: execute/raw payload MUST be exactly the selected proposal object
          body: JSON.stringify(proposal),
        });

        if (!executeRes.ok) {
          const detail = await executeRes.text();
          addMessage("sys", `Greška (execute/raw): ${executeRes.status}\n${detail || ""}`, { state: "ERROR" });
          return;
        }

        const execData = await executeRes.json();
        const approvalId = execData.approval_id || execData.approvalId || null;
        const executionId = execData.execution_id || execData.executionId || null;
        const state = execData.state || execData.execution_state || "BLOCKED";

        pendingApprovalId = approvalId;
        pendingExecutionId = executionId;

        addMessage("sys", "Execution kreiran i čeka odobrenje (BLOCKED).", {
          state: state || "BLOCKED",
          approval_id: approvalId || "–",
          execution_id: executionId || "–",
        });

        if (!approvalId) {
          addMessage("sys", "Nedostaje approval_id iz /api/execute/raw.", { state: "ERROR" });
          return;
        }

        // Step 2 is now available
        approveBtn.textContent = "Potvrdi odobrenje (EXECUTE)";
        approveBtn.disabled = false;
      } catch (err) {
        addMessage("sys", "Greška pri execute/raw toku.", { state: "ERROR" });
      } finally {
        bumpPending(-1);
      }
    }

    async function approvePendingApproval() {
      if (!pendingApprovalId) {
        addMessage("sys", "Nema pending approval_id. Prvo kreiraj execution (BLOCKED).", { state: "ERROR" });
        return;
      }

      approveBtn.disabled = true;
      bumpPending(+1);

      try {
        const approveRes = await fetch(approveUrl, {
          method: "POST",
          headers,
          body: JSON.stringify({ approval_id: pendingApprovalId }),
        });

        if (!approveRes.ok) {
          const detail = await approveRes.text();
          addMessage("sys", `Greška (approve): ${approveRes.status}\n${detail || ""}`, {
            state: "ERROR",
            approval_id: pendingApprovalId,
          });
          approveBtn.disabled = false;
          return;
        }

        const approveData = await approveRes.json();
        const finalState = approveData.execution_state || approveData.state || approveData.status || "COMPLETED";

        addMessage("sys", "Odobreno i izvršeno kroz execution pipeline.", {
          state: finalState,
          approval_id: pendingApprovalId,
          execution_id: pendingExecutionId || approveData.execution_id || "–",
        });

        const snapBtn = document.getElementById("refresh-snapshot-btn");
        if (snapBtn) snapBtn.click();

        // Clear state after completion
        resetProposalState();
        renderProposals();
      } catch (err) {
        addMessage("sys", "Greška pri approve toku.", { state: "ERROR" });
        approveBtn.disabled = false;
      } finally {
        bumpPending(-1);
      }
    }

    async function onApproveClick() {
      // CANON: Exactly one proposal, approval-gated, 2-step
      if (pendingApprovalId) {
        await approvePendingApproval();
      } else {
        await createExecutionBlockedFromSelectedProposal();
      }
    }

    async function sendMessage() {
      const text = (textarea.value || "").trim();
      if (!text) return;

      addMessage("ceo", text);

      textarea.value = "";
      autosize();

      // IMPORTANT: reset proposals + approval state on each new chat submit
      resetProposalState();
      renderProposals();

      bumpPending(+1);
      try {
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
        addMessage("sys", (data && data.text) || "(no text)", { state: "CHAT" });

        const proposals = Array.isArray(data.proposed_commands) ? data.proposed_commands : [];
        if (proposals.length > 0) {
          // Source-of-truth: last /api/chat proposals only
          lastChatProposals = proposals;
          selectedProposalIndex = 0; // default: first proposal selected
          approveBtn.disabled = false;
          approveBtn.textContent = "Kreiraj execution (BLOCKED)";

          addMessage("sys", "Predložene su akcije koje zahtijevaju odobrenje.", {
            state: "PROPOSALS_READY",
            count: proposals.length,
          });

          renderProposals();
        }

        const snapBtn = document.getElementById("refresh-snapshot-btn");
        if (snapBtn) snapBtn.click();
      } catch (err) {
        addMessage("sys", "Greška pri chat pozivu.", { state: "ERROR" });
      } finally {
        bumpPending(-1);
      }
    }

    sendBtn.addEventListener("click", sendMessage);
    approveBtn.addEventListener("click", onApproveClick);

    addMessage(
      "sys",
      "CEO Chatbox (CANON): chat ide na /api/chat (read-only). LLM vraća proposed_commands. CEO odabere TAČNO JEDAN proposal → (1) kreira execution BLOCKED (/api/execute/raw) → (2) potvrdi odobrenje (/api/ai-ops/approval/approve).",
      { state: "READY" }
    );

    setTimeout(() => textarea.focus(), 50);

    console.log("[CEO_CHATBOX] mounted", { mountSelector, chatUrl, executeRawUrl, approveUrl });
  } catch (e) {
    console.error("[CEO_CHATBOX] init failed", e);
  }
})();
