from __future__ import annotations

from typing import Any, Dict
from uuid import uuid4

from fastapi.testclient import TestClient


def test_gateway_fallback_zapamti_prisjeti_two_turn(monkeypatch):
    import gateway.gateway_server as gw

    async def _fake_ceo_command(_req):
        return {
            "ok": True,
            "text": "Nemam dovoljno signala u goals/projects/memory/snapshot da bih dao sedmične prioritete.",
            "proposed_commands": [],
            "trace": {},
        }

    monkeypatch.setattr(gw.ceo_console_module, "ceo_command", _fake_ceo_command)

    client = TestClient(gw.app)

    session_id = f"t-{uuid4()}"

    # Turn 1: store focus
    r1 = client.post(
        "/api/ceo/command",
        json={
            "text": "Zapamti: ove sedmice fokus je FLP landing + 10 leadova.",
            "data": {"session_id": session_id},
        },
    )
    assert r1.status_code == 200
    d1: Dict[str, Any] = r1.json()
    assert (d1.get("trace") or {}).get(
        "router_version"
    ) == "gateway-fallback-proposals-disabled-for-nonwrite-v1"
    assert d1.get("proposed_commands") == []
    assert d1.get("read_only") is True
    assert d1.get("summary") == d1.get("text")
    tr1 = d1.get("trace") or {}
    assert isinstance(tr1.get("used_sources"), list)
    assert isinstance(tr1.get("missing_inputs"), list)
    assert isinstance(tr1.get("notion_ops"), dict)
    assert isinstance(tr1.get("kb_ids_used"), list)

    # Turn 2: recall focus
    r2 = client.post(
        "/api/ceo/command",
        json={
            "text": "Koji fokus sedmice sam ti rekao u prethodnoj poruci?",
            "data": {"session_id": session_id},
        },
    )
    assert r2.status_code == 200
    d2: Dict[str, Any] = r2.json()
    assert d2.get("proposed_commands") == []
    assert d2.get("read_only") is True
    assert d2.get("summary") == d2.get("text")
    tr2 = d2.get("trace") or {}
    assert isinstance(tr2.get("used_sources"), list)
    assert isinstance(tr2.get("missing_inputs"), list)
    assert isinstance(tr2.get("notion_ops"), dict)
    assert isinstance(tr2.get("kb_ids_used"), list)

    assert d2.get("text") == "FLP landing + 10 leadova"
