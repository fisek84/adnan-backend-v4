# services/approval_state_service.py

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

        if not command:
            raise ValueError("Approval requires command.")

        approval_id = str(uuid4())

        approval = {
            "approval_id": approval_id,
            "command": command,
            "payload_summary": payload_summary or {},
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

        if approval.get("status") != "pending":
            return approval.copy()

        approved = {
            **approval,
            "status": "approved",
            "decided_at": datetime.utcnow().isoformat(),
        }

        self._approvals[approval_id] = approved
        return approved.copy()

    def reject(self, approval_id: str) -> Dict[str, Any]:
        approval = self._require(approval_id)

        if approval.get("status") != "pending":
            return approval.copy()

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
        return bool(approval and approval.get("status") == "approved")

    # ============================================================
    # INTERNAL
    # ============================================================
    def _require(self, approval_id: str) -> Dict[str, Any]:
        if not approval_id or approval_id not in self._approvals:
            raise KeyError("Approval not found")
        return self._approvals[approval_id]
