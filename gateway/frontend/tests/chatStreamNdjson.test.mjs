import test from "node:test";
import assert from "node:assert/strict";

import { streamTextFromResponse } from "../.node-test-dist-chat-stream/components/ceoChat/normalize.js";
import { createCeoConsoleApi } from "../.node-test-dist-chat-stream/components/ceoChat/api.js";

function ndjsonResponseFromLines(lines, { status = 200, headers = {} } = {}) {
  const text = lines.join("\n") + "\n";
  const enc = new TextEncoder();
  const rs = new ReadableStream({
    start(controller) {
      // Split into a couple of chunks to ensure buffering logic works.
      const mid = Math.max(1, Math.floor(text.length / 2));
      controller.enqueue(enc.encode(text.slice(0, mid)));
      controller.enqueue(enc.encode(text.slice(mid)));
      controller.close();
    },
  });

  return new Response(rs, {
    status,
    headers: {
      "content-type": "application/x-ndjson; charset=utf-8",
      ...headers,
    },
  });
}

test("streamTextFromResponse: yields assistant.delta and exposes assistant.final", async () => {
  const final = { text: "Hello", proposed_commands: [{ command: "noop", params: { x: 1 } }] };

  const res = ndjsonResponseFromLines([
    JSON.stringify({ type: "meta", data: { request_id: "r1" } }),
    JSON.stringify({ type: "assistant.delta", data: { delta_text: "Hel" } }),
    JSON.stringify({ type: "assistant.delta", data: { delta_text: "lo" } }),
    JSON.stringify({ type: "assistant.final", data: { text: "Hello", response: final } }),
    JSON.stringify({ type: "done" }),
  ]);

  const stream = streamTextFromResponse(res);
  let acc = "";
  for await (const chunk of stream) acc += chunk;

  assert.equal(acc, "Hello");
  const finalRaw = await stream.finalResponse;
  assert.deepEqual(finalRaw, final);
});

test("streamTextFromResponse: error event throws and rejects finalResponse", async () => {
  const res = ndjsonResponseFromLines([
    JSON.stringify({ type: "assistant.delta", data: { delta_text: "Hi" } }),
    JSON.stringify({ type: "error", data: { code: "boom", message: "nope" } }),
    JSON.stringify({ type: "done" }),
  ]);

  const stream = streamTextFromResponse(res);
  await assert.rejects(
    async () => {
      // Consume the iterator; should throw.
      // eslint-disable-next-line no-unused-vars
      for await (const _ of stream) {
        // noop
      }
    },
    (e) => String(e?.message || e).includes("nope")
  );

  await assert.rejects(stream.finalResponse);
});

test("createCeoConsoleApi.sendCommand: falls back to /api/chat when stream is 404", async () => {
  const originalFetch = globalThis.fetch;
  try {
    globalThis.fetch = async (url, _opts) => {
      if (String(url).includes("/api/chat/stream") || String(url).endsWith("/chat/stream")) {
        return new Response(JSON.stringify({ error: "chat_streaming_disabled" }), {
          status: 404,
          headers: { "content-type": "application/json" },
        });
      }

      return new Response(JSON.stringify({ text: "ok", proposed_commands: [{ command: "noop" }] }), {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    };

    const api = createCeoConsoleApi({ ceoCommandUrl: "/api/chat" });
    const resp = await api.sendCommand({ text: "hi" });

    assert.ok(!resp.stream);
    assert.equal(resp.systemText, "ok");
    assert.equal(Array.isArray(resp.proposed_commands), true);
    assert.equal(resp.proposed_commands.length, 1);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("createCeoConsoleApi.sendCommand: returns stream when NDJSON content-type", async () => {
  const originalFetch = globalThis.fetch;
  try {
    globalThis.fetch = async (url, _opts) => {
      if (String(url).includes("/api/chat/stream") || String(url).endsWith("/chat/stream")) {
        return ndjsonResponseFromLines([
          JSON.stringify({ type: "meta", data: { request_id: "r2" } }),
          JSON.stringify({ type: "assistant.delta", data: { delta_text: "A" } }),
          JSON.stringify({ type: "assistant.delta", data: { delta_text: "B" } }),
          JSON.stringify({ type: "assistant.final", data: { response: { text: "AB" } } }),
          JSON.stringify({ type: "done" }),
        ]);
      }

      throw new Error(`Unexpected fetch to ${url}`);
    };

    const api = createCeoConsoleApi({ ceoCommandUrl: "/api/chat" });
    const resp = await api.sendCommand({ text: "hi" });

    assert.ok(resp.stream);

    let acc = "";
    for await (const c of resp.stream) acc += c;
    assert.equal(acc, "AB");

    const finalRaw = await resp.stream.finalResponse;
    assert.deepEqual(finalRaw, { text: "AB" });
  } finally {
    globalThis.fetch = originalFetch;
  }
});
