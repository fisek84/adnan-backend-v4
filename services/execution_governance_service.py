"""
EXECUTION GOVERNANCE SERVICE — CANONICAL (FAZA 9)
"""

from typing import Dict, Any, Optional
from datetime import datetime

from services.policy_service import PolicyService
from services.action_safety_service import ActionSafetyService
from services.approval_state_service import get_approval_state


class ExecutionGovernanceService:
    def __init__(self):
        self.policy = PolicyService()
        self.safety = ActionSafetyService()

        # 🔒 SHARED approval state (CANONICAL)
        self.approvals = get_approval_state()

        self._governance_limits = {
            "max_execution_time_seconds": 30,
            "retry_policy": {
                "enabled": False,
                "max_retries": 0,
            },
        }

        self._meta_commands = {"delegate_execution"}

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
        # HARD VALIDATION
        # --------------------------------------------------------
        if not isinstance(role, str) or not isinstance(context_type, str) or not isinstance(directive, str):
            return self._block("Invalid execution request.", "governance", decision_ts)

        # --------------------------------------------------------
        # CONTEXT POLICY
        # --------------------------------------------------------
        context_policy = self.policy.get_context_policy(context_type)
        if context_policy and context_policy.get("execution_allowed") is False:
            return self._block("Execution not allowed in this context.", "policy", decision_ts)

        # --------------------------------------------------------
        # RBAC (POLICY-DRIVEN)
        # --------------------------------------------------------
        if not (role == "system" and directive == "system_query"):
            if not self.policy.can_request(role):
                return self._block(
                    f"Role '{role}' cannot request execution.",
                    "policy",
                    decision_ts,
                )

        if not self.policy.is_action_allowed_for_role(role, directive):
            return self._block(
                f"Role '{role}' is not allowed to perform '{directive}'.",
                "policy",
                decision_ts,
            )

        # --------------------------------------------------------
        # SAFETY
        # --------------------------------------------------------
        safety = self.safety.validate_action(directive, params or {})
        if safety.get("allowed") is not True:
            return self._block(
                safety.get("reason", "Safety validation failed."),
                "safety",
                decision_ts,
            )

        # --------------------------------------------------------
        # APPROVAL HARD-GATE
        # --------------------------------------------------------
        if directive != "system_query":

            if directive in self._meta_commands:
                if not approval_id or not self.approvals.is_fully_approved(approval_id):
                    return self._block(
                        "Approved approval required for meta execution.",
                        "governance",
                        decision_ts,
                        next_csi_state="DECISION_PENDING",
                        read_only=False,
                        approval_id=approval_id,
                    )

            else:
                if not approval_id:
                    approval = self.approvals.create(
                        command=directive,
                        payload_summary=params or {},
                        scope=context_type,
                        risk_level="standard",
                    )
                    return self._block(
                        "Approval required for write operation.",
                        "governance",
                        decision_ts,
                        next_csi_state="DECISION_PENDING",
                        read_only=False,
                        approval_id=approval["approval_id"],
                    )

                if not self.approvals.is_fully_approved(approval_id):
                    return self._block(
                        "Approval not granted.",
                        "governance",
                        decision_ts,
                        next_csi_state="DECISION_PENDING",
                        read_only=False,
                        approval_id=approval_id,
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
            "governance": self._governance_limits,
            "timestamp": decision_ts,
        }

    # ============================================================
    # INTERNAL
    # ============================================================
    def _block(
        self,
        reason: str,
        source: str,
        ts: str,
        *,
        next_csi_state: str = "IDLE",
        read_only: bool = True,
        approval_id: Optional[str] = None,
    ) -> Dict[str, Any]:

        response = {
            "allowed": False,
            "reason": reason,
            "source": source,
            "read_only": read_only,
            "next_csi_state": next_csi_state,
            "governance": self._governance_limits,
            "timestamp": ts,
        }

        if approval_id:
            response["approval_id"] = approval_id

        return response
