# services/weekly_memory_service.py

from __future__ import annotations

from typing import Any, Dict, Optional
from datetime import datetime, timezone
import threading


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

        with self._lock:
            self._latest_ai_summary = dict(payload)
            self._updated_at = datetime.now(timezone.utc).isoformat()

    def get_snapshot(self) -> Dict[str, Any]:
        """
        READ-only snapshot za frontend.
        """
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
