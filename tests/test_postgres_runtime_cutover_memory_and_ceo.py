from __future__ import annotations

import os
from typing import Any, Dict

import pytest
from fastapi.testclient import TestClient


def _pg_is_configured() -> bool:
    return bool((os.getenv("DATABASE_URL") or "").strip())


def _require_pg_memory_plane_tables() -> None:
    """Skip unless DATABASE_URL is set and memory-plane tables exist."""

    if not _pg_is_configured():
        pytest.skip("DATABASE_URL is not set; skipping postgres-mode runtime tests")

    try:
        from services.memory_postgres_backend import PostgresMemoryBackend

        pg = PostgresMemoryBackend()
        if not pg.is_configured():
            pytest.skip("PostgresMemoryBackend not configured")

        # Probe both conversation and memory tables.
        pg.get_conversation_turns(conversation_id="__probe__", max_turns=1)
        pg.get_last_memory_write()
    except Exception as exc:
        pytest.skip(
            f"Postgres memory plane is unavailable (migrations missing?): {exc}"
        )


def _load_app():
    try:
        from gateway.gateway_server import app  # type: ignore

        return app
    except Exception:
        from main import app  # type: ignore

        return app


def _grounding_pack_full() -> Dict[str, Any]:
    return {
        "enabled": True,
        "identity_pack": {"hash": "h", "payload": {"identity": {"name": "Adnan"}}},
        "kb_retrieved": {
            "used_entry_ids": ["sys_overview_001"],
            "entries": [
                {
                    "id": "sys_overview_001",
                    "title": "Šta je Adnan.AI",
                    "content": "Adnan.AI je ...",
                    "tags": ["system"],
                    "priority": 1.0,
                }
            ],
        },
        "notion_snapshot": {"status": "ok", "last_sync": "2026-01-01"},
        "memory_snapshot": {"hash": "m", "payload": {"notes": ["n1"]}},
    }


def test_postgres_ceo_conversation_continuity_no_file_fallback(monkeypatch, tmp_path):
    _require_pg_memory_plane_tables()

    monkeypatch.setenv("MEMORY_BACKEND", "postgres")
    monkeypatch.setenv("OPENAI_API_MODE", "responses")
    monkeypatch.setenv("CEO_ADVISOR_ALLOW_GENERAL_KNOWLEDGE", "1")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-live-local")

    state_path = tmp_path / "ceo_conv_state_should_not_be_used.json"
    monkeypatch.setenv("CEO_CONVERSATION_STATE_PATH", str(state_path))

    from services.grounding_pack_service import GroundingPackService

    monkeypatch.setattr(
        GroundingPackService, "build", lambda **_kwargs: _grounding_pack_full()
    )

    captured: Dict[str, Any] = {}

    class DummyExecutor:
        async def ceo_command(self, text, context):  # noqa: ANN001
            captured["instructions"] = (context or {}).get("instructions")
            return {"text": f"ack:{text}", "proposed_commands": []}

    monkeypatch.setattr(
        "services.agent_router.executor_factory.get_executor",
        lambda _purpose: DummyExecutor(),
    )

    app = _load_app()
    client = TestClient(app)

    conv_id = "pg-conv-001"

    r1 = client.post(
        "/api/chat",
        json={
            "message": "First memo: Project Alpha.",
            "conversation_id": conv_id,
            "session_id": "sess-pg-001",
            "snapshot": {"payload": {"tasks": [], "projects": [], "goals": []}},
        },
    )
    assert r1.status_code == 200

    r2 = client.post(
        "/api/chat",
        json={
            "message": "Second message.",
            "conversation_id": conv_id,
            "session_id": "sess-pg-001",
            "snapshot": {"payload": {"tasks": [], "projects": [], "goals": []}},
            "metadata": {"include_debug": True},
        },
    )
    assert r2.status_code == 200

    instr = captured.get("instructions")
    assert isinstance(instr, str) and instr.strip()
    assert "CONVERSATION_STATE:" in instr
    assert "First memo: Project Alpha" in instr

    # In postgres mode the legacy state file must not be written as SSOT.
    assert not state_path.exists()


