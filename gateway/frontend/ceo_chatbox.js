// gateway/frontend/ceo_chatbox.js
(function () {
  try {
    console.log("[CEO_CHATBOX] ceo_chatbox.js LOADED", new Date().toISOString());
    window.__CEO_CHATBOX_LOADED__ = true;

    var host = document.getElementById("ceo-left-panel");
    if (!host) {
      console.log("[CEO_CHATBOX] mount element #ceo-left-panel not found");
      return;
    }

    host.innerHTML =
      '<div style="padding:12px;border:1px solid rgba(255,255,255,0.10);border-radius:12px;background:#0b0f14;color:rgba(255,255,255,0.92);font-family:system-ui,Segoe UI,Roboto,Arial">' +
      '<div style="font-weight:700;margin-bottom:6px">CEO Chatbox boot OK (probe)</div>' +
      '<div style="color:rgba(255,255,255,0.65);font-size:13px;line-height:1.4">' +
      'Ako vidiš ovo, onda se /static/ceo_chatbox.js učitava i izvršava. Sljedeći korak je zamjena ovog probe fajla React build outputom.' +
      "</div>" +
      "</div>";
  } catch (e) {
    console.error("[CEO_CHATBOX] probe failed", e);
  }
})();
