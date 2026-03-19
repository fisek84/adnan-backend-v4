import test from "node:test";
import assert from "node:assert/strict";

import {
  extractVoiceOutputFromResponse,
  isPlayableVoiceOutput,
  createAudioFromVoiceOutput,
  createAudioFromVoiceOutputUsingGlobals,
  safeRevokeObjectUrl,
} from "../.node-test-dist/voiceOutputAudio.js";

function atobViaBuffer(b64) {
  return Buffer.from(b64, "base64").toString("binary");
}

class FakeBlob {
  constructor(parts, opts) {
    this.parts = parts;
    this.type = opts?.type;
  }
}

test("extractVoiceOutputFromResponse: direct and nested", () => {
  assert.deepEqual(extractVoiceOutputFromResponse(null), null);
  assert.deepEqual(extractVoiceOutputFromResponse("x"), null);

  const direct = { voice_output: { available: true, content_type: "audio/wav", audio_base64: "AA==" } };
  assert.equal(extractVoiceOutputFromResponse(direct)?.content_type, "audio/wav");

  const nested = { raw: { voice_output: { available: true, content_type: "audio/mpeg", audio_base64: "AA==" } } };
  assert.equal(extractVoiceOutputFromResponse(nested)?.content_type, "audio/mpeg");
});

test("isPlayableVoiceOutput: requires available true + fields", () => {
  assert.equal(isPlayableVoiceOutput(null), false);
  assert.equal(isPlayableVoiceOutput({}), false);
  assert.equal(isPlayableVoiceOutput({ available: false, content_type: "audio/wav", audio_base64: "AA==" }), false);
  assert.equal(isPlayableVoiceOutput({ available: true, content_type: "audio/wav" }), false);
  assert.equal(isPlayableVoiceOutput({ available: true, audio_base64: "AA==" }), false);

  assert.equal(isPlayableVoiceOutput({ available: true, content_type: "audio/wav", audio_base64: "AA==" }), true);

  assert.equal(isPlayableVoiceOutput({ available: true, content_type: "audio/mpeg", audio_url: "/api/voice/output/x" }), true);
});

test("createAudioFromVoiceOutput: returns object URL and content type", () => {
  const vo = { available: true, content_type: "audio/wav", audio_base64: "AQID" }; // 0x01 0x02 0x03

  const created = [];
  const res = createAudioFromVoiceOutput(vo, {
    atob: atobViaBuffer,
    Blob: FakeBlob,
    createObjectURL: (blob) => {
      created.push(blob);
      return "blob:fake-url";
    },
  });

  assert.ok(res);
  assert.equal(res.url, "blob:fake-url");
  assert.equal(res.contentType, "audio/wav");
  assert.equal(created.length, 1);
  assert.equal(created[0].type, "audio/wav");

  const bytes = created[0].parts[0];
  assert.equal(bytes[0], 1);
  assert.equal(bytes[1], 2);
  assert.equal(bytes[2], 3);
});

test("createAudioFromVoiceOutput: enforces maxBase64Chars", () => {
  const vo = { available: true, content_type: "audio/wav", audio_base64: "AAAA" };
  const res = createAudioFromVoiceOutput(vo, { atob: atobViaBuffer, Blob: FakeBlob, createObjectURL: () => "x" }, { maxBase64Chars: 1 });
  assert.equal(res, null);
});

test("createAudioFromVoiceOutput: uses audio_url when present", () => {
  const vo = {
    available: true,
    content_type: "audio/mpeg",
    audio_url: "/api/voice/output/abc",
    audio_base64: "AAAA", // should be ignored
  };

  const res = createAudioFromVoiceOutput(vo, {
    atob: atobViaBuffer,
    Blob: FakeBlob,
    createObjectURL: () => {
      throw new Error("should not be called");
    },
  }, { maxBase64Chars: 1 });

  assert.ok(res);
  assert.equal(res.url, "/api/voice/output/abc");
  assert.equal(res.contentType, "audio/mpeg");
});

test("createAudioFromVoiceOutputUsingGlobals: null in Node", () => {
  assert.equal(createAudioFromVoiceOutputUsingGlobals({ available: true, content_type: "audio/wav", audio_base64: "AA==" }), null);
});

test("safeRevokeObjectUrl: never throws", () => {
  safeRevokeObjectUrl(null);
  safeRevokeObjectUrl(undefined);
  safeRevokeObjectUrl("");
  safeRevokeObjectUrl("blob:does-not-exist");
});
