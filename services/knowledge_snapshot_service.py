import logging
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
    """

    _payload: Optional[Dict[str, Any]] = None
    _ready: bool = False
    _last_sync: Optional[str] = None

    logger = logging.getLogger("knowledge_snapshot")
    logger.setLevel(logging.INFO)

    @classmethod
    def _utc_now_iso(cls) -> str:
        return datetime.now(timezone.utc).isoformat()

    @classmethod
    def update_snapshot(cls, data: Dict[str, Any]) -> None:
        payload = data if isinstance(data, dict) else {}
        cls._payload = payload
        cls._ready = True

        payload_last_sync = payload.get("last_sync")
        if isinstance(payload_last_sync, str) and payload_last_sync.strip():
            cls._last_sync = payload_last_sync.strip()
        else:
            cls._last_sync = cls._utc_now_iso()

        cls.logger.info(
            "Knowledge snapshot updated (ready=%s last_sync=%s keys=%s)",
            cls._ready,
            cls._last_sync,
            sorted(list(payload.keys())) if isinstance(payload, dict) else [],
        )

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
            return {
                "available": False,
                "source": "identity_loader",
                "error": str(e),
            }

    @classmethod
    def get_payload(cls) -> Dict[str, Any]:
        return cls._payload if isinstance(cls._payload, dict) else {}

    @classmethod
    def get_snapshot(cls) -> Dict[str, Any]:
        payload = cls.get_payload()
        identity_pack = cls._load_identity_pack_best_effort()

        # Compute last_sync deterministically
        last_sync = cls._last_sync
        payload_last_sync = payload.get("last_sync")
        if isinstance(payload_last_sync, str) and payload_last_sync.strip():
            last_sync = payload_last_sync.strip()

        snap: Dict[str, Any] = {
            "ready": bool(cls._ready and bool(payload)),
            "last_sync": last_sync,
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
        return bool(cls._ready and bool(cls.get_payload()))
