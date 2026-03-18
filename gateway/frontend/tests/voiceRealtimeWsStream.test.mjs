import test from "node:test";
import assert from "node:assert/strict";

import { createCeoConsoleApi } from "../.node-test-dist-chat-stream/components/ceoChat/api.js";

class FakeWebSocket {
  static instances = [];

  constructor(url) {
    this.url = String(url);
    this.readyState = 0;
    this.onopen = null;
    this.onmessage = null;
    this.onerror = null;
    this.onclose = null;
    this._closed = false;
    this._sawSessionStart = false;

    FakeWebSocket.instances.push(this);

    queueMicrotask(() => {
      if (this._closed) return;
      this.readyState = 1;
      this.onopen?.();
    });
  }

  send(data) {
    const msg = JSON.parse(String(data || "{}"));
    const type = String(msg?.type || "");

    if (type === "session.start") {
      this._sawSessionStart = true;
      queueMicrotask(() => {
        this.onmessage?.({
          data: JSON.stringify({
            v: 1,
            type: "session.started",
            seq: 0,
            ts: new Date().toISOString(),
            data: { capabilities: { text_streaming: true, final_response: true, cancel: true } },
          }),
        });
      });
      return;
    }

    if (type === "input.final") {
      assert.equal(this._sawSessionStart, true);
      const final = { text: "Hello", proposed_commands: [{ command: "noop", args: { x: 1 } }] };
      const events = [
        { type: "meta", data: { request_id: "r1" } },
        { type: "turn.started", data: { turn_id: "t1" } },
        { type: "assistant.delta", data: { delta_text: "Hel" } },
        { type: "assistant.delta", data: { delta_text: "lo" } },
        { type: "assistant.final", data: { text: "Hello", response: final } },
        { type: "done", data: { ok: true, reason: "completed" } },
      ];

      for (const evt of events) {
        queueMicrotask(() => {
          this.onmessage?.({
            data: JSON.stringify({
              v: 1,
              type: evt.type,
              seq: 0,
              ts: new Date().toISOString(),
              data: evt.data,
            }),
          });
        });
      }

      return;
    }
  }

  close(code = 1000, reason = "") {
    if (this._closed) return;
    this._closed = true;
    this.readyState = 3;
    queueMicrotask(() => {
      this.onclose?.({ code, reason });
    });
  }
}

test("createCeoConsoleApi.sendVoiceExecText: returns WS stream + finalResponse parity", async () => {
  const originalWebSocket = globalThis.WebSocket;
  try {
    globalThis.WebSocket = FakeWebSocket;

    const api = createCeoConsoleApi({ ceoCommandUrl: "http://example.com/api/chat" });
    const resp = await api.sendVoiceExecText({ text: "hi", session_id: "s1" });

    assert.ok(resp.stream);
    let acc = "";
    for await (const c of resp.stream) acc += c;
    assert.equal(acc, "Hello");

    assert.ok(FakeWebSocket.instances.length >= 1);
    assert.ok(FakeWebSocket.instances[0].url.includes("/api/voice/realtime/ws"));
    assert.ok(FakeWebSocket.instances[0].url.startsWith("ws://"));

    const finalRaw = await resp.stream.finalResponse;
    assert.deepEqual(finalRaw, {
      text: "Hello",
      proposed_commands: [{ command: "noop", args: { x: 1 } }],
    });
  } finally {
    globalThis.WebSocket = originalWebSocket;
  }
});
