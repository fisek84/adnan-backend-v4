# services/knowledge_snapshot_service.py

from typing import Dict, Any
import threading
import time


class KnowledgeSnapshotService:
    """
    Read-only internal knowledge snapshot.
    Purpose:
    - Hold normalized, structured view of the company state
    - NO execution
    - NO decision making
    - NO side effects
    """

    _lock = threading.Lock()
    _snapshot: Dict[str, Any] = {
        "meta": {
            "last_updated": None,
            "source": "notion"
        },
        "goals": [],
        "tasks": [],
        "projects": [],
        "sops": [],
        "agents": [],
        "databases": {}
    }

    @classmethod
    def update_snapshot(cls, data: Dict[str, Any]) -> None:
        """
        Replace snapshot atomically.
        Called ONLY by sync layer.
        """
        with cls._lock:
            cls._snapshot = {
                **cls._snapshot,
                **data,
                "meta": {
                    **cls._snapshot.get("meta", {}),
                    "last_updated": time.time(),
                    "source": "notion"
                }
            }

    @classmethod
    def get_snapshot(cls) -> Dict[str, Any]:
        """
        Full read-only snapshot.
        """
        with cls._lock:
            return cls._snapshot.copy()

    @classmethod
    def get_section(cls, section: str) -> Any:
        """
        Read-only access to a single knowledge section
        (goals, tasks, sops, projects, agents, databases)
        """
        with cls._lock:
            return cls._snapshot.get(section)

    @classmethod
    def is_ready(cls) -> bool:
        """
        Snapshot readiness check.
        """
        with cls._lock:
            return cls._snapshot.get("meta", {}).get("last_updated") is not None
