# services/rbac_service.py

"""
RBAC SERVICE — CANONICAL

Uloga:
- jedini izvor istine za RBAC pravila
- centralizuje dozvole po:
  - ulozi
  - akciji
- READ-ONLY
"""

from typing import Dict, Any


class RBACService:
    def __init__(self):
        # --------------------------------------------------------
        # ROLE DEFINITIONS (CANONICAL)
        # --------------------------------------------------------
        self.roles: Dict[str, Dict[str, Any]] = {
            # ----------------------------------
            # SYSTEM (OS INTERNAL)
            # ----------------------------------
            "system": {
                "can_request": True,
                "can_execute": False,  # system NE izvršava direktno
                "allowed_actions": {
                    "system_query",
                    "system_identity",
                    "system_notion_inbox",
                    "system_inbox_delegation_preview",
                },
            },

            # ----------------------------------
            # USER / CEO
            # ----------------------------------
            "user": {
                "can_request": True,
                "can_execute": False,
                "allowed_actions": {
                    "query_database",
                    "create_task",
                },
            },

            # ----------------------------------
            # MANAGER
            # ----------------------------------
            "manager": {
                "can_request": True,
                "can_execute": False,
                "allowed_actions": {
                    "query_database",
                    "create_database_entry",
                    "update_database_entry",
                },
            },

            # ----------------------------------
            # ADMIN
            # ----------------------------------
            "admin": {
                "can_request": True,
                "can_execute": True,
                "allowed_actions": "*",
            },
        }

    # ============================================================
    # ROLE LOOKUP (READ-ONLY)
    # ============================================================
    def get_role(self, role: str) -> Dict[str, Any]:
        if not role:
            return {}
        return self.roles.get(role, {}).copy()

    # ============================================================
    # CHECKS (READ-ONLY)
    # ============================================================
    def can_request(self, role: str) -> bool:
        role_def = self.roles.get(role)
        return bool(role_def and role_def.get("can_request"))

    def can_execute(self, role: str) -> bool:
        role_def = self.roles.get(role)
        return bool(role_def and role_def.get("can_execute"))

    def is_action_allowed(self, role: str, action: str) -> bool:
        if not role or not action:
            return False

        role_def = self.roles.get(role)
        if not role_def:
            return False

        allowed = role_def.get("allowed_actions")
        if not allowed:
            return False

        if allowed == "*":
            return True

        return action in allowed

    # ============================================================
    # SNAPSHOT (UI / AUDIT)
    # ============================================================
    def get_rbac_snapshot(self) -> Dict[str, Any]:
        return {
            "roles": self.roles,
            "read_only": True,
        }
