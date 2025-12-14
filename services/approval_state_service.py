"""
APPROVAL STATE SERVICE — FAZA 8 (ESCALATION READY)

Uloga:
- modelira stanje višeslojnih odobrenja
- eksplicitna eskalacija ka čovjeku
- deterministički approval lifecycle
- NEMA izvršenja
- NEMA automatike
"""

from typing import Dict, Any, List, Optional
from datetime import datetime


class ApprovalStateService:
    def __init__(self):
        # In-memory state (kanonski)
        self._approvals: Dict[str, Dict[str, Any]] = {}

    # ============================================================
    # CREATE / REGISTER
    # ============================================================
    def register_approval(
        self,
        *,
        approval_id: str,
        required_levels: List[str],
        initiated_by: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        escalation_reason: Optional[str] = None,
    ) -> Dict[str, Any]:

        if approval_id not in self._approvals:
            self._approvals[approval_id] = {
                "approval_id": approval_id,
                "required_levels": list(required_levels),
                "approved_levels": [],
                "approval_log": [],
                "initiated_by": initiated_by,
                "escalation_reason": escalation_reason,
                "created_at": datetime.utcnow().isoformat(),
                "metadata": metadata or {},
            }

        return self.get_state(approval_id)

    # ============================================================
    # ESCALATE TO HUMAN (EXPLICIT)
    # ============================================================
    def escalate(
        self,
        *,
        approval_id: str,
        escalated_by: str,
        reason: str,
    ) -> Optional[Dict[str, Any]]:

        state = self._approvals.get(approval_id)
        if not state:
            return None

        state["approval_log"].append({
            "level": "ESCALATION",
            "approved_by": escalated_by,
            "note": reason,
            "ts": datetime.utcnow().isoformat(),
        })

        state["metadata"]["escalated"] = True
        state["metadata"]["escalated_at"] = datetime.utcnow().isoformat()
        state["metadata"]["escalation_reason"] = reason

        return self.get_state(approval_id)

    # ============================================================
    # APPROVE (ONE LEVEL AT A TIME)
    # ============================================================
    def approve_next_level(
        self,
        *,
        approval_id: str,
        approved_by: str,
        note: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:

        state = self._approvals.get(approval_id)
        if not state:
            return None

        approved = state.get("approved_levels", [])
        required = state.get("required_levels", [])

        if len(approved) >= len(required):
            return self.get_state(approval_id)

        next_level = required[len(approved)]

        approved.append(next_level)
        state["approved_levels"] = approved

        state["approval_log"].append({
            "level": next_level,
            "approved_by": approved_by,
            "note": note,
            "ts": datetime.utcnow().isoformat(),
        })

        return self.get_state(approval_id)

    # ============================================================
    # READ STATE
    # ============================================================
    def get_state(self, approval_id: str) -> Optional[Dict[str, Any]]:
        state = self._approvals.get(approval_id)
        if not state:
            return None

        return self._build_view(state)

    # ============================================================
    # READ HELPERS
    # ============================================================
    def get_next_required_level(self, approval_id: str) -> Optional[str]:
        state = self._approvals.get(approval_id)
        if not state:
            return None

        approved = state.get("approved_levels", [])
        required = state.get("required_levels", [])

        if len(approved) >= len(required):
            return None

        return required[len(approved)]

    def is_fully_approved(self, approval_id: str) -> bool:
        state = self._approvals.get(approval_id)
        if not state:
            return False

        return state.get("approved_levels") == state.get("required_levels")

    # ============================================================
    # SNAPSHOT (UI / CEO SAFE)
    # ============================================================
    def get_overview(self) -> Dict[str, Any]:
        return {
            "active_approvals": [
                self._build_view(s) for s in self._approvals.values()
            ],
            "read_only": True,
        }

    # ============================================================
    # INTERNAL VIEW BUILDER
    # ============================================================
    def _build_view(self, state: Dict[str, Any]) -> Dict[str, Any]:
        approved = state.get("approved_levels", [])
        required = state.get("required_levels", [])

        return {
            "approval_id": state.get("approval_id"),
            "approved_levels": approved,
            "required_levels": required,
            "next_required_level": (
                required[len(approved)] if len(approved) < len(required) else None
            ),
            "fully_approved": approved == required,
            "approval_log": list(state.get("approval_log", [])),
            "initiated_by": state.get("initiated_by"),
            "escalation_reason": state.get("escalation_reason"),
            "created_at": state.get("created_at"),
            "metadata": state.get("metadata", {}),
            "read_only": True,
        }
