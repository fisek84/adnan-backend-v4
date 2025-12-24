import logging
from datetime import datetime
from typing import Any, Dict, Optional


class KnowledgeSnapshotService:
    """
    Global, read-only snapshot poslovnog znanja.

    CANON:
    - Ovaj servis NIKAD ne radi write u eksterne sisteme.
    - Samo drži u-memory snapshot koji je već pripremljen od nekog sync procesa
      (npr. Notion Ops ili offline job).
    - CEO Advisory koristi ovaj snapshot kao READ source.

    Stabilan shape:
      {
        "ready": bool,
        "last_sync": str|None,
        "databases": dict,
        "identity_pack": dict,
        "trace": dict
      }
    """

    _snapshot: Optional[Dict[str, Any]] = None
    _ready: bool = False
    _last_sync: Optional[str] = None

    logger = logging.getLogger("knowledge_snapshot")
    logger.setLevel(logging.INFO)

    @classmethod
    def update_snapshot(cls, data: Dict[str, Any]) -> None:
        """
        In-memory update only (READ/WRITE boundary is outside this service).
        This is intended to be called by an explicit sync workflow.
        """
        cls._snapshot = data
        cls._ready = True
        cls._last_sync = datetime.utcnow().isoformat()
        cls.logger.info("Knowledge snapshot updated")

    @classmethod
    def _load_identity_pack_best_effort(cls) -> Dict[str, Any]:
        """
        Read-only: loads CEO identity pack from local repo files.
        Never raises; returns available=False on errors.
        """
        try:
            from services.identity_loader import load_ceo_identity_pack  # type: ignore

            return load_ceo_identity_pack()
        except Exception as e:
            return {
                "available": False,
                "source": "identity_loader",
                "error": str(e),
            }

    @classmethod
    def get_snapshot(cls) -> Dict[str, Any]:
        """
        Returns a stable knowledge snapshot for READ contexts.
        """
        identity_pack = cls._load_identity_pack_best_effort()

        return {
            "ready": cls._ready,
            "last_sync": cls._last_sync,
            "databases": cls._snapshot or {},
            "identity_pack": identity_pack,
            "trace": {
                "service": "KnowledgeSnapshotService",
                "generated_at": datetime.utcnow().isoformat(),
            },
        }

    @classmethod
    def is_ready(cls) -> bool:
        return cls._ready
