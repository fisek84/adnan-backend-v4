# services/approval_ux_service.py

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from services.approval_state_service import get_approval_state

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class ApprovalUXService:
    """
    APPROVAL UX SERVICE — KANON

    Svrha:
    - “presentation/UX” sloj oko ApprovalStateService
    - NE donosi policy odluke
    - NE izvršava ništa
    - samo formatira, filtrira, i daje stabilne UX strukture za frontend/CLI.

    Kanonska pravila:
    - approval je vezan za execution_id
    - approval lifecycle: pending -> approved|rejected
    - UX sloj mora biti idempotentan i bez side-effect-a (osim approve/reject poziva u StateService).
    """

    def __init__(self) -> None:
        self.state = get_approval_state()

    # -----------------------------
    # LIST / GET
    # -----------------------------
    def list_pending(self) -> Dict[str, Any]:
        pending = self.state.list_pending()
        return {
            "ok": True,
            "count": len(pending),
            "items": [self._to_card(a) for a in pending],
        }

    def list_all(self, status: Optional[str] = None) -> Dict[str, Any]:
        items = self.state.list_approvals(status=status)
        return {
            "ok": True,
            "count": len(items),
            "status": status,
            "items": [self._to_card(a) for a in items],
        }

    def get(self, approval_id: str) -> Dict[str, Any]:
        approval = self.state.get(approval_id)
        return {
            "ok": True,
            "item": self._to_card(approval),
        }

    # -----------------------------
    # DECISIONS
    # -----------------------------
    def approve(
        self,
        approval_id: str,
        *,
        approved_by: str = "unknown",
        note: Optional[str] = None,
    ) -> Dict[str, Any]:
        approval = self.state.approve(
            approval_id,
            approved_by=approved_by,
            note=note,
        )
        return {
            "ok": True,
            "item": self._to_card(approval),
        }

    def reject(
        self,
        approval_id: str,
        *,
        rejected_by: str = "unknown",
        note: Optional[str] = None,
    ) -> Dict[str, Any]:
        approval = self.state.reject(
            approval_id,
            rejected_by=rejected_by,
            note=note,
        )
        return {
            "ok": True,
            "item": self._to_card(approval),
        }

    # -----------------------------
    # UI HELPERS
    # -----------------------------
    @staticmethod
    def _to_card(approval: Dict[str, Any]) -> Dict[str, Any]:
        """
        Stabilan UX shape za prikaz (frontend/CLI).
        """
        payload_summary = (
            approval.get("payload_summary") if isinstance(approval, dict) else {}
        )
        if not isinstance(payload_summary, dict):
            payload_summary = {}

        return {
            "approval_id": approval.get("approval_id"),
            "execution_id": approval.get("execution_id"),
            "status": approval.get("status"),
            "command": approval.get("command"),
            "scope": approval.get("scope"),
            "risk_level": approval.get("risk_level"),
            "created_at": approval.get("created_at"),
            "decided_at": approval.get("decided_at"),
            "approved_by": approval.get("approved_by"),
            "rejected_by": approval.get("rejected_by"),
            "note": approval.get("note"),
            "payload_summary": payload_summary,
        }
