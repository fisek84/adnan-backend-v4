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
  res.setHeader("Access-Control-Allow-Headers", "Content-Type, Authorization");
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
app.post("/api/ceo/command", (req, res) => {
  const prompt = req.body?.prompt;

  if (!prompt || typeof prompt !== "string") {
    return res.status(400).json({
      error: "BadRequest",
      message: 'Body mora imati string polje "prompt".',
      example: { prompt: "test" },
    });
  }

  const summary = `Primio sam prompt: "${prompt}". Predlažem jedan konkretan sljedeći korak.`;

  const commands = [
    {
      id: "cmd_001",
      type: "CREATE_TASK",
      payload: {
        title: `Follow-up: ${prompt}`.slice(0, 120),
        priority: "P2",
        owner: "CEO",
        due: null,
      },
    },
  ];

  return res.status(200).json({
    ok: true,
    summary,
    commands,
  });
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
