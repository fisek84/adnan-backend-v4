import test from "node:test";
import assert from "node:assert/strict";

import {
  shouldFireVoiceAutoSendAfterGrace,
  BRIDGE_V1_GRACE_MS,
  VOICE_THINKING_PAUSE_MS,
  VOICE_SOFT_END_MS,
  VOICE_HARD_END_MS,
  normalizeVoiceUserTextForSend,
} from "../.node-test-dist-voice-autosend/voiceAutoSendGuards.js";

test("VOICE_THINKING_PAUSE_MS is 1500ms", () => {
  assert.equal(VOICE_THINKING_PAUSE_MS, 1500);
});

test("VOICE_SOFT_END_MS is 4000ms", () => {
  assert.equal(VOICE_SOFT_END_MS, 4000);
});

test("VOICE_HARD_END_MS is 6000ms", () => {
  assert.equal(VOICE_HARD_END_MS, 6000);
});

test("BRIDGE_V1_GRACE_MS is 4000ms", () => {
  assert.equal(BRIDGE_V1_GRACE_MS, 4000);
});

test("2s pause = ne salje (soft end)", () => {
  const anchorAtMs = 10_000;

  assert.equal(
    shouldFireVoiceAutoSendAfterGrace({
      sessionId: 1,
      currentSessionId: 1,
      sentForSessionId: -1,
      lastResultAtMs: anchorAtMs,
      anchorAtMs,
      nowMs: anchorAtMs + 2000,
      graceMs: VOICE_SOFT_END_MS,
      text: "hello",
    }),
    false
  );
});

test("4–6s silence = salje (soft at 4s; hard at 6s)", () => {
  const anchorAtMs = 10_000;

  assert.equal(
    shouldFireVoiceAutoSendAfterGrace({
      sessionId: 1,
      currentSessionId: 1,
      sentForSessionId: -1,
      lastResultAtMs: anchorAtMs,
      anchorAtMs,
      nowMs: anchorAtMs + VOICE_SOFT_END_MS,
      graceMs: VOICE_SOFT_END_MS,
      text: "hello",
    }),
    true
  );

  assert.equal(
    shouldFireVoiceAutoSendAfterGrace({
      sessionId: 1,
      currentSessionId: 1,
      sentForSessionId: -1,
      lastResultAtMs: anchorAtMs,
      anchorAtMs,
      nowMs: anchorAtMs + VOICE_HARD_END_MS,
      graceMs: VOICE_HARD_END_MS,
      text: "hello",
    }),
    true
  );
});

test("partial → pause → partial = ne salje izmedju", () => {
  // First partial at t=10000ms arms timers anchored at 10000.
  // Second partial arrives at t=12000ms (2s pause) and must cancel the earlier send.
  const anchorAtMs = 10_000;
  const secondPartialAtMs = 12_000;
  const softFireAtMs = anchorAtMs + VOICE_SOFT_END_MS;

  assert.equal(
    shouldFireVoiceAutoSendAfterGrace({
      sessionId: 2,
      currentSessionId: 2,
      sentForSessionId: -1,
      lastResultAtMs: secondPartialAtMs,
      anchorAtMs,
      nowMs: softFireAtMs,
      graceMs: VOICE_SOFT_END_MS,
      text: "hello",
    }),
    false
  );
});

test("shouldFireVoiceAutoSendAfterGrace: happy path", () => {
  assert.equal(
    shouldFireVoiceAutoSendAfterGrace({
      sessionId: 1,
      currentSessionId: 1,
      sentForSessionId: -1,
      lastResultAtMs: 1000,
      anchorAtMs: 1000,
      nowMs: 2500,
      graceMs: 1500,
      text: "hello",
    }),
    true
  );
});

test('"koliko imam zadataka" → "Koliko imam zadataka?"', () => {
  assert.equal(normalizeVoiceUserTextForSend("koliko imam zadataka"), "Koliko imam zadataka?");
});

test("shouldFireVoiceAutoSendAfterGrace: blocks if new result arrives after anchor", () => {
  assert.equal(
    shouldFireVoiceAutoSendAfterGrace({
      sessionId: 1,
      currentSessionId: 1,
      sentForSessionId: -1,
      lastResultAtMs: 1100,
      anchorAtMs: 1000,
      nowMs: 2600,
      graceMs: 1500,
      text: "hello",
    }),
    false
  );
});

test("shouldFireVoiceAutoSendAfterGrace: blocks double-send in same session", () => {
  assert.equal(
    shouldFireVoiceAutoSendAfterGrace({
      sessionId: 2,
      currentSessionId: 2,
      sentForSessionId: 2,
      lastResultAtMs: 2000,
      anchorAtMs: 2000,
      nowMs: 4000,
      graceMs: 1500,
      text: "hello",
    }),
    false
  );
});

test("shouldFireVoiceAutoSendAfterGrace: blocks if session changed", () => {
  assert.equal(
    shouldFireVoiceAutoSendAfterGrace({
      sessionId: 3,
      currentSessionId: 4,
      sentForSessionId: -1,
      lastResultAtMs: 3000,
      anchorAtMs: 3000,
      nowMs: 5000,
      graceMs: 1500,
      text: "hello",
    }),
    false
  );
});

test("shouldFireVoiceAutoSendAfterGrace: blocks if grace not elapsed", () => {
  assert.equal(
    shouldFireVoiceAutoSendAfterGrace({
      sessionId: 5,
      currentSessionId: 5,
      sentForSessionId: -1,
      lastResultAtMs: 5000,
      anchorAtMs: 5000,
      nowMs: 6200,
      graceMs: 1500,
      text: "hello",
    }),
    false
  );
});

test("shouldFireVoiceAutoSendAfterGrace: blocks empty text", () => {
  assert.equal(
    shouldFireVoiceAutoSendAfterGrace({
      sessionId: 6,
      currentSessionId: 6,
      sentForSessionId: -1,
      lastResultAtMs: 6000,
      anchorAtMs: 6000,
      nowMs: 8000,
      graceMs: 1500,
      text: "   ",
    }),
    false
  );
});
