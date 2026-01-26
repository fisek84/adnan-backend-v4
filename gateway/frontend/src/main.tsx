// gateway/frontend/src/main.tsx

import React from "react";
import ReactDOM from "react-dom/client";

// style.css je u gateway/frontend/style.css, a ovaj fajl je u gateway/frontend/src/
// zato ide jedan nivo gore iz src/
import "../style.css";

import App from "./App";
import { ThemeProvider } from "./contexts/ThemeContext";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <ThemeProvider>
      <App />
    </ThemeProvider>
  </React.StrictMode>
);

// PWA Service Worker registration (production-safe, dev-off by default)
// - Enabled in production builds OR when VITE_PWA_SW_ENABLED === "true"
// - Never registers on server-side (Vite SPA has no SSR, but keep it safe)
const pwaSwEnabled =
  (import.meta.env.PROD || import.meta.env.VITE_PWA_SW_ENABLED === "true") &&
  typeof window !== "undefined" &&
  "serviceWorker" in navigator;

if (pwaSwEnabled) {
  window.addEventListener("load", () => {
    navigator.serviceWorker
      .register("/service-worker.js")
      .catch((err) => console.warn("[PWA] service worker registration failed", err));
  });
}
