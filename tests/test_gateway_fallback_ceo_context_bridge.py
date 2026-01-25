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
                "entries": [{"id": "KB-123", "title": "Test", "content": "FLP"}]
            },
            "notion_snapshot": {
                "ready": True,
                "payload": {"projects": [{"title": "FLP landing"}]},
            },
            "memory_snapshot": {
                "payload": {"active_decision": {"title": "zadnja odluka"}}
            },
        }

    monkeypatch.setattr(
        "services.grounding_pack_service.GroundingPackService.build", _fake_gp_build
    )

    # Patch the LLM executor selection to a fake that echoes context IDs deterministically.
    class _FakeExecutor:
        async def ceo_command(self, text, context):  # noqa: ANN001
            # Ensure we can see that context was wired.
            gp = (context or {}).get("grounding_pack") or {}
            kb_entries = (gp.get("kb_retrieved") or {}).get("entries") or []
            kb_id = (
                kb_entries[0].get("id")
                if kb_entries and isinstance(kb_entries[0], dict)
                else "KB-MISSING"
            )
            return {
                "text": f"Koristim KB:{kb_id} i projekat FLP landing.",
                "proposed_commands": [],
            }

    monkeypatch.setattr(
        "services.agent_router.executor_factory.get_executor",
        lambda purpose=None: _FakeExecutor(),
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
