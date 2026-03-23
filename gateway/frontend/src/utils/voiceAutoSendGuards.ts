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
