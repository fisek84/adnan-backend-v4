# services/execution_governance_service.py

"""
EXECUTION GOVERNANCE SERVICE — CANONICAL (FAZA 3.6)

Uloga:
- CENTRALNA i ZADNJA tačka odluke prije izvršenja
- NE izvršava
- NE shape-a response
- NE piše stanje
- deterministički odlučuje: ALLOWED | BLOCKED
- eksplicitno označava FAILURE SOURCE za FailureHandler
"""

from typing import Dict, Any, Optional
from datetime import datetime

from services.policy_service import PolicyService
from services.rbac_service import RBACService
from services.approval_state_service import ApprovalStateService
from services.action_safety_service import ActionSafetyService


class ExecutionGovernanceService:
    def __init__(self):
        self.policy = PolicyService()
        self.rbac = RBACService()
        self.approvals = ApprovalStateService()
        self.safety = ActionSafetyService()

        self.governance_limits = {
            "max_execution_time_seconds": 30,
            "retry_policy": {
                "enabled": False,
                "max_retries": 0,
            },
        }

        # META commands:
        # - zahtijevaju već ODOBRENU approval
        # - NE smiju triggerovati novi approval flow
        self.meta_commands = {
            "delegate_execution",
        }

    # ============================================================
    # PUBLIC API
    # ============================================================
    def evaluate(
        self,
        *,
        role: str,
        context_type: str,
        directive: str,
        params: Dict[str, Any],
        approval_id: Optional[str] = None,
    ) -> Dict[str, Any]:

        decision_ts = datetime.utcnow().isoformat()

        # --------------------------------------------------------
        # 0. HARD INPUT VALIDATION (DETERMINISTIC)
        # --------------------------------------------------------
        if not role or not context_type or not directive:
            return self._block(
                reason="Invalid execution request.",
                source="governance",
                ts=decision_ts,
            )

        # --------------------------------------------------------
        # 1. CONTEXT POLICY
        # --------------------------------------------------------
        context_policy = self.policy.get_context_policy(context_type)
        if context_policy and not context_policy.get("execution_allowed", False):
            return self._block(
                reason="Execution not allowed in this context.",
                source="policy",
                ts=decision_ts,
            )

        # --------------------------------------------------------
        # 2. RBAC — REQUEST LEVEL
        # --------------------------------------------------------
        if not (role == "system" and directive == "system_query"):
            if not self.policy.can_request(role):
                return self._block(
                    reason=f"Role '{role}' cannot request execution.",
                    source="policy",
                    ts=decision_ts,
                )

        # --------------------------------------------------------
        # 3. RBAC — ACTION LEVEL
        # --------------------------------------------------------
        if not self.policy.is_action_allowed_for_role(role, directive):
            return self._block(
                reason=f"Role '{role}' is not allowed to perform '{directive}'.",
                source="policy",
                ts=decision_ts,
            )

        # --------------------------------------------------------
        # 4. SAFETY LAYER
        # --------------------------------------------------------
        safety = self.safety.validate_action(directive, params or {})
        if not safety.get("allowed", False):
            return self._block(
                reason=safety.get("reason", "Safety validation failed."),
                source="safety",
                ts=decision_ts,
            )

        # --------------------------------------------------------
        # 5. APPROVAL (WRITE — HARD GATE)
        # --------------------------------------------------------
        if directive != "system_query":

            # META commands — approval mora POSTOJATI i biti approved
            if directive in self.meta_commands:
                if not approval_id or not self.approvals.is_fully_approved(approval_id):
                    return self._block(
                        reason="Approved approval required for meta execution.",
                        source="governance",
                        ts=decision_ts,
                        next_csi_state="DECISION_PENDING",
                        read_only=False,
                    )

            # REAL WRITE commands
            else:
                if not approval_id:
                    return self._block(
                        reason="Missing approval for write operation.",
                        source="governance",
                        ts=decision_ts,
                        next_csi_state="DECISION_PENDING",
                        read_only=False,
                    )

                if not self.approvals.is_fully_approved(approval_id):
                    return self._block(
                        reason="Approval not granted.",
                        source="governance",
                        ts=decision_ts,
                        next_csi_state="DECISION_PENDING",
                        read_only=False,
                    )

        # --------------------------------------------------------
        # ALLOWED
        # --------------------------------------------------------
        return {
            "allowed": True,
            "reason": "Execution allowed by governance.",
            "source": "governance",
            "read_only": directive == "system_query",
            "next_csi_state": "EXECUTING",
            "governance": self.governance_limits,
            "timestamp": decision_ts,
        }

    # ============================================================
    # INTERNALS
    # ============================================================
    def _block(
        self,
        *,
        reason: str,
        source: str,
        ts: str,
        next_csi_state: str = "IDLE",
        read_only: bool = True,
    ) -> Dict[str, Any]:
        return {
            "allowed": False,
            "reason": reason,
            "source": source,
            "read_only": read_only,
            "next_csi_state": next_csi_state,
            "governance": self.governance_limits,
            "timestamp": ts,
        }
