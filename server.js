console.log("✅ LOADING server.js iz tačne verzije");

const express = require("express");
require("dotenv").config();

const app = express();
const PORT = process.env.PORT || 3000;

// OBAVEZNO za parsiranje JSON tijela
app.use(express.json({ limit: "1mb" }));

/**
 * CORS + Preflight (OPTIONS)
 * Dozvoljava pozive sa Vite frontenda (5173) prema API-u (3000).
 */
const ALLOWED_ORIGINS = new Set([
  "http://localhost:5173",
  "http://127.0.0.1:5173",
]);

app.use((req, res, next) => {
  const origin = req.headers.origin;

  if (origin && ALLOWED_ORIGINS.has(origin)) {
    res.setHeader("Access-Control-Allow-Origin", origin);
    res.setHeader("Vary", "Origin");
  }

  res.setHeader("Access-Control-Allow-Methods", "GET,POST,OPTIONS");
  res.setHeader(
    "Access-Control-Allow-Headers",
    "Content-Type, Authorization, X-Initiator, X-CEO-Token"
  );
  res.setHeader("Access-Control-Max-Age", "86400");

  // Preflight request
  if (req.method === "OPTIONS") {
    return res.sendStatus(204);
  }

  next();
});

// --- Home ruta za test ---
app.get("/", (req, res) => {
  res.send("Server radi!");
});

app.get("/test-post-simulacija", (req, res) => {
  const fakeBody = { title: "Simulacija iz browsera" };
  console.log("🔥 Simulirani POST:", fakeBody);
  res.status(200).json({
    message: "Simulacija prošla",
    data: fakeBody,
  });
});

// --- POST ruta za projekte ---
app.post("/api/projects", (req, res) => {
  const data = req.body;
  console.log("Primljen projekat:", data);
  res.status(201).json({
    message: "Projekat kreiran",
    data: data,
  });
});

/**
 * CEO Advisor endpoint (minimalni stub)
 * Očekuje JSON: { "prompt": "..." }
 * Vraća: { ok, summary, commands[] }
 */
app.post("/api/ceo/command", async (req, res) => {
  // IMPORTANT:
  // This endpoint must call the real FastAPI gateway (Python) CEO runtime.
  // The previous implementation was a local stub and would NEVER exercise
  // services/ceo_advisor_agent.py.

  const upstreamBase = process.env.PY_GATEWAY_URL || "http://localhost:8000";
  const upstreamUrl = `${upstreamBase.replace(/\/$/, "")}/api/ceo/command`;

  if (typeof fetch !== "function") {
    return res.status(500).json({
      error: "ServerMisconfigured",
      message:
        "Node runtime nema global fetch(). Pokreni na Node 18+ ili koristi direktno Python gateway na :8000.",
    });
  }

  // Accept both legacy {prompt:"..."} and canonical payload shapes.
  const body = req.body || {};
  const prompt = body.prompt;

  let payload = body;
  if (typeof prompt === "string" && prompt.trim()) {
    const sessionId =
      (typeof body.session_id === "string" && body.session_id) ||
      (body.data && typeof body.data.session_id === "string" && body.data.session_id) ||
      null;
    payload = {
      text: prompt.trim(),
      data: sessionId ? { session_id: sessionId } : body.data,
    };
  }

  try {
    const upstreamRes = await fetch(upstreamUrl, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        // Forward auth/CEO headers if present.
        ...(req.headers.authorization
          ? { Authorization: req.headers.authorization }
          : {}),
        ...(req.headers["x-initiator"]
          ? { "X-Initiator": req.headers["x-initiator"] }
          : {}),
        ...(req.headers["x-ceo-token"]
          ? { "X-CEO-Token": req.headers["x-ceo-token"] }
          : {}),
      },
      body: JSON.stringify(payload),
    });

    const text = await upstreamRes.text();
    let json;
    try {
      json = JSON.parse(text);
    } catch {
      json = { ok: false, error: "UpstreamNonJSON", raw: text };
    }

    return res.status(upstreamRes.status).json(json);
  } catch (e) {
    return res.status(502).json({
      error: "BadGateway",
      message: "Ne mogu kontaktirati Python gateway.",
      upstream: upstreamUrl,
      detail: String(e && e.message ? e.message : e),
    });
  }
});

/**
 * JSON parse error handler
 * (da dobiješ čitljiv JSON error umjesto HTML stranice)
 */
app.use((err, req, res, next) => {
  if (err && err.type === "entity.parse.failed") {
    return res.status(400).json({
      error: "InvalidJSON",
      message: "Neispravan JSON u request body.",
    });
  }
  next(err);
});

// Pokretanje servera
app.listen(PORT, () => {
  console.log(`Server running on port ${PORT}`);
});
