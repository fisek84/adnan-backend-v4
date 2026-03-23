import test from "node:test";
import assert from "node:assert/strict";

import {
  shouldFireVoiceAutoSendAfterGrace,
  BRIDGE_V1_GRACE_MS,
  VOICE_AUTO_SEND_GRACE_MS,
} from "../.node-test-dist-voice-autosend/voiceAutoSendGuards.js";

test("VOICE_AUTO_SEND_GRACE_MS is 4000ms", () => {
  assert.equal(VOICE_AUTO_SEND_GRACE_MS, 4000);
});

test("BRIDGE_V1_GRACE_MS is 4000ms", () => {
  assert.equal(BRIDGE_V1_GRACE_MS, 4000);
});

test("4000ms pause behavior: does not fire at 3999ms, fires at 4000ms", () => {
  const anchorAtMs = 10_000;

  assert.equal(
    shouldFireVoiceAutoSendAfterGrace({
      sessionId: 1,
      currentSessionId: 1,
      sentForSessionId: -1,
      lastResultAtMs: anchorAtMs,
      anchorAtMs,
      nowMs: anchorAtMs + VOICE_AUTO_SEND_GRACE_MS - 1,
      graceMs: VOICE_AUTO_SEND_GRACE_MS,
      text: "hello",
    }),
    false
  );

  assert.equal(
    shouldFireVoiceAutoSendAfterGrace({
      sessionId: 1,
      currentSessionId: 1,
      sentForSessionId: -1,
      lastResultAtMs: anchorAtMs,
      anchorAtMs,
      nowMs: anchorAtMs + VOICE_AUTO_SEND_GRACE_MS,
      graceMs: VOICE_AUTO_SEND_GRACE_MS,
      text: "hello",
    }),
    true
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
