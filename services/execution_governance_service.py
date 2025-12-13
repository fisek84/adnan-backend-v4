# services/execution_governance_service.py

"""
EXECUTION GOVERNANCE SERVICE — FAZA 19 (FINAL LOCKDOWN)

Uloga:
- centralna, zadnja tačka odluke prije izvršenja
- kombinuje signale iz:
  - PolicyService
  - RBACService
  - ApprovalStateService
  - ActionSafetyService
- NE izvršava ništa
- NE donosi poslovne odluke
- vraća determinističku odluku: ALLOWED / BLOCKED
"""

from typing import Dict, Any, Optional

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

        # --------------------------------------------------------
        # GOVERNANCE LIMITS — CANONICAL (V1.0)
        # --------------------------------------------------------
        self.governance_limits = {
            "max_execution_time_seconds": 30,
            "retry_policy": {
                "enabled": False,
                "max_retries": 0,
            },
            "escalation_signal": None,
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
        """
        Vraća:
        {
            "allowed": bool,
            "reason": "...",
            "source": "...",
            "read_only": True,
            "governance": {...}
        }
        """

        # --------------------------------------------------------
        # 1. CONTEXT POLICY
        # --------------------------------------------------------
        context_policy = self.policy.get_context_policy(context_type)
        if context_policy and not context_policy.get("execution_allowed", False):
            return self._block(
                reason="Execution not allowed in this context.",
                source="context_policy",
            )

        # --------------------------------------------------------
        # 2. RBAC — REQUEST LEVEL
        # --------------------------------------------------------
        if not self.policy.can_request(role):
            return self._block(
                reason=f"Role '{role}' cannot request execution.",
                source="rbac_request",
            )

        # --------------------------------------------------------
        # 3. RBAC — ACTION LEVEL
        # --------------------------------------------------------
        if not self.policy.is_action_allowed_for_role(role, directive):
            return self._block(
                reason=f"Role '{role}' is not allowed to perform '{directive}'.",
                source="rbac_action",
            )

        # --------------------------------------------------------
        # 4. SAFETY LAYER
        # --------------------------------------------------------
        safety = self.safety.validate_action(directive, params)
        if not safety.get("allowed"):
            return self._block(
                reason=safety.get("reason", "Safety validation failed."),
                source="safety",
            )

        # --------------------------------------------------------
        # 5. APPROVAL STATE (IF REQUIRED)
        # --------------------------------------------------------
        if approval_id:
            if not self.approvals.is_fully_approved(approval_id):
                return self._block(
                    reason="Required approvals are not completed.",
                    source="approval",
                )

        # --------------------------------------------------------
        # 6. GLOBAL POLICY (FINAL)
        # --------------------------------------------------------
        global_policy = self.policy.get_global_policy()
        if not global_policy.get("allow_write_actions", True):
            return self._block(
                reason="Global policy blocks write actions.",
                source="global_policy",
            )

        # --------------------------------------------------------
        # ALLOWED
        # --------------------------------------------------------
        return {
            "allowed": True,
            "reason": "Execution allowed by governance.",
            "source": "governance",
            "read_only": True,
            "governance": self.governance_limits,
        }

    # ============================================================
    # INTERNAL
    # ============================================================
    def _block(self, *, reason: str, source: str) -> Dict[str, Any]:
        return {
            "allowed": False,
            "reason": reason,
            "source": source,
            "read_only": True,
            "governance": self.governance_limits,
        }
