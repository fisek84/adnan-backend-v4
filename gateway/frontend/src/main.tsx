// gateway/frontend/src/main.tsx

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
if (el instanceof HTMLElement && cfg.ceoCommandUrl) {
  mountCeoChatbox({
    container: el,
    ceoCommandUrl: cfg.ceoCommandUrl,
    approveUrl: cfg.approveUrl,
    headers: cfg.headers,
  });
}
