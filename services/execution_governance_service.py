# services/execution_governance_service.py

from typing import Dict, Any, Optional
from datetime import datetime

from services.policy_service import PolicyService
from services.approval_state_service import get_approval_state


class ExecutionGovernanceService:
    """
    EXECUTION GOVERNANCE SERVICE — CANONICAL

    Pravilo:
    - Policy gleda KO TRAŽI (initiator), ne ko POSJEDUJE sistem
    - Governance NE ponavlja safety
    """

    def __init__(self):
        self.policy = PolicyService()
        self.approvals = get_approval_state()

        self._governance_limits = {
            "max_execution_time_seconds": 30,
            "retry_policy": {
                "enabled": False,
                "max_retries": 0,
            },
        }

    def evaluate(
        self,
        *,
        initiator: str,              # CEO
        context_type: str,
        directive: str,
        params: Dict[str, Any],
        execution_id: str,
        approval_id: Optional[str] = None,
    ) -> Dict[str, Any]:

        ts = datetime.utcnow().isoformat()

        # --------------------------------------------------------
        # BASIC VALIDATION
        # --------------------------------------------------------
        if not execution_id:
            return self._block("Missing execution_id.", ts)

        # --------------------------------------------------------
        # POLICY (INITIATOR-AWARE)
        # --------------------------------------------------------
        if not self.policy.can_request(initiator):
            return self._block("Initiator not allowed.", ts)

        if not self.policy.is_action_allowed_for_role(initiator, directive):
            return self._block("Action not allowed.", ts)

        # --------------------------------------------------------
        # APPROVAL GATE
        # --------------------------------------------------------
        if not approval_id:
            approval = self.approvals.create(
                command=directive,
                payload_summary=params or {},
                scope=context_type,
                risk_level="standard",
                execution_id=execution_id,
            )
            return self._block(
                "Approval required.",
                ts,
                approval_id=approval["approval_id"],
            )

        if not self.approvals.is_fully_approved(approval_id):
            return self._block(
                "Approval not granted.",
                ts,
                approval_id=approval_id,
            )

        # --------------------------------------------------------
        # ALLOWED
        # --------------------------------------------------------
        return {
            "allowed": True,
            "execution_id": execution_id,
            "read_only": False,
            "governance": self._governance_limits,
            "timestamp": ts,
        }

    def _block(
        self,
        reason: str,
        ts: str,
        approval_id: Optional[str] = None,
    ) -> Dict[str, Any]:

        resp = {
            "allowed": False,
            "reason": reason,
            "timestamp": ts,
            "governance": self._governance_limits,
        }

        if approval_id:
            resp["approval_id"] = approval_id

        return resp
