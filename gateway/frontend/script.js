// ====================================================================
// CEO DASHBOARD FRONTEND SCRIPT (V1)
// ====================================================================

const API_BASE = "";

// --- DOM ELEMENTI ---------------------------------------------------
const els = {};

function q(id) {
  return document.getElementById(id);
}

function initDomRefs() {
  els.commandInput = q("ceo-command-input");
  els.sendCommandBtn = q("send-command-btn");
  els.approveLatestBtn = q("approve-latest-btn");
  els.refreshSnapshotBtn = q("refresh-snapshot-btn");
  els.toggleDebugBtn = q("toggle-debug-btn");

  els.voiceToggleBtn = q("voice-toggle-btn");
  els.voiceStatus = q("voice-status");

  els.lastExecutionState = q("last-execution-state");
  els.lastApprovalId = q("last-approval-id");

  els.debugOutput = q("debug-output");

  els.goalsTableBody = q("goals-table-body");
  els.goalsTotalPill = q("goals-total-pill");
  els.goalsActivePill = q("goals-active-pill");

  els.tasksTableBody = q("tasks-table-body");
  els.tasksTotalPill = q("tasks-total-pill");
  els.tasksActivePill = q("tasks-active-pill");

  els.pendingCount = q("pending-count");
  els.approvedTodayCount = q("approved-today-count");
  els.executedTotalCount = q("executed-total-count");
  els.errorsTotalCount = q("errors-total-count");
  els.pendingLabel = q("pending-label");
  els.pendingApprovalsList = q("pending-approvals-list");

  els.weeklyMemory = q("weekly-memory");
  els.footerStatus = q("footer-status");
}

// zadnji approval_id koji je CEO dobio
let lastApprovalId = null;

// --- UTIL -----------------------------------------------------------
function setFooterStatus(text) {
  if (els.footerStatus) {
    els.footerStatus.textContent = text || "";
  }
}

function setDebug(obj) {
  if (!els.debugOutput) return;
  if (!obj) {
    els.debugOutput.textContent = "";
    return;
  }
  els.debugOutput.textContent = JSON.stringify(obj, null, 2);
}

function showError(message) {
  console.error(message);
  setFooterStatus(message);
}

// --- CEO COMMAND: SEND ----------------------------------------------
async function sendCommand() {
  const text = (els.commandInput?.value || "").trim();
  if (!text) {
    showError("Unesi naredbu.");
    return;
  }

  try {
    setFooterStatus("Slanje naredbe...");

    const res = await fetch(`${API_BASE}/api/execute`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    });

    const data = await res.json().catch(() => ({}));

    if (!res.ok) {
      showError(`Greška pri slanju naredbe: ${data.detail || res.status}`);
      setDebug(data);
      return;
    }

    lastApprovalId = data.approval_id || null;

    if (els.lastExecutionState) {
      els.lastExecutionState.textContent =
        data.execution_state || data.status || "UNKNOWN";
    }
    if (els.lastApprovalId) {
      els.lastApprovalId.textContent = lastApprovalId || "–";
    }

    setDebug(data);
    setFooterStatus("Naredba registrirana (BLOCKED). Čeka odobrenje.");

    // osvježi pipeline i snapshot
    await refreshSnapshot();
  } catch (err) {
    console.error(err);
    showError("Neuspješno slanje naredbe (network error).");
  }
}

// --- CEO COMMAND: APPROVE LATEST ------------------------------------
async function approveLatest() {
  try {
    setFooterStatus("Tražim zadnji pending zahtjev...");

    // 1) ako imamo zadnji approval_id iz sendCommand, probaj prvo to
    let approvalIdToUse = lastApprovalId;

    // 2) ako nemamo, fallback: uzmi zadnji iz pending liste
    if (!approvalIdToUse) {
      const pendingRes = await fetch(`${API_BASE}/api/ai-ops/approval/pending`);
      const pendingData = await pendingRes.json().catch(() => ({}));

      const list =
        pendingData.pending ||
        pendingData.approvals ||
        pendingData ||
        [];

      if (!Array.isArray(list) || list.length === 0) {
        showError("Nema pending zahtjeva za odobravanje.");
        return;
      }

      const last = list[list.length - 1];
      approvalIdToUse = last.approval_id || last.id;

      if (!approvalIdToUse) {
        showError("Ne mogu pronaći approval_id za zadnji zahtjev.");
        return;
      }
    }

    setFooterStatus(`Odobravam zahtjev ${approvalIdToUse}...`);

    const res = await fetch(`${API_BASE}/api/ai-ops/approval/approve`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ approval_id: approvalIdToUse }),
    });

    const data = await res.json().catch(() => ({}));

    if (!res.ok) {
      showError(
        `Greška pri odobravanju: ${data.detail || data.message || res.status}`
      );
      setDebug(data);
      return;
    }

    if (els.lastExecutionState) {
      els.lastExecutionState.textContent =
        data.execution_state || data.status || "APPROVED";
    }

    setDebug(data);
    setFooterStatus(
      `Zahtjev ${approvalIdToUse} odobren. Stanje: ${data.execution_state ||
        data.status ||
        "N/A"}`
    );

    // nakon odobrenja osvježi snapshot (goals/tasks/pipeline)
    await refreshSnapshot();
  } catch (err) {
    console.error(err);
    showError("Neuspješno odobravanje (network error).");
  }
}

