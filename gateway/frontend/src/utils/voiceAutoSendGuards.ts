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

export type VoiceSendBusyState = "idle" | "submitting" | "streaming" | "error";

export type PendingVoiceAutoSend = {
  sessionId: number;
  anchorAtMs: number;
  graceMs: number;
  text: string;
};

export type ResolvePendingVoiceAutoSendResult =
  | { action: "keep"; pending: PendingVoiceAutoSend }
  | { action: "drop"; pending: null }
  | { action: "send"; pending: null; text: string; sessionId: number };

// Voice endpointing thresholds.
// Two-stage endpointing: thinking pause -> soft end (send) -> hard end (fallback send).
export const VOICE_THINKING_PAUSE_MS = 1500;
export const VOICE_SOFT_END_MS = 4000;
export const VOICE_HARD_END_MS = 6000;

// Back-compat alias: existing code/tests treat "grace" as the soft end.
// Keep this exported so tests can assert the configured value.
export const VOICE_AUTO_SEND_GRACE_MS = VOICE_SOFT_END_MS;

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

/**
 * Minimal deterministic helper for retry-on-idle:
 * - If UI is busy, keep the pending send.
 * - When UI becomes idle, re-check eligibility and either send or drop.
 */
export function resolvePendingVoiceAutoSendOnIdle(args: {
  pending: PendingVoiceAutoSend | null;
  busy: VoiceSendBusyState;
  currentSessionId: number;
  sentForSessionId: number;
  lastResultAtMs: number;
  nowMs: number;
}): ResolvePendingVoiceAutoSendResult {
  const p = args.pending;
  if (!p) return { action: "drop", pending: null };

  if (args.busy === "submitting" || args.busy === "streaming") {
    return { action: "keep", pending: p };
  }

  const ok = shouldFireVoiceAutoSendAfterGrace({
    sessionId: p.sessionId,
    currentSessionId: args.currentSessionId,
    sentForSessionId: args.sentForSessionId,
    lastResultAtMs: args.lastResultAtMs,
    anchorAtMs: p.anchorAtMs,
    nowMs: args.nowMs,
    graceMs: p.graceMs,
    text: p.text,
  });

  if (!ok) return { action: "drop", pending: null };
  return { action: "send", pending: null, text: p.text, sessionId: p.sessionId };
}

function _capitalizeFirstLetter(s: string): string {
  if (!s) return s;
  // Find first Unicode letter and uppercase it.
  const chars = Array.from(s);
  for (let i = 0; i < chars.length; i++) {
    const ch = chars[i];
    if (/\p{L}/u.test(ch)) {
      chars[i] = ch.toUpperCase();
      return chars.join("");
    }
  }
  return s;
}

function _looksLikeQuestion(s: string): boolean {
  const t = s.trim().toLowerCase();
  if (!t) return false;

  // Minimal deterministic heuristic for "obvious" questions.
  // 1) Question openers (BHS + EN)
  const opener = /^(koliko|kako|zasto|zašto|sta|šta|gdje|gde|kada|ko|da\s+li|jel|je\s+li|jesi\s+li|mogu\s+li|možeš\s+li|mozes\s+li|what|why|how|when|where|who|can|could|would|should|do|does|did|is|are|am|have|has|will)\b/u;
  if (opener.test(t)) return true;

  // 2) Common embedded question phrases (kept small + explicit)
  const embedded = /\b(who\s+are\s+you|what\s+is\s+your\s+role|how\s+are\s+you|how\s+do\s+you)\b/u;
  if (embedded.test(t)) return true;

  // 3) Any explicit question word in the sentence (English only)
  // Helps cases like: "I want to know who you are ..."
  const anyQ = /\b(who|what|why|how|when|where)\b/u;
  return anyQ.test(t);
}

/**
 * Minimal deterministic punctuation normalization for voice-dictated user text.
 * - Capitalize first letter
 * - Add '?' for obvious questions
 * - Otherwise add '.' if missing terminal punctuation
 */
export function normalizeVoiceUserTextForSend(rawText: string): string {
  const trimmed = String(rawText ?? "").trim();
  if (!trimmed) return "";

  const hasTerminalPunct = /[.!?…]$/.test(trimmed);
  let out = trimmed;
  if (!hasTerminalPunct) {
    out = trimmed + (_looksLikeQuestion(trimmed) ? "?" : ".");
  }

  return _capitalizeFirstLetter(out);
}
