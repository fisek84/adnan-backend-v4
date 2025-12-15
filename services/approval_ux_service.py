"""
APPROVAL UX SERVICE — CANONICAL (FAZA 5)

Uloga:
- JEDINI UX ulaz za approval akcije
- mapira CEO potvrdu u strogo definisan approval signal
- NE izvršava ništa
- NE donosi odluke
- NE radi governance
- NE dira execution

CEO potvrda ≠ execution
CEO potvrda = signal SYSTEMU
"""

from typing import Dict, Any
from datetime import datetime

from services.approval_state_service import ApprovalStateService


class ApprovalUXService:
    """
    UX-facing approval handler.
    """

    def __init__(self):
        self._approvals = ApprovalStateService()

    # =========================================================
    # CEO APPROVAL INPUT
    # =========================================================
    def approve(
        self,
        *,
        approval_id: str,
        approved_by: str,
        note: str | None = None,
    ) -> Dict[str, Any]:
        """
        CEO / Human eksplicitno potvrđuje sljedeći approval level.
        """

        state = self._approvals.approve_next_level(
            approval_id=approval_id,
            approved_by=approved_by,
            note=note,
        )

        if not state:
            return {
                "success": False,
                "error": "approval_not_found",
                "timestamp": datetime.utcnow().isoformat(),
                "read_only": True,
            }

        return {
            "success": True,
            "approval": state,
            "timestamp": datetime.utcnow().isoformat(),
            "read_only": False,
        }

    # =========================================================
    # ESCALATION (EXPLICIT)
    # =========================================================
    def escalate(
        self,
        *,
        approval_id: str,
        escalated_by: str,
        reason: str,
    ) -> Dict[str, Any]:
        """
        Eksplicitna eskalacija ka čovjeku / višem nivou.
        """

        state = self._approvals.escalate(
            approval_id=approval_id,
            escalated_by=escalated_by,
            reason=reason,
        )

        if not state:
            return {
                "success": False,
                "error": "approval_not_found",
                "timestamp": datetime.utcnow().isoformat(),
                "read_only": True,
            }

        return {
            "success": True,
            "approval": state,
            "timestamp": datetime.utcnow().isoformat(),
            "read_only": False,
        }
