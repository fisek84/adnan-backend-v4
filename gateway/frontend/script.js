// gateway/frontend/script.js

const sendBtn = document.getElementById("send");
const input = document.getElementById("input");
const output = document.getElementById("output");

if (!sendBtn || !input || !output) {
  console.error("❌ Frontend elementi nisu pronađeni");
}

sendBtn.addEventListener("click", async () => {
  const text = input.value.trim();
  if (!text) return;

  output.textContent = "🧠 Razmišljam...";

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

    output.textContent =
      typeof data === "string"
        ? data
        : JSON.stringify(data, null, 2);

  } catch (err) {
    output.textContent = "❌ Greška: " + err.message;
  }
});
