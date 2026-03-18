from __future__ import annotations

import asyncio
import json
import uuid

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from models.agent_contract import AgentOutput


def _load_app():
    try:
        from gateway.gateway_server import app  # type: ignore

        return app
    except Exception:
        from main import app  # type: ignore

        return app


def _recv_json(ws) -> dict:
    return json.loads(ws.receive_text())


def _drain_until_done(ws, *, max_events: int = 50) -> list[dict]:
    evts: list[dict] = []
    for _ in range(max_events):
        evt = _recv_json(ws)
        evts.append(evt)
        if evt.get("type") == "done":
            break
    return evts


def test_voice_realtime_ws_disabled_closes(monkeypatch):
    monkeypatch.delenv("VOICE_REALTIME_WS_ENABLED", raising=False)

    app = _load_app()
    client = TestClient(app)

    with pytest.raises(WebSocketDisconnect) as excinfo:
        with client.websocket_connect("/api/voice/realtime/ws") as ws:
            ws.receive_text()

    assert excinfo.value.code == 4404


def test_voice_realtime_ws_token_enforced_requires_query_token(monkeypatch):
    monkeypatch.setenv("VOICE_REALTIME_WS_ENABLED", "true")
    monkeypatch.setenv("CEO_TOKEN_ENFORCEMENT", "true")
    monkeypatch.setenv("CEO_APPROVAL_TOKEN", "secret")

    app = _load_app()
    client = TestClient(app)

    with pytest.raises(WebSocketDisconnect) as excinfo:
        with client.websocket_connect("/api/voice/realtime/ws") as ws:
            ws.receive_text()

    assert excinfo.value.code == 4403


def test_voice_realtime_ws_happy_path_event_order_and_parity(monkeypatch):
    monkeypatch.setenv("VOICE_REALTIME_WS_ENABLED", "true")

    async def _dummy_route(self, *_args, **_kwargs):
        return AgentOutput(
            text="hello ws",
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

    sid = f"s_{uuid.uuid4().hex}"
    cid = f"c_{uuid.uuid4().hex}"

    with client.websocket_connect("/api/voice/realtime/ws") as ws:
        ws.send_text(
            json.dumps(
                {
                    "type": "session.start",
                    "data": {"session_id": sid, "conversation_id": cid},
                }
            )
        )

        started = _recv_json(ws)
        assert started.get("type") == "session.started"
        assert (started.get("data") or {}).get("capabilities", {}).get("cancel") is True

        ws.send_text(
            json.dumps(
                {
                    "type": "input.final",
                    "data": {
                        "text": "hello",
                        "identity_pack": {"user_id": "test"},
                        "metadata": {"source": "voice"},
                    },
                }
            )
        )

        evts = _drain_until_done(ws)
        types = [e.get("type") for e in evts]

        assert "meta" in types
        assert "turn.started" in types
        assert "assistant.final" in types
        assert types[-1] == "done"

        deltas = [e for e in evts if e.get("type") == "assistant.delta"]
        joined = "".join(
            str((e.get("data") or {}).get("delta_text") or "") for e in deltas
        )
        assert joined == "hello ws"

        final = next(e for e in evts if e.get("type") == "assistant.final")
        final_data = final.get("data") or {}
        resp = final_data.get("response")
        assert isinstance(resp, dict)
        assert str(resp.get("text") or "") == "hello ws"
        pcs = resp.get("proposed_commands")
        assert isinstance(pcs, list) and pcs
        assert pcs[0].get("command") == "noop"
        assert (pcs[0].get("args") or {}).get("x") == 1
        assert resp.get("read_only") is True


def test_voice_realtime_ws_cancel_stops_turn(monkeypatch):
    monkeypatch.setenv("VOICE_REALTIME_WS_ENABLED", "true")

    async def _slow_route(self, *_args, **_kwargs):
        await asyncio.sleep(2.0)
        return AgentOutput(
            text="should_not_complete",
            proposed_commands=[],
            agent_id="ceo_advisor",
            read_only=True,
            trace={"dummy": True},
        )

    monkeypatch.setattr(
        "services.agent_router_service.AgentRouterService.route",
        _slow_route,
    )

    app = _load_app()
    client = TestClient(app)

    with client.websocket_connect("/api/voice/realtime/ws") as ws:
        ws.send_text(json.dumps({"type": "session.start", "data": {}}))
        _ = _recv_json(ws)

        ws.send_text(json.dumps({"type": "input.final", "data": {"text": "hello"}}))

        # Wait until the turn is acknowledged before cancelling.
        for _ in range(20):
            evt = _recv_json(ws)
            if evt.get("type") == "turn.started":
                break

        ws.send_text(json.dumps({"type": "control.cancel", "data": {}}))

        evts = _drain_until_done(ws)
        done = evts[-1]
        assert done.get("type") == "done"
        assert (done.get("data") or {}).get("ok") is False
        assert (done.get("data") or {}).get("reason") == "cancelled"

        assert not any(e.get("type") == "assistant.final" for e in evts)
