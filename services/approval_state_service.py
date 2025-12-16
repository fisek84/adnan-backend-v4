# services/approval_state_service.py

"""
APPROVAL STATE SERVICE — CANONICAL (FAZA 9)

Uloga:
- SINGLE SOURCE OF TRUTH za approval
- approval je vezan za TAČNO JEDAN AICommand
- approval lifecycle je deterministički
- NEMA izvršenja
- NEMA automatike
- READ-ONLY iz perspektive executiona
"""

from typing import Dict, Any
from datetime import datetime
from uuid import uuid4
from threading import Lock


class ApprovalStateService:
    """
    Minimalni, kanonski approval servis.

    Podržani lifecycle:
    pending -> approved | rejected
    """

    def __init__(self):
        self._approvals: Dict[str, Dict[str, Any]] = {}
        self._lock = Lock()

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

        if not isinstance(command, str) or not command:
            raise ValueError("Approval requires command.")

        approval_id = str(uuid4())
        now = datetime.utcnow().isoformat()

        approval = {
            "approval_id": approval_id,
            "command": command,
            "payload_summary": payload_summary or {},
            "scope": scope,
            "risk_level": risk_level,
            "requested_by": "system",
            "status": "pending",
            "created_at": now,
        }

        with self._lock:
            self._approvals[approval_id] = approval

        return approval.copy()

    # ============================================================
    # DECISIONS
    # ============================================================
    def approve(self, approval_id: str) -> Dict[str, Any]:
        with self._lock:
            approval = self._require(approval_id)

            if approval["status"] != "pending":
                return approval.copy()

            approved = {
                **approval,
                "status": "approved",
                "decided_at": datetime.utcnow().isoformat(),
            }

            self._approvals[approval_id] = approved
            return approved.copy()

    def reject(self, approval_id: str) -> Dict[str, Any]:
        with self._lock:
            approval = self._require(approval_id)

            if approval["status"] != "pending":
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
        with self._lock:
            return self._require(approval_id).copy()

    def is_fully_approved(self, approval_id: str) -> bool:
        with self._lock:
            approval = self._approvals.get(approval_id)
            return bool(approval and approval.get("status") == "approved")

    # ============================================================
    # INTERNAL
    # ============================================================
    def _require(self, approval_id: str) -> Dict[str, Any]:
        if not approval_id or approval_id not in self._approvals:
            raise KeyError("Approval not found")
        return self._approvals[approval_id]
