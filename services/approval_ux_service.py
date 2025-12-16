# services/approval_ux_service.py

"""
APPROVAL UX SERVICE — CANONICAL (FAZA 12 / UX POLISH)

Uloga:
- JEDINI UX ulaz za approval akcije
- mapira CEO potvrdu / odbijanje u EKSPLICITAN SIGNAL sistemu
- NE izvršava
- NE donosi odluke
- NE radi governance
- NE dira execution

CEO potvrda ≠ execution
CEO potvrda = signal SYSTEMU
"""

from typing import Dict, Any, Optional
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
        note: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        CEO eksplicitno ODOBRAVA approval.
        Ovo je SIGNAL, ne izvršenje.
        """

        try:
            state = self._approvals.approve(approval_id)
        except KeyError:
            return {
                "success": False,
                "status": "blocked",
                "reason": "approval_not_found",
                "message": "Traženi approval ne postoji.",
                "timestamp": datetime.utcnow().isoformat(),
                "read_only": True,
            }

        return {
            "success": True,
            "status": "approved",
            "approval": state,
            "approved_by": approved_by,
            "note": note,
            "message": "Approval je uspješno potvrđen. Nema izvršenja bez governance-a.",
            "timestamp": datetime.utcnow().isoformat(),
            "read_only": False,
        }

    # =========================================================
    # CEO REJECTION
    # =========================================================
    def reject(
        self,
        *,
        approval_id: str,
        rejected_by: str,
        note: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        CEO eksplicitno ODBIJA approval.
        Ovo je SIGNAL, ne akcija.
        """

        try:
            state = self._approvals.reject(approval_id)
        except KeyError:
            return {
                "success": False,
                "status": "blocked",
                "reason": "approval_not_found",
                "message": "Traženi approval ne postoji.",
                "timestamp": datetime.utcnow().isoformat(),
                "read_only": True,
            }

        return {
            "success": True,
            "status": "rejected",
            "approval": state,
            "rejected_by": rejected_by,
            "note": note,
            "message": "Approval je odbijen. Izvršenje je zaustavljeno.",
            "timestamp": datetime.utcnow().isoformat(),
            "read_only": False,
        }
