# services/approval_state_service.py

from typing import Dict, Any
from datetime import datetime
from uuid import uuid4
from threading import Lock
import json


class ApprovalStateService:
    """
    CANONICAL APPROVAL STATE SERVICE

    - approval je VEZAN za execution_id
    - nema approvala bez execution_id
    - approval lifecycle: pending -> approved | rejected
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
        execution_id: str,
    ) -> Dict[str, Any]:

        if not execution_id:
            raise ValueError("execution_id is required for approval")

        payload_key = json.dumps(payload_summary or {}, sort_keys=True)

        with self._lock:
            for approval in self._approvals.values():
                if (
                    approval["command"] == command
                    and approval["payload_key"] == payload_key
                    and approval["execution_id"] == execution_id
                    and approval["status"] == "approved"
                ):
                    return approval.copy()

            approval_id = str(uuid4())
            now = datetime.utcnow().isoformat()

            approval = {
                "approval_id": approval_id,
                "execution_id": execution_id,
                "command": command,
                "payload_summary": payload_summary,
                "payload_key": payload_key,
                "scope": scope,
                "risk_level": risk_level,
                "status": "pending",
                "created_at": now,
            }

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

            approval["status"] = "approved"
            approval["decided_at"] = datetime.utcnow().isoformat()
            return approval.copy()

    def reject(self, approval_id: str) -> Dict[str, Any]:
        with self._lock:
            approval = self._require(approval_id)
            if approval["status"] != "pending":
                return approval.copy()

            approval["status"] = "rejected"
            approval["decided_at"] = datetime.utcnow().isoformat()
            return approval.copy()

    # ============================================================
    # READ
    # ============================================================
    def is_fully_approved(self, approval_id: str) -> bool:
        with self._lock:
            approval = self._approvals.get(approval_id)
            return bool(approval and approval["status"] == "approved")

    def get(self, approval_id: str) -> Dict[str, Any]:
        with self._lock:
            return self._require(approval_id).copy()

    # ============================================================
    # INTERNAL
    # ============================================================
    def _require(self, approval_id: str) -> Dict[str, Any]:
        if approval_id not in self._approvals:
            raise KeyError("Approval not found")
        return self._approvals[approval_id]


# ============================================================
# CANONICAL SINGLETON
# ============================================================

_APPROVAL_STATE_SINGLETON = ApprovalStateService()


def get_approval_state() -> ApprovalStateService:
    return _APPROVAL_STATE_SINGLETON