// --- SNAPSHOT RENDER ------------------------------------------------
function renderGoals(summary) {
  if (!els.goalsTableBody) return;

  const tbody = els.goalsTableBody;
  tbody.innerHTML = "";

  if (!summary) {
    tbody.innerHTML =
      '<tr><td colspan="4" class="placeholder-text">Nema ciljeva u snapshotu.</td></tr>';
    if (els.goalsTotalPill) els.goalsTotalPill.textContent = "Ukupno: 0";
    if (els.goalsActivePill) els.goalsActivePill.textContent = "Aktivni: 0";
    return;
  }

  const items =
    summary.items ||
    summary.rows ||
    summary.goals ||
    [];

  if (!Array.isArray(items) || items.length === 0) {
    tbody.innerHTML =
      '<tr><td colspan="4" class="placeholder-text">Nema ciljeva u snapshotu.</td></tr>';
  } else {
    for (const g of items) {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td>${g.name || g.title || "—"}</td>
        <td>${g.status || "—"}</td>
        <td>${g.priority || "—"}</td>
        <td>${g.deadline || g.due_date || "—"}</td>
      `;
      tbody.appendChild(tr);
    }
  }

  if (els.goalsTotalPill) {
    const total = summary.total ?? items.length ?? 0;
    els.goalsTotalPill.textContent = `Ukupno: ${total}`;
  }
  if (els.goalsActivePill) {
    const active = summary.active_count ?? summary.active ?? 0;
    els.goalsActivePill.textContent = `Aktivni: ${active}`;
  }
}

function renderTasks(summary) {
  if (!els.tasksTableBody) return;

  const tbody = els.tasksTableBody;
  tbody.innerHTML = "";

  if (!summary) {
    tbody.innerHTML =
      '<tr><td colspan="4" class="placeholder-text">Nema taskova u snapshotu.</td></tr>';
    if (els.tasksTotalPill) els.tasksTotalPill.textContent = "Ukupno: 0";
    if (els.tasksActivePill) els.tasksActivePill.textContent = "Aktivni: 0";
    return;
  }

  const items =
    summary.items ||
    summary.rows ||
    summary.tasks ||
    [];

  if (!Array.isArray(items) || items.length === 0) {
    tbody.innerHTML =
      '<tr><td colspan="4" class="placeholder-text">Nema taskova u snapshotu.</td></tr>';
  } else {
    for (const t of items) {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td>${t.name || t.title || "—"}</td>
        <td>${t.status || "—"}</td>
        <td>${t.priority || "—"}</td>
        <td>${t.due_date || t.deadline || "—"}</td>
      `;
      tbody.appendChild(tr);
    }
  }

  if (els.tasksTotalPill) {
    const total = summary.total ?? items.length ?? 0;
    els.tasksTotalPill.textContent = `Ukupno: ${total}`;
  }
  if (els.tasksActivePill) {
    const active = summary.active_count ?? summary.active ?? 0;
    els.tasksActivePill.textContent = `Aktivni: ${active}`;
  }
}

