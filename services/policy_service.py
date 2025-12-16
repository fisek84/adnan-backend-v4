# services/policy_service.py

"""
ENTERPRISE POLICY SERVICE — FAZA 9 (POLICY EVOLUTION)

Uloga:
- statički policy sloj (kanonski)
- policy se NE izvršava
- policy se NE evaluira ovdje
- policy se SAMO izlaže (READ-ONLY)
- enforcement je izvan ovog servisa
"""

from typing import Dict, Any, Optional
from copy import deepcopy
from services.rbac_service import RBACService


class PolicyService:
    def __init__(self):
        # --------------------------------------------------------
        # GLOBAL POLICIES (STATIC, READ-ONLY)
        # --------------------------------------------------------
        self._global_policies: Dict[str, Any] = {
            "allow_write_actions": True,
            "require_confirmation_for_write": True,
            "max_parallel_steps": 5,
        }

        # --------------------------------------------------------
        # CONTEXT POLICIES (STATIC, READ-ONLY)
        # --------------------------------------------------------
        self._context_policies: Dict[str, Dict[str, Any]] = {
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
        self._rbac = RBACService()

    # ============================================================
    # GLOBAL POLICY (READ-ONLY)
    # ============================================================
    def get_global_policy(self) -> Dict[str, Any]:
        return deepcopy(self._global_policies)

    # ============================================================
    # CONTEXT POLICY (READ-ONLY)
    # ============================================================
    def get_context_policy(self, context_type: str) -> Optional[Dict[str, Any]]:
        if not isinstance(context_type, str) or not context_type:
            return None

        policy = self._context_policies.get(context_type)
        return deepcopy(policy) if policy else None

    # ============================================================
    # RBAC PROXIES (READ-ONLY)
    # ============================================================
    def get_role_policy(self, role: str) -> Dict[str, Any]:
        if not role:
            return {}
        return self._rbac.get_role(role)

    def is_action_allowed_for_role(self, role: str, action: str) -> bool:
        if not role or not action:
            return False
        return self._rbac.is_action_allowed(role, action)

    def can_request(self, role: str) -> bool:
        if not role:
            return False
        return self._rbac.can_request(role)

    def can_execute(self, role: str) -> bool:
        if not role:
            return False
        return self._rbac.can_execute(role)

    # ============================================================
    # POLICY SNAPSHOT (UI / AUDIT)
    # ============================================================
    def get_policy_snapshot(self) -> Dict[str, Any]:
        return {
            "global": deepcopy(self._global_policies),
            "contexts": deepcopy(self._context_policies),
            "rbac": self._rbac.get_rbac_snapshot(),
            "read_only": True,
        }
