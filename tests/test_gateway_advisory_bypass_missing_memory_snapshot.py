from __future__ import annotations

import json
from typing import Any, Dict

from fastapi.testclient import TestClient


class _FakeAgentOut:
    def __init__(self, payload: Dict[str, Any]):
        self._payload = payload

    def model_dump(self, by_alias: bool = True):  # noqa: ANN001
        return self._payload

    def dict(self, by_alias: bool = True):  # noqa: ANN001
        return self._payload


def _force_gateway_fallback_router(monkeypatch):
    import gateway.gateway_server as gw

    async def _fake_backend_ceo_command(_req):  # noqa: ANN001
        return {
            "ok": True,
            "text": "noop",
            "summary": "noop",
            "proposed_commands": [],
            "trace": {},
        }

    monkeypatch.setattr(gw.ceo_console_module, "ceo_command", _fake_backend_ceo_command)

    return gw


def _ctx_bridge_missing_memory_snapshot() -> Dict[str, Any]:
    return {
        "snapshot": {"ready": True, "payload": {}},
        "identity_json": {"available": True, "payload": {"company": "ACME"}},
        "memory_stm": {"active_decision": {"title": "x"}},
        "grounding_pack": {
            "enabled": True,
            "identity_pack": {"payload": {"company": "ACME"}},
            "kb_retrieved": {"entries": [], "used_entry_ids": []},
            "notion_snapshot": {},
            # Intentionally omit memory_snapshot to simulate the prod blocker.
            "trace": {"used_sources": ["kb_snapshot"]},
        },
        "kb_hits": [],
        "missing": [],
        "trace": {},
    }


def test_gateway_advisory_bypass_missing_memory_snapshot_a(monkeypatch):
    gw = _force_gateway_fallback_router(monkeypatch)

    monkeypatch.setenv("OPENAI_API_MODE", "responses")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("CEO_ADVISOR_ALLOW_GENERAL_KNOWLEDGE", "0")

    monkeypatch.setattr(
        gw,
        "_build_ceo_read_context",
        lambda **_k: _ctx_bridge_missing_memory_snapshot(),
    )

    async def _fake_create_ceo_advisor_agent(_agent_in, _agent_ctx):  # noqa: ANN001
        return _FakeAgentOut(
            {
                "text": "- Korak 1: Definiši cilj\n- Korak 2: Napravi plan\n- Korak 3: Prvi sljedeći korak",
                "proposed_commands": [],
                "read_only": True,
                "trace": {"exit_reason": "llm.success"},
            }
        )

    monkeypatch.setattr(
        "services.ceo_advisor_agent.create_ceo_advisor_agent",
        _fake_create_ceo_advisor_agent,
    )

    client = TestClient(gw.app)
    r = client.post(
        "/api/ceo/command",
        headers={"X-Initiator": "ceo_dashboard"},
        json={
            "text": "Kako da upravljam mislima i napravim bolji plan",
            "data": {"session_id": "gw-adv-1"},
        },
    )
    assert r.status_code == 200
    j: Dict[str, Any] = r.json()

    pretty = json.dumps(j, ensure_ascii=False, indent=2, sort_keys=True)

    txt = j.get("text") or ""
    assert "ne mogu dati smislen odgovor" not in txt.lower(), pretty
    assert "\n-" in txt, pretty

    assert j.get("read_only") is True
    assert j.get("proposed_commands") == []

    tr = j.get("trace") or {}
    assert (
        tr.get("router_version") or ""
    ) == "gateway-fallback-proposals-disabled-for-nonwrite-v1"


def test_gateway_advisory_bypass_missing_memory_snapshot_b(monkeypatch):
    gw = _force_gateway_fallback_router(monkeypatch)

    monkeypatch.setenv("OPENAI_API_MODE", "responses")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("CEO_ADVISOR_ALLOW_GENERAL_KNOWLEDGE", "0")

    monkeypatch.setattr(
        gw,
        "_build_ceo_read_context",
        lambda **_k: _ctx_bridge_missing_memory_snapshot(),
    )

    async def _fake_create_ceo_advisor_agent(_agent_in, _agent_ctx):  # noqa: ANN001
        return _FakeAgentOut(
            {
                "text": "- Korak 1: Postavi kriterije\n- Korak 2: Fokus blok 25 min\n- Korak 3: Donosi odluku",
                "proposed_commands": [],
                "read_only": True,
                "trace": {"exit_reason": "llm.success"},
            }
        )

    monkeypatch.setattr(
        "services.ceo_advisor_agent.create_ceo_advisor_agent",
        _fake_create_ceo_advisor_agent,
    )

    client = TestClient(gw.app)
    r = client.post(
        "/api/ceo/command",
        headers={"X-Initiator": "ceo_dashboard"},
        json={
            "text": "Kako da poboljšam fokus i donesem bolju odluku",
            "data": {"session_id": "gw-adv-2"},
        },
    )
    assert r.status_code == 200
    j: Dict[str, Any] = r.json()

    pretty = json.dumps(j, ensure_ascii=False, indent=2, sort_keys=True)

    txt = j.get("text") or ""
    assert "ne mogu dati smislen odgovor" not in txt.lower(), pretty
    assert "\n-" in txt, pretty

    assert j.get("read_only") is True
    assert j.get("proposed_commands") == []


def test_gateway_fact_lookup_missing_memory_snapshot_still_returns_canonical_no_answer(
    monkeypatch,
):
    gw = _force_gateway_fallback_router(monkeypatch)

    monkeypatch.setenv("OPENAI_API_MODE", "responses")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("CEO_ADVISOR_ALLOW_GENERAL_KNOWLEDGE", "0")

    monkeypatch.setattr(
        gw,
        "_build_ceo_read_context",
        lambda **_k: _ctx_bridge_missing_memory_snapshot(),
    )

    async def _boom(*_a, **_k):  # noqa: ANN001
        raise AssertionError(
            "CEO advisor agent must not be called for fact lookup blocked at gateway"
        )

    monkeypatch.setattr("services.ceo_advisor_agent.create_ceo_advisor_agent", _boom)

    client = TestClient(gw.app)
    r = client.post(
        "/api/ceo/command",
        headers={"X-Initiator": "ceo_dashboard"},
        json={
            "text": "Koji je glavni grad Francuske?",
            "data": {"session_id": "gw-fact-1"},
        },
    )
    assert r.status_code == 200
    j: Dict[str, Any] = r.json()

    txt = j.get("text") or ""
    assert "Ne mogu dati smislen odgovor" in txt
    assert j.get("read_only") is True
    assert j.get("proposed_commands") == []

    pretty = json.dumps(j, ensure_ascii=False, indent=2, sort_keys=True)
    assert "gateway_fallback_context_bridge" in (j.get("trace") or {}), pretty
