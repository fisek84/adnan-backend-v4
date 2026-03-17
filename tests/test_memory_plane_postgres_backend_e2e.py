from __future__ import annotations

import os
import time
import uuid

import pytest
import sqlalchemy as sa

from services.ceo_conversation_state_store import ConversationStateStore
from services.memory_service import MemoryService


def _db_url() -> str:
    return (os.getenv("DATABASE_URL") or "").strip()


def _pg_enabled() -> bool:
    return (os.getenv("MEMORY_BACKEND") or "").strip().lower() == "postgres"


def _require_pg() -> sa.Engine:
    if not _pg_enabled():
        pytest.skip("MEMORY_BACKEND!=postgres; skipping Postgres memory-plane tests")

    url = _db_url()
    if not url:
        pytest.skip("DATABASE_URL not set; skipping Postgres memory-plane tests")

    eng = sa.create_engine(url, pool_pre_ping=True, future=True)

    try:
        with eng.connect() as conn:
            conn.execute(sa.text("SELECT 1"))
    except Exception:
        pytest.skip("DATABASE_URL not reachable; skipping Postgres memory-plane tests")

    return eng


def _tables_present(engine: sa.Engine) -> bool:
    needed = {
        "memory_item",
        "memory_scope_kv",
        "conversation_turn",
        "conversation_meta_kv",
    }
    try:
        insp = sa.inspect(engine)
        tables = set(insp.get_table_names(schema="public"))
        return needed.issubset(tables)
    except Exception:
        return False


def test_pg_memory_write_v1_persists_to_memory_item():
    eng = _require_pg()
    if not _tables_present(eng):
        pytest.skip("memory-plane tables not migrated; run alembic upgrade head")

    idem = f"pytest_{uuid.uuid4().hex}"

    mem = MemoryService()
    payload = {
        "schema_version": "memory_write.v1",
        "idempotency_key": idem,
        "grounded_on": ["KB:memory_model_001", "identity_pack.user_id:test"],
        "item": {
            "type": "fact",
            "text": f"pg write marker {idem}",
            "tags": ["pytest", "pg"],
            "source": "user",
        },
    }

    res = mem.upsert_memory_write_v1(
        payload,
        approval_id="pytest_approval",
        execution_id=None,
        identity_id="pytest_identity",
    )
    assert isinstance(res, dict)
    assert res.get("ok") is True

    with eng.connect() as conn:
        row = (
            conn.execute(
                sa.text(
                    "SELECT stored_id, item_text FROM memory_item WHERE idempotency_key = :idem LIMIT 1"
                ),
                {"idem": idem},
            )
            .mappings()
            .first()
        )

    assert row is not None
    assert isinstance(row.get("stored_id"), str) and row.get("stored_id")
    assert row.get("item_text") == f"pg write marker {idem}"


def test_pg_scoped_kv_persists_to_memory_scope_kv():
    eng = _require_pg()
    if not _tables_present(eng):
        pytest.skip("memory-plane tables not migrated; run alembic upgrade head")

    scope_id = f"pytest_scope_{uuid.uuid4().hex}"
    key = "k1"
    value = {"hello": "world", "n": 1}

    mem = MemoryService()
    ok = mem.set(scope_type="session", scope_id=scope_id, key=key, value=value)
    assert ok is True

    with eng.connect() as conn:
        row = (
            conn.execute(
                sa.text(
                    """
                    SELECT value
                    FROM memory_scope_kv
                    WHERE scope_type = 'session' AND scope_id = :sid AND key = :k
                    LIMIT 1
                    """
                ),
                {"sid": scope_id, "k": key},
            )
            .mappings()
            .first()
        )

    assert row is not None
    assert row.get("value") == value


def test_pg_conversation_turn_and_meta_persist_and_roundtrip_last_referenced_goal_id():
    eng = _require_pg()
    if not _tables_present(eng):
        pytest.skip("memory-plane tables not migrated; run alembic upgrade head")

    cid = f"pytest_conv_{uuid.uuid4().hex}"

    ConversationStateStore.append_turn(
        conversation_id=cid,
        user_text="U",
        assistant_text="A",
        max_turns=10,
    )

    goal_id = "g_test_123"
    ConversationStateStore.update_meta(
        conversation_id=cid,
        updates={
            "last_referenced_goal_id": goal_id,
            "last_referenced_goal_title": "Display Title",
            "last_referenced_goal_at": float(time.time()),
        },
    )

    meta = ConversationStateStore.get_meta(conversation_id=cid)
    assert isinstance(meta, dict)
    assert meta.get("last_referenced_goal_id") == goal_id

    with eng.connect() as conn:
        turn = (
            conn.execute(
                sa.text(
                    """
                    SELECT conversation_id
                    FROM conversation_turn
                    WHERE conversation_id = :cid
                    LIMIT 1
                    """
                ),
                {"cid": cid},
            )
            .mappings()
            .first()
        )
        kv = (
            conn.execute(
                sa.text(
                    """
                    SELECT value
                    FROM conversation_meta_kv
                    WHERE conversation_id = :cid AND key = 'last_referenced_goal_id'
                    LIMIT 1
                    """
                ),
                {"cid": cid},
            )
            .mappings()
            .first()
        )

    assert turn is not None
    assert kv is not None
    assert kv.get("value") == goal_id
