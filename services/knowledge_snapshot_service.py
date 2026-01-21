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
        # If meta.ok explicitly false and there is no data, mark not-ready.
        meta_ok = None
        try:
            meta_ok = cls._meta.get("ok") if isinstance(cls._meta, dict) else None
        except Exception:
            meta_ok = None

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

        cls._ready = bool(has_core_data or meta_ok is not False)

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
        payload = cls.get_payload()
        if not isinstance(payload, dict):
            payload = {}

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
            # Ensure core collections exist and are lists.
            for k in ("goals", "tasks", "projects"):
                v = payload.get(k)
                if not isinstance(v, list):
                    payload[k] = []
        meta = cls._meta if isinstance(cls._meta, dict) else {}

        identity_pack = cls._load_identity_pack_best_effort()

        # Enterprise status is derived from readiness + TTL (not from payload truthiness).
        if not cls._ready:
            status = "missing_data"
        elif expired:
            status = "stale"
        else:
            status = "fresh"

        snap: Dict[str, Any] = {
            "schema_version": "v1",
            "status": status,
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
