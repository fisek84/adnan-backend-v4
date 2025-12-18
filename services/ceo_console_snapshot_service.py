# services/ceo_console_snapshot_service.py

from __future__ import annotations

from typing import Any, Dict, List, Optional
from datetime import datetime, timezone
from collections import Counter
import logging

from services.approval_state_service import get_approval_state, ApprovalStateService
from services.goals_service import GoalsService
from services.tasks_service import TasksService

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class CeoConsoleSnapshotService:
    """
    CEO CONSOLE SNAPSHOT SERVICE (READ-ONLY)

    CANON:
    - Ne izvršava nikakve WRITE akcije.
    - Ne kreira, ne odobrava, ne orkestrira.
    - Samo čita postojeće stanje iz domen servisa i approval state-a.
    - Output je čist DTO za CEO Dashboard (System / Approvals / Goals / Tasks).
    """

    def __init__(
        self,
        *,
        goals_service: Optional[GoalsService] = None,
        tasks_service: Optional[TasksService] = None,
    ) -> None:
        self._approval_state: ApprovalStateService = get_approval_state()
        self._goals_service = goals_service
        self._tasks_service = tasks_service

    # ------------------------------------------------------------------
    # INTERNAL HELPERS
    # ------------------------------------------------------------------

    def _utc_now_iso(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _status_counts(self, items: List[Any]) -> Dict[str, int]:
        """
        Generički brojač po statusu.
        Pretpostavka: item.status postoji i string je.
        """
        counter: Counter[str] = Counter()
        for item in items:
            status = getattr(item, "status", None)
            if not status:
                continue
            counter[str(status)] += 1
        return dict(counter)

    # ------------------------------------------------------------------
    # SNAPSHOT BUILDERS
    # ------------------------------------------------------------------

    def _build_approvals_pipeline(self) -> Dict[str, Any]:
        """
        Read-only pogled na approval state.
        Ništa se ne mijenja, samo se čita trenutni in-memory state.
        """
        approvals_map: Dict[str, Dict[str, Any]] = self._approval_state._approvals  # type: ignore[attr-defined]
        approvals: List[Dict[str, Any]] = list(approvals_map.values())

        pending = [a for a in approvals if a.get("status") == "pending"]
        approved = [a for a in approvals if a.get("status") == "approved"]
        rejected = [a for a in approvals if a.get("status") == "rejected"]
        failed = [a for a in approvals if a.get("status") == "failed"]

        return {
            "total": len(approvals),
            "pending": pending,
            "approved": approved,
            # rejected + failed da CEO odmah vidi sve što nije prošlo
            "rejected": rejected,
            "failed": failed,
        }

    def _build_goals_snapshot(self) -> Dict[str, Any]:
        if not self._goals_service:
            # ako nije injektovan servis, vratimo prazan snapshot (READ-only, safe)
            return {"total": 0, "by_status": {}}

        goals = self._goals_service.get_all()
        return {
            "total": len(goals),
            "by_status": self._status_counts(goals),
        }

    def _build_tasks_snapshot(self) -> Dict[str, Any]:
        if not self._tasks_service:
            return {"total": 0, "by_status": {}}

        tasks = self._tasks_service.get_all()
        return {
            "total": len(tasks),
            "by_status": self._status_counts(tasks),
        }

    # ------------------------------------------------------------------
    # PUBLIC API
    # ------------------------------------------------------------------

    def build_snapshot(self) -> Dict[str, Any]:
        """
        Glavni entrypoint: CE0 Dashboard READ-only snapshot.

        Ovo smije da se poziva iz bilo kojeg UX sloja (web, voice, CLI),
        jer ne izvršava ništa – samo vraća stanje.
        """

        logger.info("[CEO SNAPSHOT] Building CEO console snapshot (READ-only)")

        approvals_pipeline = self._build_approvals_pipeline()
        goals_snapshot = self._build_goals_snapshot()
        tasks_snapshot = self._build_tasks_snapshot()

        # System status minimalno za FAZU 1.1.
        # Kasnije se ovdje može dodati health check, metrics, itd.
        system_status = {
            "status": "OK",
            "generated_at": self._utc_now_iso(),
        }

        snapshot: Dict[str, Any] = {
            "system_status": system_status,
            "approvals_pipeline": approvals_pipeline,
            "goals_snapshot": goals_snapshot,
            "tasks_snapshot": tasks_snapshot,
        }

        return snapshot
