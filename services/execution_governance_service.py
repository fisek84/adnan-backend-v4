"""
EXECUTION GOVERNANCE SERVICE — CANONICAL

Uloga:
- centralna, zadnja tačka odluke prije izvršenja
- NE izvršava ništa
- vraća determinističku odluku + CSI tranziciju
"""

from typing import Dict, Any, Optional
from datetime import datetime

from services.policy_service import PolicyService
from services.rbac_service import RBACService
from services.approval_state_service import ApprovalStateService
from services.action_safety_service import ActionSafetyService
from services.memory_service import MemoryService


class ExecutionGovernanceService:
    def __init__(self):
        self.policy = PolicyService()
        self.rbac = RBACService()
        self.approvals = ApprovalStateService()
        self.safety = ActionSafetyService()
        self.memory = MemoryService()

        self.governance_limits = {
            "max_execution_time_seconds": 30,
            "retry_policy": {"enabled": False, "max_retries": 0},
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
        # 1. CONTEXT POLICY
        # --------------------------------------------------------
        context_policy = self.policy.get_context_policy(context_type)
        if context_policy and not context_policy.get("execution_allowed", False):
            result = self._block(
                reason="Execution not allowed in this context.",
                source="context_policy",
            )
            self._audit(decision_ts, role, context_type, directive, result)
            return result

        # --------------------------------------------------------
        # 2. RBAC — REQUEST LEVEL
        # --------------------------------------------------------
        # ✅ CANONICAL EXCEPTION:
        # SYSTEM may always request READ-ONLY commands
        if not (role == "system" and directive == "system_query"):
            if not self.policy.can_request(role):
                result = self._block(
                    reason=f"Role '{role}' cannot request execution.",
                    source="rbac_request",
                )
                self._audit(decision_ts, role, context_type, directive, result)
                return result

        # --------------------------------------------------------
        # 3. RBAC — ACTION LEVEL
        # --------------------------------------------------------
        if not self.policy.is_action_allowed_for_role(role, directive):
            result = self._block(
                reason=f"Role '{role}' is not allowed to perform '{directive}'.",
                source="rbac_action",
            )
            self._audit(decision_ts, role, context_type, directive, result)
            return result

        # --------------------------------------------------------
        # 4. SAFETY LAYER
        # --------------------------------------------------------
        safety = self.safety.validate_action(directive, params)
        if not safety.get("allowed"):
            result = self._block(
                reason=safety.get("reason", "Safety validation failed."),
                source="safety",
            )
            self._audit(decision_ts, role, context_type, directive, result)
            return result

        # --------------------------------------------------------
        # 5. APPROVAL STATE
        # --------------------------------------------------------
        if approval_id and not self.approvals.is_fully_approved(approval_id):
            result = {
                "allowed": False,
                "reason": "Awaiting required approvals.",
                "source": "approval",
                "read_only": True,
                "next_csi_state": "DECISION_PENDING",
                "governance": self.governance_limits,
            }
            self._audit(decision_ts, role, context_type, directive, result)
            return result

        # --------------------------------------------------------
        # ALLOWED
        # --------------------------------------------------------
        result = {
            "allowed": True,
            "reason": "Execution allowed by governance.",
            "source": "governance",
            "read_only": True,
            "next_csi_state": "EXECUTING",
            "governance": self.governance_limits,
        }

        self._audit(decision_ts, role, context_type, directive, result)
        return result

    # ============================================================
    # INTERNALS
    # ============================================================
    def _audit(self, ts, role, context_type, directive, result):
        self.memory.memory.setdefault("execution_stats", {})

    def _block(self, *, reason: str, source: str) -> Dict[str, Any]:
        return {
            "allowed": False,
            "reason": reason,
            "source": source,
            "read_only": True,
            "next_csi_state": "IDLE",
            "governance": self.governance_limits,
        }
