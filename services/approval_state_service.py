"""
APPROVAL STATE SERVICE — CANONICAL (FAZA 3.4)

Uloga:
- SINGLE SOURCE OF TRUTH za approval
- approval je vezan za TAČNO JEDAN AICommand
- approval lifecycle je deterministički
- NEMA izvršenja
- NEMA automatike
- NEMA eskalacione logike u FAZI 3
"""

from typing import Dict, Any
from datetime import datetime
from uuid import uuid4


class ApprovalStateService:
    """
    Minimalni, kanonski approval servis.
    FAZA 3 podržava ISKLJUČIVO:
    pending -> approved | rejected
    """

    def __init__(self):
        self._approvals: Dict[str, Dict[str, Any]] = {}

    # ============================================================
    # CREATE
    # ============================================================
    def create(
        self,
        *,
        command: str,
        payload_summary: Dict[str, Any],
        scope: str,
        risk_level: str,
    ) -> Dict[str, Any]:

        approval_id = str(uuid4())

        approval = {
            "approval_id": approval_id,
            "command": command,
            "payload_summary": payload_summary,
            "scope": scope,
            "risk_level": risk_level,
            "requested_by": "system",
            "status": "pending",
            "created_at": datetime.utcnow().isoformat(),
        }

        self._approvals[approval_id] = approval
        return approval.copy()

    # ============================================================
    # DECISIONS
    # ============================================================
    def approve(self, approval_id: str) -> Dict[str, Any]:
        approval = self._require(approval_id)

        approved = {
            **approval,
            "status": "approved",
            "decided_at": datetime.utcnow().isoformat(),
        }

        self._approvals[approval_id] = approved
        return approved.copy()

    def reject(self, approval_id: str) -> Dict[str, Any]:
        approval = self._require(approval_id)

        rejected = {
            **approval,
            "status": "rejected",
            "decided_at": datetime.utcnow().isoformat(),
        }

        self._approvals[approval_id] = rejected
        return rejected.copy()

    # ============================================================
    # READ
    # ============================================================
    def get(self, approval_id: str) -> Dict[str, Any]:
        return self._require(approval_id).copy()

    def is_fully_approved(self, approval_id: str) -> bool:
        approval = self._approvals.get(approval_id)
        if not approval:
            return False
        return approval.get("status") == "approved"

    # ============================================================
    # INTERNAL
    # ============================================================
    def _require(self, approval_id: str) -> Dict[str, Any]:
        if approval_id not in self._approvals:
            raise KeyError("Approval not found")
        return self._approvals[approval_id]
