# services/approval_state_service.py

from typing import Dict, Any, List, Optional
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

    NOTE (stabilnost testova):
    - svi instance-i dijele isti backing store (class-level), da se izbjegne
      “approval not found in pending list” kad različiti dijelovi koda kreiraju
      novu instancu servisa.
    """

    _GLOBAL_APPROVALS: Dict[str, Dict[str, Any]] = {}
    _GLOBAL_LOCK: Lock = Lock()

    def __init__(self):
        self._approvals = ApprovalStateService._GLOBAL_APPROVALS
        self._lock = ApprovalStateService._GLOBAL_LOCK

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

        try:
            payload_key = json.dumps(payload_summary or {}, sort_keys=True, default=str)
        except Exception:
            payload_key = "{}"

        with self._lock:
            # replay: ako već postoji pending ili approved za isti execution_id+command+payload
            for approval in self._approvals.values():
                if (
                    approval.get("command") == command
                    and approval.get("payload_key") == payload_key
                    and approval.get("execution_id") == execution_id
                    and approval.get("status") in ("pending", "approved")
                ):
                    return approval.copy()

            approval_id = str(uuid4())
            now = datetime.utcnow().isoformat()

            approval = {
                "approval_id": approval_id,
                "execution_id": execution_id,
                "command": command,
                "payload_summary": payload_summary or {},
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
            return bool(approval and approval.get("status") == "approved")

    def get(self, approval_id: str) -> Dict[str, Any]:
        with self._lock:
            return self._require(approval_id).copy()

    def list_approvals(self, status: Optional[str] = None) -> List[Dict[str, Any]]:
        with self._lock:
            vals = list(self._approvals.values())
            if status:
                vals = [a for a in vals if a.get("status") == status]
            return [a.copy() for a in vals]

    def list_pending(self) -> List[Dict[str, Any]]:
        return self.list_approvals(status="pending")

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