def test_postgres_goal_context_persists_last_referenced_goal_id_roundtrip(monkeypatch):
    _require_pg_memory_plane_tables()

    monkeypatch.setenv("MEMORY_BACKEND", "postgres")
    monkeypatch.setenv("CEO_ADVISOR_FORCE_OFFLINE", "1")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-key")
    monkeypatch.setenv("CEO_NOTION_TARGETED_READS_ENABLED", "false")

    from gateway.gateway_server import app  # noqa: PLC0415
    from services.ceo_conversation_state_store import ConversationStateStore

    client = TestClient(app)

    conv_id = "pg-goal-context-001"
    sess_id = "pg-goal-context-001"

    snap1 = {
        "ready": True,
        "status": "fresh",
        "schema_version": "v1",
        "payload": {
            "goals": [
                {
                    "id": "g1",
                    "title": "EU Growth Goal",
                    "fields": {"status": "Blocked", "owner": ["cto@example.com"]},
                },
                {
                    "id": "g2",
                    "title": "EU Growth Goal",
                    "fields": {"status": "In Progress", "owner": ["ceo@example.com"]},
                },
            ],
            "tasks": [],
            "projects": [],
        },
    }

    r1 = client.post(
        "/api/chat",
        json={
            "message": "Koji je glavni cilj?",
            "conversation_id": conv_id,
            "session_id": sess_id,
            "snapshot": snap1,
            "metadata": {"include_debug": True},
        },
    )
    assert r1.status_code == 200, r1.text

    meta = ConversationStateStore.get_meta(conversation_id=conv_id)
    assert meta.get("last_referenced_goal_id") == "g1"

    # Rename the goal title in the next snapshot; ID stays stable.
    snap2 = {
        **snap1,
        "payload": {
            **snap1["payload"],
            "goals": [
                {
                    "id": "g1",
                    "title": "EU Growth Goal (RENAMED)",
                    "fields": {"status": "Blocked", "owner": ["cto@example.com"]},
                },
                {
                    "id": "g2",
                    "title": "EU Growth Goal",
                    "fields": {"status": "In Progress", "owner": ["ceo@example.com"]},
                },
            ],
        },
    }

    r2 = client.post(
        "/api/chat",
        json={
            "message": "Ko je zadužen za ovaj cilj?",
            "conversation_id": conv_id,
            "session_id": sess_id,
            "snapshot": snap2,
            "metadata": {"include_debug": True},
        },
    )
    assert r2.status_code == 200, r2.text
    txt = r2.json().get("text") or ""
    assert "cto@example.com" in txt
    assert "ceo@example.com" not in txt


def test_postgres_memory_read_after_write_is_restart_safe(monkeypatch):
    _require_pg_memory_plane_tables()

    monkeypatch.setenv("MEMORY_BACKEND", "postgres")

    from services.memory_service import MemoryService
    from services.memory_read_only import ReadOnlyMemoryService

    mem1 = MemoryService()

    payload = {
        "schema_version": "memory_write.v1",
        "idempotency_key": "idem_test_pg_read_after_write_001",
        "item": {
            "type": "note",
            "text": "PG canonical memory item",
            "tags": ["ceo"],
            "source": "test",
        },
        "grounded_on": ["KB:sys", "identity_pack.001"],
    }

    res = mem1.upsert_memory_write_v1(
        payload,
        approval_id="ap_test",
        execution_id=None,
        identity_id="id_test",
    )
    assert res.get("ok") is True

    # Simulate restart: new service instance must be able to read from Postgres.
    mem2 = MemoryService()
    ro2 = ReadOnlyMemoryService(mem2)

    items = ro2.get_recent_memory_items(limit=10)
    assert any((it.get("text") == "PG canonical memory item") for it in items)

    snap = ro2.export_public_snapshot()
    assert isinstance(snap, dict)
    assert snap.get("last_memory_write")


def test_file_backend_memory_read_after_write_compat(monkeypatch, tmp_path):
    monkeypatch.setenv("MEMORY_BACKEND", "file")
    monkeypatch.setenv("MEMORY_PATH", str(tmp_path / "mem"))

    from services.memory_service import MemoryService
    from services.memory_read_only import ReadOnlyMemoryService

    mem1 = MemoryService()

    payload = {
        "schema_version": "memory_write.v1",
        "idempotency_key": "idem_test_file_read_after_write_001",
        "item": {
            "type": "note",
            "text": "FILE canonical memory item",
            "tags": ["ceo"],
            "source": "test",
        },
        "grounded_on": ["KB:sys", "identity_pack.001"],
    }

    res = mem1.upsert_memory_write_v1(
        payload,
        approval_id="ap_test",
        execution_id=None,
        identity_id="id_test",
    )
    assert res.get("ok") is True

    mem2 = MemoryService()
    ro2 = ReadOnlyMemoryService(mem2)
    items = ro2.get_recent_memory_items(limit=10)
    assert any((it.get("text") == "FILE canonical memory item") for it in items)
