from __future__ import annotations

import json
import uuid

from fastapi.testclient import TestClient

from models.agent_contract import AgentOutput


def _load_app():
    try:
        from gateway.gateway_server import app  # type: ignore

        return app
    except Exception:
        from main import app  # type: ignore

        return app


def _payload(*, message: str = "hello") -> dict:
    sid = f"s_{uuid.uuid4().hex}"
    cid = f"c_{uuid.uuid4().hex}"
    return {
        "message": message,
        "session_id": sid,
        "conversation_id": cid,
        "identity_pack": {"user_id": "test"},
        "snapshot": {},
        "metadata": {"include_debug": True, "read_only": True},
    }


def _parse_ndjson(text: str) -> list[dict]:
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    out: list[dict] = []
    for ln in lines:
        out.append(json.loads(ln))
    return out


def test_api_chat_stream_disabled_returns_404(monkeypatch):
    monkeypatch.delenv("CHAT_STREAMING_ENABLED", raising=False)

    app = _load_app()
    client = TestClient(app)

    r = client.post("/api/chat/stream", json=_payload())
    assert r.status_code == 404, r.text
    body = r.json()
    assert body.get("error") == "chat_streaming_disabled"


def test_api_chat_stream_happy_path_parity_and_order(monkeypatch):
    monkeypatch.setenv("CHAT_STREAMING_ENABLED", "true")

    async def _dummy_route(self, *_args, **_kwargs):
        return AgentOutput(
            text="hello stream",
            proposed_commands=[{"command": "noop", "params": {"x": 1}}],
            agent_id="ceo_advisor",
            read_only=True,
            trace={"dummy": True},
        )

    monkeypatch.setattr(
        "services.agent_router_service.AgentRouterService.route",
        _dummy_route,
    )

    app = _load_app()
    client = TestClient(app)

    p = _payload(message="hello")

    r = client.post("/api/chat/stream", json=p)
    assert r.status_code == 200, r.text

    ct = (r.headers.get("content-type") or "").lower()
    assert "application/x-ndjson" in ct

    evts = _parse_ndjson(r.text)
    assert evts, "expected NDJSON events"

    assert evts[0].get("type") == "meta"
    assert evts[-1].get("type") == "done"

    final_events = [e for e in evts if e.get("type") == "assistant.final"]
    assert len(final_events) == 1

    deltas = [e for e in evts if e.get("type") == "assistant.delta"]
    joined = "".join(str(e.get("data", {}).get("delta_text") or "") for e in deltas)
    assert joined == "hello stream"

    final = final_events[0]
    final_data = final.get("data") or {}

    # Parity requirement: assistant.final.data.response must be /api/chat-compatible.
    resp_obj = final_data.get("response")
    assert isinstance(resp_obj, dict)

    # Stable-field parity with expected /api/chat-compatible output.
    assert str(resp_obj.get("text") or "") == "hello stream"
    pcs = resp_obj.get("proposed_commands")
    assert isinstance(pcs, list) and pcs
    assert pcs[0].get("command") == "noop"
    assert (pcs[0].get("args") or {}).get("x") == 1
    assert resp_obj.get("read_only") is True
    assert str(resp_obj.get("agent_id") or "")


def test_api_chat_stream_error_event_then_done(monkeypatch):
    monkeypatch.setenv("CHAT_STREAMING_ENABLED", "true")

    async def _route_boom(self, *_args, **_kwargs):
        raise RuntimeError("boom")

    async def _agent_boom(*_args, **_kwargs):
        raise RuntimeError("boom")

    # Force chat() itself to raise: route fails, then fallback agent creation fails.
    monkeypatch.setattr(
        "services.agent_router_service.AgentRouterService.route",
        _route_boom,
    )
    monkeypatch.setattr(
        "routers.chat_router.create_ceo_advisor_agent",
        _agent_boom,
    )

    app = _load_app()
    client = TestClient(app)

    r = client.post("/api/chat/stream", json=_payload(message="trigger"))
    assert r.status_code == 200, r.text

    evts = _parse_ndjson(r.text)
    types = [e.get("type") for e in evts]

    assert "meta" in types
    assert "error" in types
    assert types[-1] == "done"

    err = next(e for e in evts if e.get("type") == "error")
    msg = str((err.get("data") or {}).get("message") or "")
    assert "boom" in msg