function renderApprovals(approvals) {
  if (!approvals || !els.pendingCount) return;

  const pendingCount = approvals.pending_count ?? 0;
  const completedCount = approvals.completed_count ?? 0;
  const approvedCount = approvals.approved_count ?? 0;
  const failedCount = approvals.failed_count ?? approvals.rejected_count ?? 0;
  const pendingList = approvals.pending || [];

  els.pendingCount.textContent = pendingCount;
  els.executedTotalCount.textContent = completedCount;
  els.approvedTodayCount.textContent = approvedCount;
  els.errorsTotalCount.textContent = failedCount;

  if (els.pendingLabel) {
    els.pendingLabel.textContent =
      pendingCount > 0 ? `${pendingCount} pending` : "Nema pending zahtjeva";
  }

  if (!els.pendingApprovalsList) return;

  const ul = els.pendingApprovalsList;
  ul.innerHTML = "";

  if (!Array.isArray(pendingList) || pendingList.length === 0) {
    ul.innerHTML =
      '<li class="placeholder-text">Trenutno nema zahtjeva na čekanju.</li>';
    return;
  }

  for (const a of pendingList) {
    const li = document.createElement("li");
    const cmd = a.command || {};
    const cmdName = cmd.command || "cmd";
    const intent = cmd.intent || "intent";

    li.innerHTML = `
      <div class="pipeline-item-title">${cmdName}</div>
      <div class="pipeline-item-meta">
        <span>ID: ${a.approval_id || "?"}</span>
        <span>Intent: ${intent}</span>
      </div>
    `;
    ul.appendChild(li);
  }
}

// Weekly memory – za sada placeholder (može se kasnije vezati na Notion)
function renderWeeklyMemory(snapshot) {
  if (!els.weeklyMemory) return;

  els.weeklyMemory.innerHTML =
    '<p class="placeholder-text">Nema sačuvanih prioriteta za ovu sedmicu.</p>';
}

// --- SNAPSHOT FETCH -------------------------------------------------
async function refreshSnapshot() {
  try {
    const res = await fetch(`${API_BASE}/api/ceo/console/snapshot`);
    const data = await res.json().catch(() => ({}));

    if (!res.ok) {
      showError(`Greška pri snapshotu: ${data.detail || res.status}`);
      return;
    }

    renderGoals(data.goals_summary || null);
    renderTasks(data.tasks_summary || null);
    renderApprovals(data.approvals || null);
    renderWeeklyMemory(data);

    if (data.system && data.system.version) {
      setFooterStatus(
        `Snapshot OK · Verzija: ${data.system.version} · Last sync: ${
          data.knowledge_snapshot?.last_sync || "n/a"
        }`
      );
    } else {
      setFooterStatus("Snapshot OK.");
    }
  } catch (err) {
    console.error(err);
    showError("Neuspješno učitavanje snapshota (network error).");
  }
}

// --- VOICE ----------------------------------------------------------
let recognition = null;
let isListening = false;

function setupVoice() {
  const SpeechRecognition =
    window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SpeechRecognition) {
    if (els.voiceStatus) {
      els.voiceStatus.textContent = "Browser ne podržava voice.";
    }
    return;
  }

  recognition = new SpeechRecognition();
  recognition.lang = "bs-BA";
  recognition.continuous = false;
  recognition.interimResults = false;

  recognition.onstart = () => {
    isListening = true;
    if (els.voiceStatus) els.voiceStatus.textContent = "Slušam...";
  };

  recognition.onend = () => {
    isListening = false;
    if (els.voiceStatus) els.voiceStatus.textContent = "Glasovno upravljanje spremno.";
  };

  recognition.onerror = () => {
    isListening = false;
    if (els.voiceStatus) els.voiceStatus.textContent = "Greška u voice modu.";
  };

  recognition.onresult = (event) => {
    const text = event.results[0][0].transcript;
    if (els.commandInput) {
      els.commandInput.value = text;
      els.commandInput.focus();
    }
  };
}

function toggleVoice() {
  if (!recognition) return;
  if (isListening) {
    recognition.stop();
  } else {
    recognition.start();
  }
}

// --- INIT -----------------------------------------------------------
function initEvents() {
  if (els.sendCommandBtn) {
    els.sendCommandBtn.addEventListener("click", sendCommand);
  }
  if (els.approveLatestBtn) {
    els.approveLatestBtn.addEventListener("click", approveLatest);
  }
  if (els.refreshSnapshotBtn) {
    els.refreshSnapshotBtn.addEventListener("click", refreshSnapshot);
  }
  if (els.toggleDebugBtn) {
    els.toggleDebugBtn.addEventListener("click", () => {
      if (!els.debugOutput) return;
      els.debugOutput.classList.toggle("hidden");
    });
  }
  if (els.voiceToggleBtn) {
    els.voiceToggleBtn.addEventListener("click", toggleVoice);
  }
}

document.addEventListener("DOMContentLoaded", () => {
  initDomRefs();
  initEvents();
  setupVoice();
  refreshSnapshot();

  // periodično osvježavanje cjevovoda/snapshot-a
  setInterval(refreshSnapshot, 15000);
});
