import logging
from typing import Dict, Any, Optional
from datetime import datetime


class KnowledgeSnapshotService:
    """
    Global, read-only snapshot poslovnog znanja iz Notiona.
    Jedini izvor svijesti za Adnan.AI (FAZA 1).
    """

    _snapshot: Optional[Dict[str, Any]] = None
    _ready: bool = False
    _last_sync: Optional[str] = None

    logger = logging.getLogger("knowledge_snapshot")
    logger.setLevel(logging.INFO)

    @classmethod
    def update_snapshot(cls, data: Dict[str, Any]) -> None:
        cls._snapshot = data
        cls._ready = True
        cls._last_sync = datetime.utcnow().isoformat()
        cls.logger.info("📸 Knowledge snapshot updated")

    @classmethod
    def get_snapshot(cls) -> Dict[str, Any]:
        return {
            "ready": cls._ready,
            "last_sync": cls._last_sync,
            "databases": cls._snapshot or {},
        }

    @classmethod
    def is_ready(cls) -> bool:
        return cls._ready
