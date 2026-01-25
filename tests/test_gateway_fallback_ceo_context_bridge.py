from __future__ import annotations

import json
from typing import Any, Dict

from fastapi.testclient import TestClient


def test_gateway_fallback_context_bridge_uses_context_and_llm(monkeypatch):
    import gateway.gateway_server as gw

    # Force gateway fallback router_version by returning empty proposed_commands
    # from the backend ceo_command and using a non-write prompt.
    async def _fake_backend_ceo_command(_req):
        return {
            "ok": True,
            "text": "Nemam dovoljno signala u goals/projects/memory/snapshot da bih dao sedmične prioritete.",
            "summary": "Nemam dovoljno signala u goals/projects/memory/snapshot da bih dao sedmične prioritete.",
            "proposed_commands": [],
            "trace": {},
        }

    monkeypatch.setattr(gw.ceo_console_module, "ceo_command", _fake_backend_ceo_command)

    # Patch SystemReadExecutor.snapshot (existing read context provider)
    def _fake_system_snapshot(self):  # noqa: ANN001
        return {
            "available": True,
            "generated_at": "2026-01-25T00:00:00Z",
            "identity_pack": {"available": True, "payload": {"company": "ACME"}},
            "knowledge_snapshot": {
                "ready": True,
                "payload": {"goals": [], "tasks": [], "projects": []},
            },
            "ceo_notion_snapshot": {
                "available": True,
                "dashboard": {"weekly_priority": "FLP landing"},
            },
            "trace": {},
        }

    monkeypatch.setattr(
        "services.system_read_executor.SystemReadExecutor.snapshot",
        _fake_system_snapshot,
    )

    # Patch ReadOnlyMemoryService.export_public_snapshot (existing memory provider)
    def _fake_mem_export(self):  # noqa: ANN001
        return {"active_decision": {"title": "zadnja odluka"}, "decision_outcomes": []}

    monkeypatch.setattr(
        "services.memory_read_only.ReadOnlyMemoryService.export_public_snapshot",
        _fake_mem_export,
    )

    # Patch GroundingPackService.build (existing KB retriever wrapper)
    def _fake_gp_build(**_kwargs):
        return {
            "enabled": True,
            "identity_pack": {"payload": {"company": "ACME"}},
            "kb_retrieved": {
                "entries": [{"id": "KB-123", "title": "Test", "content": "FLP"}],
                "used_entry_ids": ["KB-123"],
            },
            "notion_snapshot": {
                "ready": True,
                "payload": {"projects": [{"title": "FLP landing"}]},
            },
            "memory_snapshot": {
                "payload": {"active_decision": {"title": "zadnja odluka"}}
            },
            "trace": {"used_sources": ["kb_snapshot", "memory_snapshot"]},
        }

    monkeypatch.setattr(
        "services.grounding_pack_service.GroundingPackService.build", _fake_gp_build
    )

    # Patch CEO agent to avoid hitting OpenAI and to echo context deterministically.
    class _FakeAgentOut:
        def __init__(self, payload: Dict[str, Any]):
            self._payload = payload

        def model_dump(self, by_alias: bool = True):  # noqa: ANN001
            return self._payload

        def dict(self, by_alias: bool = True):  # noqa: ANN001
            return self._payload

    async def _fake_create_ceo_advisor_agent(agent_in, agent_ctx):  # noqa: ANN001
        gp = (agent_ctx or {}).get("grounding_pack") or {}
        kb_entries = (gp.get("kb_retrieved") or {}).get("entries") or []
        kb_id = (
            kb_entries[0].get("id")
            if kb_entries and isinstance(kb_entries[0], dict)
            else "KB-MISSING"
        )
        return _FakeAgentOut(
            {
                "text": f"Koristim KB:{kb_id} i projekat FLP landing.",
                "proposed_commands": [],
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
            "text": "Daj mi kratko stanje.",
            "data": {"session_id": "conv-bridge-001"},
        },
    )
    assert r.status_code == 200
    j: Dict[str, Any] = r.json()

    assert (j.get("trace") or {}).get(
        "router_version"
    ) == "gateway-fallback-proposals-disabled-for-nonwrite-v1"
    assert j.get("read_only") is True
    assert j.get("proposed_commands") == []

    pretty = json.dumps(j, ensure_ascii=False, indent=2, sort_keys=True)

    # Bridge should have run (even if it fails-soft, it must report in trace).
    assert "gateway_fallback_context_bridge" in (j.get("trace") or {}), pretty

    # Not the generic fallback.
    assert "Nemam dovoljno signala" not in (j.get("text") or ""), pretty
    # Must include at least one context element.
    assert "KB-123" in (j.get("text") or "") or "FLP landing" in (
        j.get("text") or ""
    ), pretty

    # Trace must explicitly state bridge use and missing keys.
    gb = (j.get("trace") or {}).get("gateway_fallback_context_bridge") or {}
    assert isinstance(gb, dict)
    assert "missing" in gb
    assert "used_sources" in gb

    # Canon: top-level trace should include provenance fields.
    tr = j.get("trace") or {}
    assert isinstance(tr, dict)
    assert isinstance(tr.get("used_sources"), list)
    assert isinstance(tr.get("missing_inputs"), list)
    assert isinstance(tr.get("notion_ops"), dict)
    assert isinstance(tr.get("kb_ids_used"), list)


