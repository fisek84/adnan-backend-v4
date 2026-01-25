from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi.testclient import TestClient


def _mk_ctx_bridge(*, kb_ids: list[str] | None = None) -> Dict[str, Any]:
    kb_ids = kb_ids or ["KB-789"]
    return {
        "snapshot": {"available": True, "ceo": {"weekly_priority": "FLP"}},
        "identity_json": {"available": True, "payload": {"company": "ACME"}},
        "memory_stm": {"active_decision": {"title": "zadnja odluka"}},
        "grounding_pack": {
            "enabled": True,
            "identity_pack": {"payload": {"company": "ACME"}},
            "kb_retrieved": {
                "entries": [{"id": kb_ids[0], "title": "T", "content": "C"}],
                "used_entry_ids": kb_ids,
            },
            "notion_snapshot": {
                "ready": True,
                "payload": {"projects": [{"title": "FLP"}]},
            },
            "memory_snapshot": {
                "payload": {"active_decision": {"title": "zadnja odluka"}}
            },
            "trace": {
                "used_sources": [
                    "identity_pack",
                    "notion_snapshot",
                    "kb_snapshot",
                    "memory_snapshot",
                ]
            },
        },
        "conversation_state": {"turn": 1},
        "missing": [],
        "trace": {
            "used_sources": [
                "identity_pack",
                "notion_snapshot",
                "kb_snapshot",
                "memory_snapshot",
            ]
        },
    }


def test_gateway_fallback_bridge_injects_context_and_trace_contract(monkeypatch):
    import gateway.gateway_server as gw

    # Force gateway fallback router_version by returning empty proposed_commands
    # from the backend ceo_command and using a non-write prompt.
    async def _fake_backend_ceo_command(_req):
        return {
            "ok": True,
            "text": "noop",
            "summary": "noop",
            "proposed_commands": [],
            "trace": {},
        }

    monkeypatch.setattr(gw.ceo_console_module, "ceo_command", _fake_backend_ceo_command)

    # Disarmed Notion Ops.
    async def _fake_get_state(_sid):  # noqa: ANN001
        return {"armed": False, "armed_at": None}

    async def _fake_is_armed(_sid):  # noqa: ANN001
        return False

    monkeypatch.setattr("services.notion_ops_state.get_state", _fake_get_state)
    monkeypatch.setattr("services.notion_ops_state.is_armed", _fake_is_armed)

    # Provide deterministic read-context bridge.
    monkeypatch.setattr(gw, "_build_ceo_read_context", lambda *a, **k: _mk_ctx_bridge())

    captured: Dict[str, Any] = {}

    class _FakeExecutor:
        async def ceo_command(self, prompt: str, ctx: Dict[str, Any]):  # noqa: ANN001
            captured["prompt"] = prompt
            captured["ctx"] = ctx
            return {
                "text": "Predlažem dvije akcije.",
                "proposed_commands": [
                    {"command": "notion_write", "args": {"title": "X"}},
                    {
                        "command": gw.PROPOSAL_WRAPPER_INTENT,
                        "intent": "memory_write",
                        "args": {"k": "v"},
                    },
                ],
                "trace": {"intent": "status", "exit_reason": "ok"},
            }

    def _fake_get_executor(*, purpose: Optional[str] = None):
        captured["purpose"] = purpose
        return _FakeExecutor()

    monkeypatch.setattr(
        "services.agent_router.executor_factory.get_executor", _fake_get_executor
    )

    client = TestClient(gw.app)
    r = client.post(
        "/api/ceo/command",
        headers={"X-Initiator": "ceo_dashboard"},
        json={"text": "Daj mi kratko stanje.", "data": {"session_id": "conv-e2e-001"}},
    )

    assert r.status_code == 200
    j: Dict[str, Any] = r.json()

    # Fallback route selected.
    assert (j.get("trace") or {}).get(
        "router_version"
    ) == "gateway-fallback-proposals-disabled-for-nonwrite-v1"
    assert j.get("read_only") is True

    # Executor got the governed context packs.
    assert captured.get("purpose") == "ceo_advisor"
    ex_ctx = captured.get("ctx")
    assert isinstance(ex_ctx, dict)
    assert isinstance(ex_ctx.get("grounding_pack"), dict)
    assert isinstance(ex_ctx.get("identity_pack"), dict)
    assert isinstance(ex_ctx.get("snapshot"), dict)
    assert isinstance(ex_ctx.get("memory"), dict)
    # conversation_state is optional in executor context (may be injected elsewhere).
    if "conversation_state" in ex_ctx:
        assert isinstance(ex_ctx.get("conversation_state"), (dict, type(None)))
    assert (ex_ctx.get("metadata") or {}).get("initiator") == "gateway_fallback"
    assert (ex_ctx.get("metadata") or {}).get("session_id") == "conv-e2e-001"

    # Notion Ops disarmed: strip only Notion writes, keep memory_write.
    pcs = j.get("proposed_commands")
    assert isinstance(pcs, list)
    assert all(isinstance(x, dict) for x in pcs)
    assert all((x.get("command") != "notion_write") for x in pcs)
    assert any((x.get("intent") == "memory_write") for x in pcs)

    # Trace contract must be present.
    tr = j.get("trace") or {}
    assert isinstance(tr, dict)
    assert isinstance(tr.get("used_sources"), list)
    assert isinstance(tr.get("missing_inputs"), list)
    assert isinstance(tr.get("notion_ops"), dict)
    assert isinstance(tr.get("kb_ids_used"), list)
    assert "KB-789" in tr.get("kb_ids_used")

    # If gating happened, it must be explicitly recorded.
    assert isinstance(tr.get("notion_ops_gate"), dict)
    assert tr.get("notion_ops_gate", {}).get("applied") is True


