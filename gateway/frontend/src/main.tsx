console.log("CEO_CHATBOX_BOOT_OK");

import { mountCeoChatbox } from "./mountCeoChatbox";

declare global {
  interface Window {
    __EVO_UI__?: {
      ceoCommandUrl?: string;
      approveUrl?: string;
      headers?: Record<string, string>;
      mountSelector?: string;
    };
  }
}

const cfg = window.__EVO_UI__ ?? {};
const selector = cfg.mountSelector ?? "#root";

const el = document.querySelector(selector);

// fallback URL radi na Renderu i lokalno (FastAPI prefix)
const ceoCommandUrl = cfg.ceoCommandUrl ?? "/api/ceo/command";

if (el instanceof HTMLElement) {
  mountCeoChatbox({
    container: el,
    ceoCommandUrl,
    approveUrl: cfg.approveUrl,
    headers: cfg.headers,
  });
}
