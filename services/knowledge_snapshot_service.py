import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional


class KnowledgeSnapshotService:
    """
    Global, read-only snapshot poslovnog znanja.

    SSOT:
    - _payload: kanonski payload (npr. Notion snapshot: goals/tasks/leads/kpis/projects/dashboard/...)
    - wrapper get_snapshot() daje meta + payload + identity_pack
    - BACKWARD COMPAT: iz payload-a izvučemo top-level alias ključeve (dashboard/goals/tasks/...)
      da postojeći agenti koji očekuju snapshot["dashboard"] i sl. ne puknu.

    TTL:
    - Snapshot se smatra EXPIRED ako je stariji od KNOWLEDGE_SNAPSHOT_TTL_SECONDS (default 12h).
    - Kada je EXPIRED: get_payload() vraća {}, get_snapshot() vraća ready=False i payload={}
    """

    DEFAULT_TTL_SECONDS = 12 * 60 * 60  # 12h

    _payload: Optional[Dict[str, Any]] = None
    _meta: Optional[Dict[str, Any]] = None
    _ready: bool = False
    _last_sync: Optional[str] = None  # ISO string (UTC)

    logger = logging.getLogger("knowledge_snapshot")
    logger.setLevel(logging.INFO)

    # ----------------------------
    # TIME HELPERS
    # ----------------------------

    @classmethod
    def _utc_now(cls) -> datetime:
        return datetime.now(timezone.utc)

    @classmethod
    def _utc_now_iso(cls) -> str:
        # Keep ISO; can be "+00:00" or "Z" depending on caller expectations.
        return cls._utc_now().isoformat()

    @classmethod
    def _ttl_seconds(cls) -> int:
        raw = (os.getenv("KNOWLEDGE_SNAPSHOT_TTL_SECONDS") or "").strip()
        if not raw:
            return cls.DEFAULT_TTL_SECONDS
        try:
            v = int(raw)
            return v if v > 0 else cls.DEFAULT_TTL_SECONDS
        except Exception:
            return cls.DEFAULT_TTL_SECONDS

    @classmethod
    def _parse_iso_best_effort(cls, s: str) -> Optional[datetime]:
        try:
            ss = (s or "").strip()
            if not ss:
                return None
            # Support "....Z"
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
        if isinstance(cls._last_sync, str) and cls._last_sync.strip():
            return cls._parse_iso_best_effort(cls._last_sync.strip())

        payload = cls._payload if isinstance(cls._payload, dict) else {}
        pls = payload.get("last_sync")
        if isinstance(pls, str) and pls.strip():
            return cls._parse_iso_best_effort(pls.strip())

        meta = cls._meta if isinstance(cls._meta, dict) else {}
        ms = meta.get("synced_at") if isinstance(meta, dict) else None
        if isinstance(ms, str) and ms.strip():
            return cls._parse_iso_best_effort(ms.strip())

        return None

    @classmethod
    def get_age_seconds(cls) -> Optional[int]:
        dt = cls._last_sync_dt()
        if dt is None:
            return None
        age = (cls._utc_now() - dt).total_seconds()
        if age < 0:
            age = 0
        return int(age)

    @classmethod
    def is_expired(cls) -> bool:
        age = cls.get_age_seconds()
        if age is None:
            return False  # no timestamp => don't expire hard
        return age > cls._ttl_seconds()

    # ----------------------------
    # UPDATE / LOAD
    # ----------------------------

    @classmethod
    def update_snapshot(cls, data: Dict[str, Any]) -> None:
        """
        Accepts either:
          A) wrapper: {"payload": {...}, "meta": {...}}
          B) payload: {...}

        Stores canonical payload in _payload and meta (if present) in _meta.
        """
        wrapper = data if isinstance(data, dict) else {}

        payload: Dict[str, Any]
        meta: Dict[str, Any]

        if isinstance(wrapper.get("payload"), dict):
            payload = wrapper.get("payload") or {}
            meta = wrapper.get("meta") if isinstance(wrapper.get("meta"), dict) else {}
        else:
            payload = wrapper
            meta = {}

        cls._payload = payload if isinstance(payload, dict) else {}
        cls._meta = meta if isinstance(meta, dict) else {}
        cls._ready = True

        # Deterministic last_sync:
        # prefer payload.last_sync; fallback meta.synced_at; else now.
        payload_last_sync = (
            cls._payload.get("last_sync") if isinstance(cls._payload, dict) else None
        )
        meta_synced_at = (
            cls._meta.get("synced_at") if isinstance(cls._meta, dict) else None
        )

        if isinstance(payload_last_sync, str) and payload_last_sync.strip():
            cls._last_sync = payload_last_sync.strip()
        elif isinstance(meta_synced_at, str) and meta_synced_at.strip():
            cls._last_sync = meta_synced_at.strip()
        else:
            cls._last_sync = cls._utc_now_iso()

        cls.logger.info(
            "Knowledge snapshot updated (ready=%s last_sync=%s keys=%s)",
            cls._ready,
            cls._last_sync,
            sorted(list(cls._payload.keys())) if isinstance(cls._payload, dict) else [],
        )

    # ----------------------------
    # IDENTITY PACK (best-effort)
    # ----------------------------

    @classmethod
    def _load_identity_pack_best_effort(cls) -> Dict[str, Any]:
        try:
            from services.identity_loader import load_ceo_identity_pack  # type: ignore

            pack = load_ceo_identity_pack()
            return (
                pack
                if isinstance(pack, dict)
                else {"available": False, "error": "identity_pack_not_dict"}
            )
        except Exception as e:
            return {"available": False, "source": "identity_loader", "error": str(e)}

    # ----------------------------
    # READ API
    # ----------------------------

    @classmethod
    def get_payload(cls) -> Dict[str, Any]:
        if cls.is_expired():
            return {}
        return cls._payload if isinstance(cls._payload, dict) else {}

    @classmethod
    def get_snapshot(cls) -> Dict[str, Any]:
        identity_pack = cls._load_identity_pack_best_effort()

        expired = cls.is_expired()
        ttl_seconds = cls._ttl_seconds()
        age_seconds = cls.get_age_seconds()

        payload = (
            {} if expired else (cls._payload if isinstance(cls._payload, dict) else {})
        )
        meta = cls._meta if isinstance(cls._meta, dict) else {}

        # Compute last_sync deterministically
        last_sync = cls._last_sync
        payload_last_sync = (
            payload.get("last_sync") if isinstance(payload, dict) else None
        )
        if isinstance(payload_last_sync, str) and payload_last_sync.strip():
            last_sync = payload_last_sync.strip()

        snap: Dict[str, Any] = {
            "ready": bool((cls._ready and bool(payload)) and (not expired)),
            "expired": bool(expired),
            "ttl_seconds": int(ttl_seconds),
            "age_seconds": age_seconds,
            "last_sync": last_sync,
            "meta": meta,  # safe to expose; empty if not provided
            "payload": payload,
            "identity_pack": identity_pack,
            "trace": {
                "service": "KnowledgeSnapshotService",
                "generated_at": cls._utc_now_iso(),
                "payload_keys": sorted(list(payload.keys()))
                if isinstance(payload, dict)
                else [],
                "payload_empty": not bool(payload),
                "compat_aliases": True,
                "ttl_seconds": int(ttl_seconds),
                "age_seconds": age_seconds,
                "expired": bool(expired),
            },
        }

        # ---------------------------------------------------------
        # BACKWARD-COMPAT ALIASES (root-level)
        # ---------------------------------------------------------
        if isinstance(payload, dict) and payload:
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
                if k in payload and k not in snap:
                    snap[k] = payload.get(k)

        return snap

    @classmethod
    def is_ready(cls) -> bool:
        return bool(cls._ready and bool(cls.get_payload()) and (not cls.is_expired()))
