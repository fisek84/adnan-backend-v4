// gateway/frontend/script.js

let lastApprovalId = null;

function $(id) {
  return document.getElementById(id);
}

function setCommandStatus(chipText, text, variant) {
  const chip = $("command-status-chip");
  const label = $("command-status-text");
  if (!chip || !label) return;

  chip.textContent = chipText || "";
  label.textContent = text || "";

  if (variant === "error") {
    chip.style.background = "rgba(127,29,29,0.5)";
    chip.style.borderColor = "rgba(248,113,113,0.9)";
  } else {
    chip.style.background = "";
    chip.style.borderColor = "";
  }
}

function appendHistoryMessage(role, text) {
  const history = $("ceo-history");
  if (!history) return null;

  const placeholder = history.querySelector(".history-placeholder");
  if (placeholder) placeholder.remove();

  const msg = document.createElement("div");
  msg.classList.add("conv-message");
  if (role === "user") msg.classList.add("conv-user");
  else msg.classList.add("conv-system");

  msg.textContent = text;
  history.appendChild(msg);
  history.scrollTop = history.scrollHeight;
  return msg;
}

// --------------------------------------------------
// SNAPSHOT
// --------------------------------------------------
async function loadSnapshot() {
  try {
    const res = await fetch("/ceo/console/snapshot");
    if (!res.ok) throw new Error(`Snapshot HTTP ${res.status}`);
    const data = await res.json();

    const osPill = $("os-status-pill");
    if (osPill) {
      const bootReady = data.system?.boot_ready;
      const osEnabled = data.system?.os_enabled;
      if (osEnabled && bootReady) {
        osPill.textContent = "OS ONLINE";
        osPill.classList.add("status-pill-online");
      } else {
        osPill.textContent = "OS OFFLINE";
        osPill.classList.remove("status-pill-online");
      }
    }

    const approvals = data.approvals || {};
    const pending = $("pending-count-pill");
    const approvedToday = $("approved-today-pill");
    const executedTotal = $("executed-total-pill");
    const errorsTotal = $("errors-total-pill");

    if (pending) pending.textContent = approvals.pending_count ?? 0;
    if (approvedToday) approvedToday.textContent = approvals.approved_count ?? 0;
    if (executedTotal) executedTotal.textContent = approvals.completed_count ?? 0;
    if (errorsTotal) errorsTotal.textContent =
      (approvals.failed_count ?? 0) + (approvals.rejected_count ?? 0);

    renderGoals(data.goals_summary);
    renderTasks(data.tasks_summary);

    const lastSync = data.knowledge_snapshot?.last_sync || "n/a";
    const footer = $("footer-status");
    if (footer) footer.textContent = `Last sync: ${lastSync}`;
  } catch (err) {
    console.error("Failed to load snapshot", err);
    renderGoals(null, "Greška pri učitavanju ciljeva.");
    renderTasks(null, "Greška pri učitavanju taskova.");
  }
}

function renderGoals(goals, errorMsg) {
  const tbody = $("goals-table-body");
  if (!tbody) return;

  tbody.innerHTML = "";

  if (errorMsg) {
    const tr = document.createElement("tr");
    const td = document.createElement("td");
    td.colSpan = 4;
    td.className = "placeholder-text";
    td.textContent = errorMsg;
    tr.appendChild(td);
    tbody.appendChild(tr);
    return;
  }

  if (!goals || !goals.length) {
    const tr = document.createElement("tr");
    const td = document.createElement("td");
    td.colSpan = 4;
    td.className = "placeholder-text";
    td.textContent = "Nema ciljeva u snapshotu.";
    tr.appendChild(td);
    tbody.appendChild(tr);
    return;
  }

  const totalPill = $("goals-total-pill");
  const activePill = $("goals-active-pill");
  if (totalPill) totalPill.textContent = `Ukupno: ${goals.length}`;
  if (activePill) activePill.textContent = `Aktivni: ${
    goals.filter((g) => String(g.status || "").toLowerCase().includes("aktiv")).length
  }`;

  for (const g of goals) {
    const tr = document.createElement("tr");
    const cols = [
      g.name ?? g.title ?? "(bez naziva)",
      g.status ?? "-",
      g.priority ?? "-",
      g.due_date ?? g.deadline ?? "-",
    ];
    for (const c of cols) {
      const td = document.createElement("td");
      td.textContent = c;
      tr.appendChild(td);
    }
    tbody.appendChild(tr);
  }
}

function renderTasks(tasks, errorMsg) {
  const tbody = $("tasks-table-body");
  if (!tbody) return;

  tbody.innerHTML = "";

  if (errorMsg) {
    const tr = document.createElement("tr");
    const td = document.createElement("td");
    td.colSpan = 4;
    td.className = "placeholder-text";
    td.textContent = errorMsg;
    tr.appendChild(td);
    tbody.appendChild(tr);
    return;
  }

  if (!tasks || !tasks.length) {
    const tr = document.createElement("tr");
    const td = document.createElement("td");
    td.colSpan = 4;
    td.className = "placeholder-text";
    td.textContent = "Nema taskova u snapshotu.";
    tr.appendChild(td);
    tbody.appendChild(tr);
    return;
  }

  const totalPill = $("tasks-total-pill");
  const activePill = $("tasks-active-pill");
  if (totalPill) totalPill.textContent = `Ukupno: ${tasks.length}`;
  if (activePill) activePill.textContent = `Aktivni: ${
    tasks.filter((t) =>
      String(t.status || "").toLowerCase().includes("to do") ||
      String(t.status || "").toLowerCase().includes("aktiv")
    ).length
  }`;

  for (const t of tasks) {
    const tr = document.createElement("tr");
    const cols = [
      t.title ?? t.name ?? "(bez naziva)",
      t.status ?? "-",
      t.priority ?? "-",
      t.due_date ?? t.deadline ?? "-",
    ];
    for (const c of cols) {
      const td = document.createElement("td");
      td.textContent = c;
      tr.appendChild(td);
    }
    tbody.appendChild(tr);
  }
}