def test_gateway_fallback_bridge_allows_notion_write_when_armed(monkeypatch):
    import gateway.gateway_server as gw

    async def _fake_backend_ceo_command(_req):
        return {
            "ok": True,
            "text": "noop",
            "summary": "noop",
            "proposed_commands": [],
            "trace": {},
        }

    monkeypatch.setattr(gw.ceo_console_module, "ceo_command", _fake_backend_ceo_command)

    # Armed Notion Ops.
    async def _fake_get_state(_sid):  # noqa: ANN001
        return {"armed": True, "armed_at": "2026-01-25T00:00:00Z"}

    async def _fake_is_armed(_sid):  # noqa: ANN001
        return True

    monkeypatch.setattr("services.notion_ops_state.get_state", _fake_get_state)
    monkeypatch.setattr("services.notion_ops_state.is_armed", _fake_is_armed)

    monkeypatch.setattr(
        gw, "_build_ceo_read_context", lambda *a, **k: _mk_ctx_bridge(kb_ids=["KB-900"])
    )

    class _FakeExecutor:
        async def ceo_command(self, prompt: str, ctx: Dict[str, Any]):  # noqa: ANN001
            return {
                "text": "OK",
                "proposed_commands": [
                    {"command": "notion_write", "args": {"title": "X"}},
                    {
                        "command": gw.PROPOSAL_WRAPPER_INTENT,
                        "intent": "memory_write",
                        "args": {"k": "v"},
                    },
                ],
                "trace": {"intent": "status", "exit_reason": "ok"},
            }

    monkeypatch.setattr(
        "services.agent_router.executor_factory.get_executor",
        lambda purpose=None: _FakeExecutor(),
    )

    client = TestClient(gw.app)
    r = client.post(
        "/api/ceo/command",
        json={
            "text": "Daj mi kratko stanje.",
            "data": {"session_id": "conv-e2e-armed-001"},
        },
    )

    assert r.status_code == 200
    j: Dict[str, Any] = r.json()

    pcs = j.get("proposed_commands")
    assert isinstance(pcs, list)
    assert any((x.get("command") == "notion_write") for x in pcs)

    tr = j.get("trace") or {}
    assert isinstance(tr.get("notion_ops"), dict)
    assert tr.get("notion_ops", {}).get("armed") is True
    assert "KB-900" in (tr.get("kb_ids_used") or [])
