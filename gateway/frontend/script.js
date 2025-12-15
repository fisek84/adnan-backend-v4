// gateway/frontend/script.js

const sendBtn = document.getElementById("send");
const input = document.getElementById("input");
const output = document.getElementById("output");

if (!sendBtn || !input || !output) {
  console.error("❌ Frontend elementi nisu pronađeni");
}

function renderMessage(text) {
  output.innerHTML = `<div class="message">${text.replace(/\n/g, "<br>")}</div>`;
}

function renderError(text) {
  output.innerHTML = `<div class="error">❌ ${text}</div>`;
}

function renderActions(actions) {
  if (!Array.isArray(actions) || actions.length === 0) return;

  const container = document.createElement("div");
  container.className = "actions";

  actions.forEach(action => {
    const btn = document.createElement("button");
    btn.textContent = action.label || "Akcija";
    btn.className = "action-btn";

    btn.addEventListener("click", () => {
      input.value = action.example || "";
      input.focus();
    });

    container.appendChild(btn);
  });

  output.appendChild(container);
}

sendBtn.addEventListener("click", async () => {
  const text = input.value.trim();
  if (!text) return;

  renderMessage("🧠 Razmišljam...");

  try {
    const res = await fetch("/api/adnan-ai/input", {
      method: "POST",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify({
        text: text,
        context: {}
      })
    });

    if (!res.ok) {
      const errText = await res.text();
      throw new Error(`HTTP ${res.status}: ${errText}`);
    }

    const data = await res.json();

    // ---------------------------------
    // CANONICAL OS RESPONSE HANDLING
    // ---------------------------------

    // 1. Failure
    if (data.failure) {
      renderError(data.failure.error || "Greška u sistemu.");
      return;
    }

    // 2. Primary message (CEO / System voice)
    if (data.message) {
      if (typeof data.message === "string") {
        renderMessage(data.message);
      } else if (data.message.text) {
        renderMessage(data.message.text);
      } else {
        renderMessage("ℹ️ Sistem je aktivan.");
      }
    } else {
      renderMessage("ℹ️ Sistem je aktivan.");
    }

    // 3. Approval actions (ako postoje)
    if (data.approval && data.approval.read_only === false) {
      renderActions(data.approval.actions || []);
    }

  } catch (err) {
    renderError(err.message);
  }
});
