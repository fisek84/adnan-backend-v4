# services/knowledge_snapshot_service.py

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional


class KnowledgeSnapshotService:
    """
    KNOWLEDGE SNAPSHOT SERVICE — CANONICAL (WORLD-CLASS)

    Odgovornost:
    - Globalni READ-ONLY snapshot znanja (SSOT)
    - TTL enforcement
    - Backward compatibility
    - Identity pack (best-effort)

    HARD CANON:
    - NEMA IO u read path-u
    - NEMA side-effecta u get_*
    - Snapshot je ATOMIC
    """

    DEFAULT_TTL_SECONDS = 12 * 60 * 60  # 12h

    _payload: Optional[Dict[str, Any]] = None
    _meta: Optional[Dict[str, Any]] = None
    _ready: bool = False
    _last_sync: Optional[str] = None  # ISO UTC
    _status_hint: Optional[str] = None

    logger = logging.getLogger("knowledge_snapshot")
    logger.setLevel(logging.INFO)

    # =========================================================
    # TIME
    # =========================================================
    @classmethod
    def _utc_now(cls) -> datetime:
        return datetime.now(timezone.utc)

    @classmethod
    def _utc_now_iso(cls) -> str:
        return cls._utc_now().isoformat()

    @classmethod
    def _ttl_seconds(cls) -> int:
        raw = (os.getenv("KNOWLEDGE_SNAPSHOT_TTL_SECONDS") or "").strip()
        try:
            v = int(raw)
            return v if v > 0 else cls.DEFAULT_TTL_SECONDS
        except Exception:
            return cls.DEFAULT_TTL_SECONDS

    @classmethod
    def _parse_iso(cls, s: str) -> Optional[datetime]:
        try:
            ss = (s or "").strip()
            if not ss:
                return None
            if ss.endswith("Z"):
                ss = ss[:-1] + "+00:00"
            dt = datetime.fromisoformat(ss)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except Exception:
            return None

    @classmethod
    def _last_sync_dt(cls) -> Optional[datetime]:
        if isinstance(cls._last_sync, str):
            return cls._parse_iso(cls._last_sync)

        payload = cls._payload if isinstance(cls._payload, dict) else {}
        if isinstance(payload.get("last_sync"), str):
            return cls._parse_iso(payload["last_sync"])

        meta = cls._meta if isinstance(cls._meta, dict) else {}
        if isinstance(meta.get("synced_at"), str):
            return cls._parse_iso(meta["synced_at"])

        return None

    @classmethod
    def get_age_seconds(cls) -> Optional[int]:
        dt = cls._last_sync_dt()
        if not dt:
            return None
        age = (cls._utc_now() - dt).total_seconds()
        return max(0, int(age))

    @classmethod
    def is_expired(cls) -> bool:
        age = cls.get_age_seconds()
        return False if age is None else age > cls._ttl_seconds()

    # =========================================================
    # UPDATE (WRITE PATH)
    # =========================================================
    @classmethod
    def update_snapshot(cls, data: Dict[str, Any]) -> None:
        wrapper = data if isinstance(data, dict) else {}

        if isinstance(wrapper.get("payload"), dict):
            payload = wrapper.get("payload") or {}
            meta = wrapper.get("meta") if isinstance(wrapper.get("meta"), dict) else {}
        else:
            payload = wrapper
            meta = {}

        cls._payload = payload if isinstance(payload, dict) else {}
        cls._meta = meta if isinstance(meta, dict) else {}

        # Readiness should reflect whether we actually have usable snapshot data.
        # Invariants (enterprise):
        # - If meta.ok == false OR budget exceeded OR meta.errors non-empty OR payload empty
        #   => snapshot must NOT be ready/fresh.
        meta_ok = None
        try:
            meta_ok = cls._meta.get("ok") if isinstance(cls._meta, dict) else None
        except Exception:
            meta_ok = None

        meta_errors = []
        try:
            meta_errors = (
                cls._meta.get("errors") if isinstance(cls._meta, dict) else None
            )
        except Exception:
            meta_errors = []
        has_errors = isinstance(meta_errors, list) and len(meta_errors) > 0

        budget_exceeded = False
        try:
            if isinstance(cls._meta, dict):
                if cls._meta.get("budget_exceeded") is True:
                    budget_exceeded = True
                budget = cls._meta.get("budget")
                if isinstance(budget, dict) and budget.get("exceeded") is True:
                    budget_exceeded = True
        except Exception:
            budget_exceeded = False

        payload_empty = False
        try:
            payload_empty = not bool(cls._payload)
        except Exception:
            payload_empty = True

        has_core_data = False
        try:
            if isinstance(cls._payload, dict):
                for k in ("goals", "tasks", "projects"):
                    v = cls._payload.get(k)
                    if isinstance(v, list) and len(v) > 0:
                        has_core_data = True
                        break
        except Exception:
            has_core_data = False

        hard_not_ready = bool(
            meta_ok is False or budget_exceeded or has_errors or payload_empty
        )
        if hard_not_ready:
            cls._ready = False
            cls._status_hint = (
                "error"
                if (meta_ok is False or budget_exceeded or has_errors)
                else "partial"
            )
        else:
            cls._ready = bool(has_core_data or meta_ok is not False)
            cls._status_hint = None

        if isinstance(cls._payload.get("last_sync"), str):
            cls._last_sync = cls._payload["last_sync"]
        elif isinstance(cls._meta.get("synced_at"), str):
            cls._last_sync = cls._meta["synced_at"]
        else:
            cls._last_sync = cls._utc_now_iso()

        cls.logger.info(
            "Knowledge snapshot updated (ready=%s last_sync=%s keys=%s)",
            cls._ready,
            cls._last_sync,
            sorted(list(cls._payload.keys())),
        )

    # =========================================================
    # IDENTITY PACK (BEST-EFFORT)
    # =========================================================
    @classmethod
    def _load_identity_pack_best_effort(cls) -> Dict[str, Any]:
        try:
            from services.identity_loader import load_ceo_identity_pack  # type: ignore

            pack = load_ceo_identity_pack()
            return pack if isinstance(pack, dict) else {"available": False}
        except Exception as e:
            return {"available": False, "error": str(e)}

    # =========================================================
    # READ API
    # =========================================================
    @classmethod
    def get_payload(cls) -> Dict[str, Any]:
        # Canon: get_payload must be side-effect free and stable.
        # Expiration is signaled via `expired`, not by blanking payload.
        return cls._payload if isinstance(cls._payload, dict) else {}

    @classmethod
    def get_snapshot(cls) -> Dict[str, Any]:
        expired = cls.is_expired()
        payload_raw = cls.get_payload()
        payload: Dict[str, Any] = (
            dict(payload_raw) if isinstance(payload_raw, dict) else {}
        )

        generated_at = cls._utc_now_iso()
        # Contract: last_sync must always be present as a string (UI never renders empty state).
        last_sync_out = (
            cls._last_sync
            if isinstance(cls._last_sync, str) and cls._last_sync
            else generated_at
        )

        # Guarantee a deterministic, UI-safe shape even on cold start or failures.
        # NOTE: readiness still depends on non-expired state.
        if not payload:
            payload = {"goals": [], "tasks": [], "projects": []}
        else:
            # If payload.databases exists, treat it as SSOT for list-shaped payload keys.
            # This prevents any legacy list from contradicting per-db snapshot sections.
            dbs = payload.get("databases")
            if isinstance(dbs, dict) and dbs:
                try:
                    for db_key, section in dbs.items():
                        if not isinstance(db_key, str) or not db_key.strip():
                            continue
                        if not isinstance(section, dict):
                            continue
                        items = section.get("items")
                        payload[db_key] = items if isinstance(items, list) else []
                except Exception:
                    pass

            # Ensure core collections exist and are lists.
            for k in ("goals", "tasks", "projects"):
                v = payload.get(k)
                if not isinstance(v, list):
                    payload[k] = []
        meta = cls._meta if isinstance(cls._meta, dict) else {}

        identity_pack = cls._load_identity_pack_best_effort()

        # Contract: status must remain within the stable public set.
        # Readiness invariants and richer health signals are exposed via `ready` and `status_detail`.
        if expired:
            status = "stale"
        elif not cls._ready:
            status = "missing_data"
        else:
            status = "fresh"

        snap: Dict[str, Any] = {
            "schema_version": "v1",
            "status": status,
            "status_detail": cls._status_hint,
            "generated_at": generated_at,
            "ready": bool(cls._ready and not expired),
            "expired": bool(expired),
            "ttl_seconds": cls._ttl_seconds(),
            "age_seconds": cls.get_age_seconds(),
            "last_sync": last_sync_out,
            "meta": meta,
            "payload": payload,
            "identity_pack": identity_pack,
            "trace": {
                "service": "KnowledgeSnapshotService",
                "generated_at": generated_at,
                "payload_keys": sorted(list(payload.keys())),
                "expired": bool(expired),
                "ttl_seconds": cls._ttl_seconds(),
                "age_seconds": cls.get_age_seconds(),
                "is_expired": bool(expired),
                "notion_calls": (
                    int(meta.get("notion_calls"))
                    if isinstance(meta, dict)
                    and isinstance(meta.get("notion_calls"), int)
                    else 0
                ),
                "notion_budget": (
                    meta.get("budget")
                    if isinstance(meta, dict) and isinstance(meta.get("budget"), dict)
                    else None
                ),
            },
        }

        # BACKWARD-COMPAT ALIASES
        for k in (
            "dashboard",
            "goals",
            "tasks",
            "projects",
            "kpi",
            "kpis",
            "leads",
            "extra_databases",
        ):
            if isinstance(payload, dict) and k in payload:
                snap[k] = payload.get(k)

        return snap

    @classmethod
    def is_ready(cls) -> bool:
        return bool(cls._ready and cls.get_payload() and not cls.is_expired())
