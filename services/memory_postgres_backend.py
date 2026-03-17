from __future__ import annotations

import os
import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import sqlalchemy as sa


class PostgresBackendUnavailable(RuntimeError):
    pass


def _env_first(name: str) -> str:
    return (os.getenv(name) or "").strip()


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class MemoryWriteRecord:
    stored_id: str
    idempotency_key: str
    item_type: str
    item_text: str
    item_tags: List[str]
    item_source: str
    grounded_on: List[str]
    approval_id: str
    execution_id: Optional[str]
    identity_id: str


class PostgresMemoryBackend:
    """Minimal Postgres backend for the memory plane.

    Scope of this module is intentionally narrow:
    - memory_write.v1 sink (+ optional audit event)
    - scoped KV
    - CEO conversation turns + meta

    It is designed to be called from existing services via a feature flag.
    """

    def __init__(self, *, database_url: Optional[str] = None) -> None:
        self._database_url = (database_url or _env_first("DATABASE_URL")).strip()
        self._engine: sa.Engine | None = None

    def is_configured(self) -> bool:
        return bool(self._database_url)

    def _get_engine(self) -> sa.Engine:
        if not self._database_url:
            raise PostgresBackendUnavailable("DATABASE_URL is not set")
        if self._engine is None:
            self._engine = sa.create_engine(
                self._database_url,
                pool_pre_ping=True,
                future=True,
            )
        return self._engine

    # ------------------------------------------------------------
    # memory_item (memory_write.v1)
    # ------------------------------------------------------------
    def upsert_memory_item(self, rec: MemoryWriteRecord) -> Dict[str, Any]:
        """Idempotent insert by idempotency_key, returns stored_id + created_at."""

        eng = self._get_engine()

        insert_sql = sa.text(
            """
            INSERT INTO memory_item (
                stored_id,
                idempotency_key,
                schema_version,
                item_type,
                item_text,
                item_tags,
                item_source,
                grounded_on,
                approval_id,
                execution_id,
                identity_id
            ) VALUES (
                :stored_id,
                :idempotency_key,
                'memory_write.v1',
                :item_type,
                :item_text,
                CAST(:item_tags AS jsonb),
                :item_source,
                CAST(:grounded_on AS jsonb),
                :approval_id,
                :execution_id,
                :identity_id
            )
            ON CONFLICT (idempotency_key)
            DO NOTHING
            RETURNING stored_id, created_at
            """
        )

        select_sql = sa.text(
            """
            SELECT stored_id, created_at
            FROM memory_item
            WHERE idempotency_key = :idempotency_key
            LIMIT 1
            """
        )

        params = {
            "stored_id": rec.stored_id,
            "idempotency_key": rec.idempotency_key,
            "item_type": rec.item_type,
            "item_text": rec.item_text,
            "item_tags": json.dumps(rec.item_tags),
            "item_source": rec.item_source,
            "grounded_on": json.dumps(rec.grounded_on),
            "approval_id": rec.approval_id,
            "execution_id": rec.execution_id,
            "identity_id": rec.identity_id,
        }

        with eng.begin() as conn:
            row = conn.execute(insert_sql, params).mappings().first()
            if row is None:
                row = (
                    conn.execute(select_sql, {"idempotency_key": rec.idempotency_key})
                    .mappings()
                    .first()
                )

        if not row:
            raise PostgresBackendUnavailable("memory_item upsert returned no row")

        created_at = row.get("created_at")
        if isinstance(created_at, datetime):
            created_at_iso = created_at.astimezone(timezone.utc).isoformat()
        else:
            created_at_iso = _utc_now_iso()

        return {
            "stored_id": row.get("stored_id"),
            "created_at": created_at_iso,
        }

    def get_recent_memory_items(self, *, limit: int) -> List[Dict[str, Any]]:
        if not isinstance(limit, int) or limit <= 0:
            return []

        eng = self._get_engine()
        sql = sa.text(
            """
            SELECT
                stored_id,
                idempotency_key,
                item_type,
                item_text,
                item_tags,
                item_source,
                grounded_on,
                approval_id,
                execution_id,
                identity_id,
                created_at
            FROM memory_item
            ORDER BY created_at DESC
            LIMIT :limit
            """
        )

        out: List[Dict[str, Any]] = []
        with eng.connect() as conn:
            rows = conn.execute(sql, {"limit": int(limit)}).mappings().all()

        for r in reversed(list(rows)):
            created_at = r.get("created_at")
            created_at_iso = (
                created_at.astimezone(timezone.utc).isoformat()
                if isinstance(created_at, datetime)
                else None
            )

            out.append(
                {
                    "stored_id": r.get("stored_id"),
                    "schema_version": "memory_write.v1",
                    "idempotency_key": r.get("idempotency_key"),
                    "item": {
                        "type": r.get("item_type"),
                        "text": r.get("item_text"),
                        "tags": list(r.get("item_tags") or []),
                        "source": r.get("item_source"),
                    },
                    "grounded_on": list(r.get("grounded_on") or []),
                    "approval_id": r.get("approval_id"),
                    "execution_id": r.get("execution_id"),
                    "identity_id": r.get("identity_id"),
                    "created_at": created_at_iso,
                }
            )

        return out

    def get_last_memory_write(self) -> Optional[str]:
        eng = self._get_engine()
        sql = sa.text("SELECT max(created_at) AS mx FROM memory_item")
        with eng.connect() as conn:
            row = conn.execute(sql).mappings().first()
        if not row:
            return None
        mx = row.get("mx")
        if isinstance(mx, datetime):
            return mx.astimezone(timezone.utc).isoformat()
        return None

    # ------------------------------------------------------------
    # memory_write_audit_event
    # ------------------------------------------------------------
    def insert_audit_event(self, event: Dict[str, Any]) -> None:
        if not isinstance(event, dict):
            return

        eng = self._get_engine()
        sql = sa.text(
            """
            INSERT INTO memory_write_audit_event (
                op, approval_id, execution_id, identity_id, stored_id, ok, source, payload
            ) VALUES (
                :op, :approval_id, :execution_id, :identity_id, :stored_id, :ok, :source, CAST(:payload AS jsonb)
            )
            """
        )

        params = {
            "op": (event.get("op") or "").strip() or "write",
            "approval_id": event.get("approval_id"),
            "execution_id": event.get("execution_id"),
            "identity_id": event.get("identity_id"),
            "stored_id": event.get("stored_id"),
            "ok": bool(event.get("ok") is True),
            "source": event.get("source"),
            "payload": json.dumps(event.get("payload")) if "payload" in event else None,
        }

        with eng.begin() as conn:
            conn.execute(sql, params)

    # ------------------------------------------------------------
    # memory_scope_kv (scoped KV)
    # ------------------------------------------------------------
    def get_scope_kv(
        self, *, scope_type: str, scope_id: str, key: str
    ) -> Optional[Dict[str, Any]]:
        eng = self._get_engine()

        sql = sa.text(
            """
            SELECT value, ts_unix, exp_unix, meta
            FROM memory_scope_kv
            WHERE scope_type = :scope_type AND scope_id = :scope_id AND key = :key
            LIMIT 1
            """
        )

        with eng.connect() as conn:
            row = (
                conn.execute(
                    sql,
                    {"scope_type": scope_type, "scope_id": scope_id, "key": key},
                )
                .mappings()
                .first()
            )

        if not row:
            return None

        exp = row.get("exp_unix")
        if isinstance(exp, (int, float)) and exp <= time.time():
            # Best-effort cleanup
            try:
                self.delete_scope_kv(scope_type=scope_type, scope_id=scope_id, key=key)
            except Exception:
                pass
            return None

        return {
            "value": row.get("value"),
            "ts": row.get("ts_unix"),
            "exp": row.get("exp_unix"),
            "meta": row.get("meta") or {},
        }

    def upsert_scope_kv(
        self,
        *,
        scope_type: str,
        scope_id: str,
        key: str,
        value: Any,
        exp_unix: Optional[float],
        meta: Dict[str, Any],
    ) -> None:
        eng = self._get_engine()

        sql = sa.text(
            """
            INSERT INTO memory_scope_kv (
                scope_type, scope_id, key, value, ts_unix, exp_unix, meta
            ) VALUES (
                :scope_type, :scope_id, :key, CAST(:value AS jsonb), :ts_unix, :exp_unix, CAST(:meta AS jsonb)
            )
            ON CONFLICT (scope_type, scope_id, key)
            DO UPDATE SET
                value = excluded.value,
                ts_unix = excluded.ts_unix,
                exp_unix = excluded.exp_unix,
                meta = excluded.meta
            """
        )

        params = {
            "scope_type": scope_type,
            "scope_id": scope_id,
            "key": key,
            "value": json.dumps(value),
            "ts_unix": float(time.time()),
            "exp_unix": exp_unix,
            "meta": json.dumps(meta or {}),
        }

        with eng.begin() as conn:
            conn.execute(sql, params)

    def delete_scope_kv(self, *, scope_type: str, scope_id: str, key: str) -> int:
        eng = self._get_engine()
        sql = sa.text(
            """
            DELETE FROM memory_scope_kv
            WHERE scope_type = :scope_type AND scope_id = :scope_id AND key = :key
            """
        )
        with eng.begin() as conn:
            res = conn.execute(
                sql,
                {"scope_type": scope_type, "scope_id": scope_id, "key": key},
            )
        return int(getattr(res, "rowcount", 0) or 0)

    def clear_scope(self, *, scope_type: str, scope_id: str) -> int:
        eng = self._get_engine()
        sql = sa.text(
            """
            DELETE FROM memory_scope_kv
            WHERE scope_type = :scope_type AND scope_id = :scope_id
            """
        )
        with eng.begin() as conn:
            res = conn.execute(sql, {"scope_type": scope_type, "scope_id": scope_id})
        return int(getattr(res, "rowcount", 0) or 0)

    # ------------------------------------------------------------
    # conversation_turn
    # ------------------------------------------------------------
    def append_conversation_turn(
        self,
        *,
        conversation_id: str,
        user_text: str,
        assistant_text: str,
        max_turns: int,
    ) -> None:
        eng = self._get_engine()
        sql = sa.text(
            """
            INSERT INTO conversation_turn (conversation_id, t_unix, user_text, assistant_text)
            VALUES (:conversation_id, :t_unix, :user_text, :assistant_text)
            """
        )
        with eng.begin() as conn:
            conn.execute(
                sql,
                {
                    "conversation_id": conversation_id,
                    "t_unix": float(time.time()),
                    "user_text": user_text,
                    "assistant_text": assistant_text,
                },
            )

            if isinstance(max_turns, int) and max_turns > 0:
                # Keep last N turns for the conversation.
                cleanup = sa.text(
                    """
                    DELETE FROM conversation_turn
                    WHERE id IN (
                        SELECT id FROM conversation_turn
                        WHERE conversation_id = :conversation_id
                        ORDER BY t_unix DESC
                        OFFSET :max_turns
                    )
                    """
                )
                conn.execute(
                    cleanup,
                    {"conversation_id": conversation_id, "max_turns": int(max_turns)},
                )
            else:
                conn.execute(
                    sa.text(
                        "DELETE FROM conversation_turn WHERE conversation_id = :conversation_id"
                    ),
                    {"conversation_id": conversation_id},
                )

    def get_conversation_turns(
        self, *, conversation_id: str, max_turns: int
    ) -> List[Dict[str, Any]]:
        if not isinstance(max_turns, int) or max_turns <= 0:
            return []

        eng = self._get_engine()
        sql = sa.text(
            """
            SELECT t_unix, user_text, assistant_text
            FROM conversation_turn
            WHERE conversation_id = :conversation_id
            ORDER BY t_unix DESC
            LIMIT :max_turns
            """
        )

        with eng.connect() as conn:
            rows = (
                conn.execute(
                    sql,
                    {"conversation_id": conversation_id, "max_turns": int(max_turns)},
                )
                .mappings()
                .all()
            )

        out: List[Dict[str, Any]] = []
        for r in reversed(list(rows)):
            out.append(
                {
                    "t": r.get("t_unix"),
                    "user": r.get("user_text"),
                    "assistant": r.get("assistant_text"),
                }
            )
        return out

    # ------------------------------------------------------------
    # conversation_meta_kv
    # ------------------------------------------------------------
    def get_conversation_meta(self, *, conversation_id: str) -> Dict[str, Any]:
        eng = self._get_engine()
        sql = sa.text(
            """
            SELECT key, value
            FROM conversation_meta_kv
            WHERE conversation_id = :conversation_id
            """
        )

        with eng.connect() as conn:
            rows = (
                conn.execute(sql, {"conversation_id": conversation_id}).mappings().all()
            )

        out: Dict[str, Any] = {}
        for r in rows:
            k = r.get("key")
            if isinstance(k, str) and k.strip():
                out[k] = r.get("value")
        return out

    def upsert_conversation_meta(
        self, *, conversation_id: str, updates: Dict[str, Any]
    ) -> None:
        if not isinstance(updates, dict) or not updates:
            return

        eng = self._get_engine()
        sql = sa.text(
            """
            INSERT INTO conversation_meta_kv (conversation_id, key, value, updated_at)
            VALUES (:conversation_id, :key, CAST(:value AS jsonb), now())
            ON CONFLICT (conversation_id, key)
            DO UPDATE SET value = excluded.value, updated_at = now()
            """
        )

        with eng.begin() as conn:
            for k, v in updates.items():
                if not (isinstance(k, str) and k.strip()):
                    continue
                conn.execute(
                    sql,
                    {
                        "conversation_id": conversation_id,
                        "key": k.strip(),
                        "value": json.dumps(v),
                    },
                )