// --------------------------------------------------
// WEEKLY PRIORITY
// --------------------------------------------------
async function loadWeeklyPriority() {
  const tbody = $("weekly-priority-body");
  if (!tbody) return;

  tbody.innerHTML = `
    <tr><td colspan="5" class="placeholder-text">
      Učitavanje weekly priority liste...
    </td></tr>
  `;

  try {
    const res = await fetch("/ceo/weekly-priority-memory");
    if (!res.ok) throw new Error(`Weekly HTTP ${res.status}`);
    const data = await res.json();
    const items = data.items || [];

    tbody.innerHTML = "";

    if (!items.length) {
      const tr = document.createElement("tr");
      const td = document.createElement("td");
      td.colSpan = 5;
      td.className = "placeholder-text";
      td.textContent = "Nema podataka za ovu sedmicu.";
      tr.appendChild(td);
      tbody.appendChild(tr);
      return;
    }

    for (const i of items) {
      const tr = document.createElement("tr");
      const cols = [
        i.type || "-",
        i.name || "-",
        i.status || "-",
        i.priority || "-",
        i.period || i.week || "-",
      ];
      for (const c of cols) {
        const td = document.createElement("td");
        td.textContent = c;
        tr.appendChild(td);
      }
      tbody.appendChild(tr);
    }
  } catch (err) {
    console.error("Failed to load weekly priority", err);
    tbody.innerHTML = `
      <tr><td colspan="5" class="placeholder-text">
        Greška pri učitavanju weekly priority liste.
      </td></tr>
    `;
  }
}

// --------------------------------------------------
// LEGACY CEO COMMAND (kept; ceo_chatbox.js runs the UX)
// --------------------------------------------------
async function sendCeoCommand() {
  const inputEl = $("ceo-command-input");
  if (!inputEl) return;

  const text = inputEl.value.trim();
  if (!text) return;

  const msgEl = appendHistoryMessage("user", text);

  setCommandStatus("PENDING", "Naredba poslana, čekam COO prevod...");
  const lastIdEl = $("last-approval-id");
  if (lastIdEl) lastIdEl.textContent = "–";

  try {
    const res = await fetch("/ceo/command", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        input_text: text,
        smart_context: null,
        source: "ceo_dashboard",
      }),
    });

    if (!res.ok) {
      const detailText = await res.text();
      setCommandStatus(
        "ERROR",
        `Greška: ${res.status} — ${detailText || "COO nije uspio prevesti naredbu."}`,
        "error"
      );
      if (msgEl) msgEl.classList.add("conv-error");
      return;
    }

    const data = await res.json();
    lastApprovalId = data.approval_id;
    if (lastIdEl) lastIdEl.textContent = lastApprovalId || "–";
    setCommandStatus("BLOCKED", "Naredba je BLOCKED. Odobri zahtjev da bi se izvršila.");

    inputEl.value = "";
    inputEl.style.height = "24px";
  } catch (err) {
    console.error("ceo/command failed", err);
    setCommandStatus("ERROR", "Greška pri slanju naredbe.", "error");
    if (msgEl) msgEl.classList.add("conv-error");
  }
}

async function approveLatest() {
  if (!lastApprovalId) {
    setCommandStatus("INFO", "Nema pending zahtjeva iz ove sesije.", "error");
    return;
  }

  try {
    const res = await fetch("/api/ai-ops/approval/approve", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ approval_id: lastApprovalId }),
    });

    if (!res.ok) {
      const detail = await res.text();
      setCommandStatus("ERROR", `Greška pri odobravanju: ${res.status} — ${detail || ""}`, "error");
      return;
    }

    setCommandStatus("EXECUTED", "Zahtjev odobren. Execution će biti vidljiv u metrikama.");
    await loadSnapshot();
  } catch (err) {
    console.error("approveLatest failed", err);
    setCommandStatus("ERROR", "Greška pri odobravanju zahtjeva.", "error");
  }
}

// --------------------------------------------------
// INIT
// --------------------------------------------------
document.addEventListener("DOMContentLoaded", () => {
  const sendBtn = $("send-command-btn");
  if (sendBtn) sendBtn.addEventListener("click", sendCeoCommand);

  const snapBtn = $("refresh-snapshot-btn");
  if (snapBtn) snapBtn.addEventListener("click", loadSnapshot);

  const weeklyBtn = $("refresh-weekly-btn");
  if (weeklyBtn) weeklyBtn.addEventListener("click", loadWeeklyPriority);

  const approveBtn = $("approve-latest-btn");
  if (approveBtn) approveBtn.addEventListener("click", approveLatest);

  const input = $("ceo-command-input");
  if (input) {
    input.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey && !e.ctrlKey && !e.altKey && !e.metaKey) {
        e.preventDefault();
        sendCeoCommand();
      }
    });

    input.addEventListener("input", () => {
      input.style.height = "24px";
      input.style.height = Math.min(input.scrollHeight, 120) + "px";
    });
  }

  loadSnapshot();
  loadWeeklyPriority();
});