def test_gateway_fallback_disarmed_strips_notion_only(monkeypatch):
    import gateway.gateway_server as gw

    async def _fake_ceo_command(_req):
        return {
            "ok": True,
            "text": "noop",
            "summary": "noop",
            "proposed_commands": [],
            "trace": {},
        }

    monkeypatch.setattr(gw.ceo_console_module, "ceo_command", _fake_ceo_command)

    async def _fake_get_state(_sid):  # noqa: ANN001
        return {"armed": False, "armed_at": None}

    async def _fake_is_armed(_sid):  # noqa: ANN001
        return False

    monkeypatch.setattr("services.notion_ops_state.get_state", _fake_get_state)
    monkeypatch.setattr("services.notion_ops_state.is_armed", _fake_is_armed)

    def _fake_ctx_bridge(*_args, **_kwargs):
        return {
            "snapshot": {"available": True},
            "identity_json": {"available": True, "payload": {"company": "ACME"}},
            "memory_stm": {"active_decision": {"title": "x"}},
            "grounding_pack": {
                "enabled": True,
                "identity_pack": {"payload": {"company": "ACME"}},
                "kb_retrieved": {"entries": [], "used_entry_ids": []},
                "notion_snapshot": {"ready": True, "payload": {}},
                "memory_snapshot": {"payload": {"active_decision": {"title": "x"}}},
                "trace": {"used_sources": ["memory_snapshot"]},
            },
            "missing": [],
            "trace": {},
        }

    monkeypatch.setattr(gw, "_build_ceo_read_context", _fake_ctx_bridge)

    class _FakeAgentOut:
        def __init__(self, payload: Dict[str, Any]):
            self._payload = payload

        def model_dump(self, by_alias: bool = True):  # noqa: ANN001
            return self._payload

        def dict(self, by_alias: bool = True):  # noqa: ANN001
            return self._payload

    async def _fake_create_ceo_advisor_agent(_agent_in, _agent_ctx):
        return _FakeAgentOut(
            {
                "text": "Predlažem dvije akcije.",
                "proposed_commands": [
                    {"command": "notion_write", "args": {"title": "X"}},
                    {
                        "command": gw.PROPOSAL_WRAPPER_INTENT,
                        "intent": "memory_write",
                        "args": {"k": "v"},
                    },
                ],
            }
        )

    monkeypatch.setattr(
        "services.ceo_advisor_agent.create_ceo_advisor_agent",
        _fake_create_ceo_advisor_agent,
    )

    client = TestClient(gw.app)
    r = client.post(
        "/api/ceo/command",
        json={"text": "Daj mi kratko stanje.", "data": {"session_id": "conv-gate-001"}},
    )
    assert r.status_code == 200
    j: Dict[str, Any] = r.json()

    pcs = j.get("proposed_commands")
    assert isinstance(pcs, list)
    assert all(isinstance(x, dict) for x in pcs)
    assert all((x.get("command") != "notion_write") for x in pcs)
    assert any((x.get("intent") == "memory_write") for x in pcs)

    tr = j.get("trace") or {}
    assert isinstance(tr.get("notion_ops_gate"), dict)
    assert tr.get("notion_ops_gate", {}).get("applied") is True


