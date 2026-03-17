# services/weekly_memory_service.py

from __future__ import annotations

from typing import Any, Dict, Optional
from datetime import datetime, timezone
import threading
import os


def _backend_kind() -> str:
    return (os.getenv("MEMORY_BACKEND") or "file").strip().lower()


def _pg_backend_required():
    if _backend_kind() != "postgres":
        return None
    try:
        from services.memory_postgres_backend import PostgresMemoryBackend

        pg = PostgresMemoryBackend()
        if not pg.is_configured():
            raise RuntimeError(
                "MEMORY_BACKEND=postgres but DATABASE_URL is not set; weekly memory cannot be persisted"
            )
        return pg
    except Exception as e:
        raise RuntimeError(
            "MEMORY_BACKEND=postgres but Postgres backend is unavailable for weekly memory"
        ) from e


_WEEKLY_SCOPE_TYPE = "user"
_WEEKLY_SCOPE_ID = "ceo_weekly_memory"
_WEEKLY_KEY = "latest_ai_summary"


class WeeklyMemoryService:
    """
    In-memory cache za CEO WEEKLY PRIORITY MEMORY.

    - write radi isključivo NotionOpsAgent (workflowi tipa KPI weekly summary)
    - read radi CEO dashboard / snapshot
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._latest_ai_summary: Optional[Dict[str, Any]] = None
        self._updated_at: Optional[str] = None

    def set_latest_ai_summary(self, payload: Dict[str, Any]) -> None:
        """
        Upisuje zadnji AI weekly summary koji treba da se pokaže na CEO dashboardu.
        """
        if not isinstance(payload, dict):
            payload = {}

        # Canonical persistence in postgres mode (restart-safe).
        pg = _pg_backend_required()
        if pg is not None:
            updated_at = datetime.now(timezone.utc).isoformat()
            pg.upsert_scope_kv(
                scope_type=_WEEKLY_SCOPE_TYPE,
                scope_id=_WEEKLY_SCOPE_ID,
                key=_WEEKLY_KEY,
                value=dict(payload),
                exp_unix=None,
                meta={"updated_at": updated_at},
            )
            with self._lock:
                self._latest_ai_summary = dict(payload)
                self._updated_at = updated_at
            return

        with self._lock:
            self._latest_ai_summary = dict(payload)
            self._updated_at = datetime.now(timezone.utc).isoformat()

    def get_snapshot(self) -> Dict[str, Any]:
        """
        READ-only snapshot za frontend.
        """
        pg = _pg_backend_required()
        if pg is not None:
            rec = pg.get_scope_kv(
                scope_type=_WEEKLY_SCOPE_TYPE,
                scope_id=_WEEKLY_SCOPE_ID,
                key=_WEEKLY_KEY,
            )
            val = rec.get("value") if isinstance(rec, dict) else None
            meta = rec.get("meta") if isinstance(rec, dict) else None
            updated_at = (
                (meta.get("updated_at") if isinstance(meta, dict) else None)
                if isinstance(meta, dict)
                else None
            )
            if not (isinstance(updated_at, str) and updated_at.strip()):
                updated_at = None
            latest = val if isinstance(val, dict) else None
            return {
                "latest_ai_summary": latest,
                "updated_at": updated_at,
            }

        with self._lock:
            return {
                "latest_ai_summary": self._latest_ai_summary,
                "updated_at": self._updated_at,
            }


# --- global singleton (isti pattern kao ApprovalStateService) --------
_global_weekly_memory: Optional[WeeklyMemoryService] = None


def get_weekly_memory_service() -> WeeklyMemoryService:
    global _global_weekly_memory
    if _global_weekly_memory is None:
        _global_weekly_memory = WeeklyMemoryService()
    return _global_weekly_memory
