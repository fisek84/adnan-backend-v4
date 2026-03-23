export type VoiceAutoSendGraceCheck = {
  sessionId: number;
  currentSessionId: number;
  sentForSessionId: number;
  lastResultAtMs: number;
  anchorAtMs: number;
  nowMs: number;
  graceMs: number;
  text: string;
};

// Canonical grace delay used by browser SpeechRecognition auto-send.
// Keep this exported so tests can assert the configured value.
export const VOICE_AUTO_SEND_GRACE_MS = 4000;

// Canonical grace delay used by iOS WKWebView Bridge V1 final transcript auto-send.
// Keep identical to browser STT grace to ensure consistent UX across runtimes.
export const BRIDGE_V1_GRACE_MS = VOICE_AUTO_SEND_GRACE_MS;

export function shouldFireVoiceAutoSendAfterGrace(c: VoiceAutoSendGraceCheck): boolean {
  if (c.currentSessionId !== c.sessionId) return false;
  if (c.sentForSessionId === c.sessionId) return false;
  if (!String(c.text || "").trim()) return false;

  // Defensive: if called early, do not send yet.
  if (c.nowMs - c.anchorAtMs < c.graceMs) return false;

  // If any new recognition result arrived after the anchor point,
  // we treat it as continued speech and cancel this send.
  if (c.lastResultAtMs > c.anchorAtMs) return false;

  return true;
}
