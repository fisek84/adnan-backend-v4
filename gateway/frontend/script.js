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
    btn.textContent = action.oznaka || "Akcija";
    btn.className = "action-btn";

    btn.addEventListener("click", () => {
      input.value = action.primjer || "";
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

    // -------------------------------
    // UX HANDLING (CANONICAL)
    // -------------------------------

    if (data.status !== "u redu" && data.status !== "ok") {
      renderError(data.razlog || "Nepoznata greška");
      return;
    }

    // Glavna poruka
    if (data.tekst) {
      renderMessage(data.tekst);
    } else {
      renderMessage("ℹ️ Sistem nije vratio poruku.");
    }

    // Sugestije / sljedeće radnje
    if (data.sljedeće_radnje) {
      renderActions(data.sljedeće_radnje);
    }

  } catch (err) {
    renderError(err.message);
  }
});