def test_gateway_fallback_trace_contract(monkeypatch):
    import gateway.gateway_server as gw

    async def _fake_ceo_command(_req):
        return {
            "ok": True,
            "text": "noop",
            "summary": "noop",
            "proposed_commands": [],
            "trace": {},
        }

    monkeypatch.setattr(gw.ceo_console_module, "ceo_command", _fake_ceo_command)

    async def _fake_get_state(_sid):  # noqa: ANN001
        return {"armed": False, "armed_at": None}

    async def _fake_is_armed(_sid):  # noqa: ANN001
        return False

    monkeypatch.setattr("services.notion_ops_state.get_state", _fake_get_state)
    monkeypatch.setattr("services.notion_ops_state.is_armed", _fake_is_armed)

    def _fake_ctx_bridge(*_args, **_kwargs):
        return {
            "snapshot": {"available": True},
            "identity_json": {"available": True, "payload": {"company": "ACME"}},
            "memory_stm": {"active_decision": {"title": "x"}},
            "grounding_pack": {
                "enabled": True,
                "identity_pack": {"payload": {"company": "ACME"}},
                "kb_retrieved": {
                    "entries": [{"id": "KB-1"}],
                    "used_entry_ids": ["KB-1"],
                },
                "notion_snapshot": {"ready": True, "payload": {}},
                "memory_snapshot": {"payload": {"active_decision": {"title": "x"}}},
                "trace": {"used_sources": ["kb_snapshot", "memory_snapshot"]},
            },
            "missing": [],
            "trace": {},
        }

    monkeypatch.setattr(gw, "_build_ceo_read_context", _fake_ctx_bridge)

    class _FakeAgentOut:
        def __init__(self, payload: Dict[str, Any]):
            self._payload = payload

        def model_dump(self, by_alias: bool = True):  # noqa: ANN001
            return self._payload

        def dict(self, by_alias: bool = True):  # noqa: ANN001
            return self._payload

    async def _fake_create_ceo_advisor_agent(_agent_in, _agent_ctx):
        return _FakeAgentOut({"text": "OK", "proposed_commands": [], "trace": {}})

    monkeypatch.setattr(
        "services.ceo_advisor_agent.create_ceo_advisor_agent",
        _fake_create_ceo_advisor_agent,
    )

    client = TestClient(gw.app)
    r = client.post(
        "/api/ceo/command",
        json={
            "text": "Daj mi kratko stanje.",
            "data": {"session_id": "conv-trace-001"},
        },
    )
    assert r.status_code == 200
    j: Dict[str, Any] = r.json()

    tr = j.get("trace") or {}
    assert isinstance(tr, dict)
    assert isinstance(tr.get("used_sources"), list)
    assert isinstance(tr.get("missing_inputs"), list)
    assert isinstance(tr.get("notion_ops"), dict)
    assert isinstance(tr.get("kb_ids_used"), list)
    assert "KB-1" in tr.get("kb_ids_used")


def test_gateway_fallback_missing_grounding_blocks(monkeypatch):
    import gateway.gateway_server as gw

    monkeypatch.setenv("OPENAI_API_MODE", "responses")

    async def _fake_ceo_command(_req):
        return {
            "ok": True,
            "text": "noop",
            "summary": "noop",
            "proposed_commands": [],
            "trace": {},
        }

    monkeypatch.setattr(gw.ceo_console_module, "ceo_command", _fake_ceo_command)

    def _fake_system_snapshot(self):  # noqa: ANN001
        return {
            "available": True,
            "generated_at": "2026-01-25T00:00:00Z",
            "identity_pack": {"available": True, "payload": {"company": "ACME"}},
            "knowledge_snapshot": {
                "ready": True,
                "payload": {"goals": [], "tasks": [], "projects": []},
            },
            "ceo_notion_snapshot": {
                "available": True,
                "dashboard": {"weekly_priority": "FLP landing"},
            },
            "trace": {},
        }

    monkeypatch.setattr(
        "services.system_read_executor.SystemReadExecutor.snapshot",
        _fake_system_snapshot,
    )

    def _fake_mem_export(self):  # noqa: ANN001
        return {"active_decision": {"title": "zadnja odluka"}, "decision_outcomes": []}

    monkeypatch.setattr(
        "services.memory_read_only.ReadOnlyMemoryService.export_public_snapshot",
        _fake_mem_export,
    )

    # Build an intentionally insufficient grounding pack (missing memory_snapshot).
    def _fake_gp_build(**_kwargs):
        return {
            "enabled": True,
            "identity_pack": {"payload": {"company": "ACME"}},
            "kb_retrieved": {"entries": []},
            "notion_snapshot": {"ready": True, "payload": {}},
            # memory_snapshot missing => should trigger CEO Advisor Responses guard
        }

    monkeypatch.setattr(
        "services.grounding_pack_service.GroundingPackService.build", _fake_gp_build
    )

    # Ensure we do not accidentally call the executor in this path.
    monkeypatch.setattr(
        "services.agent_router.executor_factory.get_executor",
        lambda purpose=None: (_ for _ in ()).throw(
            AssertionError("executor should not be called")
        ),
    )

    client = TestClient(gw.app)
    r = client.post(
        "/api/ceo/command",
        json={"text": "Daj mi kratko stanje.", "data": {"session_id": "conv-mg-001"}},
    )
    assert r.status_code == 200
    j: Dict[str, Any] = r.json()
    tr = j.get("trace") or {}
    assert tr.get("exit_reason") == "blocked.missing_grounding"
