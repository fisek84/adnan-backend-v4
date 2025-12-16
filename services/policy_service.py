# services/policy_service.py

"""
ENTERPRISE POLICY SERVICE — FAZA 13 + FAZA 16.1 (ALIGNED)

Uloga:
- statički enterprise policy sloj
- kontekstualna pravila (context, global)
- RBAC pitanja DELEGIRA na RBACService
- READ-ONLY
- enforcement ostaje izvan ovog servisa
"""

from typing import Dict, Any, Optional
from services.rbac_service import RBACService


class PolicyService:
    def __init__(self):
        # --------------------------------------------------------
        # GLOBAL POLICIES (STATIC, READ-ONLY)
        # --------------------------------------------------------
        self.global_policies: Dict[str, Any] = {
            "allow_write_actions": True,
            "require_confirmation_for_write": True,
            "max_parallel_steps": 5,
        }

        # --------------------------------------------------------
        # CONTEXT POLICIES (STATIC, READ-ONLY)
        # --------------------------------------------------------
        self.context_policies: Dict[str, Dict[str, Any]] = {
            "chat": {
                "execution_allowed": False,
            },
            "knowledge": {
                "execution_allowed": False,
            },
            "sop": {
                "execution_allowed": True,
            },
            "meta": {
                "execution_allowed": False,
            },
            "system": {
                "execution_allowed": True,
            },
        }

        # --------------------------------------------------------
        # RBAC (SINGLE SOURCE OF TRUTH)
        # --------------------------------------------------------
        self.rbac = RBACService()

    # ============================================================
    # GLOBAL POLICY (READ-ONLY)
    # ============================================================
    def get_global_policy(self) -> Dict[str, Any]:
        return dict(self.global_policies)

    # ============================================================
    # CONTEXT POLICY (READ-ONLY)
    # ============================================================
    def get_context_policy(self, context_type: str) -> Optional[Dict[str, Any]]:
        if not context_type:
            return None
        policy = self.context_policies.get(context_type)
        return dict(policy) if policy else None

    # ============================================================
    # RBAC PROXIES (READ-ONLY)
    # ============================================================
    def get_role_policy(self, role: str) -> Dict[str, Any]:
        return self.rbac.get_role(role)

    def is_action_allowed_for_role(self, role: str, action: str) -> bool:
        if not role or not action:
            return False
        return self.rbac.is_action_allowed(role, action)

    def can_request(self, role: str) -> bool:
        if not role:
            return False
        return self.rbac.can_request(role)

    def can_execute(self, role: str) -> bool:
        if not role:
            return False
        return self.rbac.can_execute(role)

    # ============================================================
    # POLICY SNAPSHOT (UI / AUDIT)
    # ============================================================
    def get_policy_snapshot(self) -> Dict[str, Any]:
        return {
            "global": dict(self.global_policies),
            "contexts": dict(self.context_policies),
            "rbac": self.rbac.get_rbac_snapshot(),
            "read_only": True,
        }
