"""
RBAC SERVICE — CANONICAL (FAZA 9)

Uloga:
- jedini izvor istine za RBAC pravila
- centralizuje dozvole po:
  - ulozi
  - akciji
- READ-ONLY
- bez side-effecta
"""

from typing import Dict, Any
from copy import deepcopy


class RBACService:
    def __init__(self):
        # --------------------------------------------------------
        # ROLE DEFINITIONS (CANONICAL, STATIC)
        # --------------------------------------------------------
        self._roles: Dict[str, Dict[str, Any]] = {
            # ----------------------------------
            # SYSTEM (OS INTERNAL — BRAIN / OWNER)
            # ----------------------------------
            "system": {
                "can_request": True,
                "can_execute": False,
                "allowed_actions": {
                    "system_query",
                    "system_identity",
                    "system_notion_inbox",
                    "system_inbox_delegation_preview",
                },
            },

            # ----------------------------------
            # CEO (HUMAN DECISION MAKER)
            # ----------------------------------
            "ceo": {
                "can_request": True,
                "can_execute": False,
                "allowed_actions": {
                    "goal_write",
                    "update_goal",
                    "create_task",
                    "create_project",
                    "query_database",
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
        if not isinstance(role, str) or not role:
            return {}
        role_def = self._roles.get(role)
        return deepcopy(role_def) if role_def else {}

    # ============================================================
    # CHECKS (READ-ONLY)
    # ============================================================
    def can_request(self, role: str) -> bool:
        role_def = self._roles.get(role)
        return bool(role_def and role_def.get("can_request") is True)

    def can_execute(self, role: str) -> bool:
        role_def = self._roles.get(role)
        return bool(role_def and role_def.get("can_execute") is True)

    def is_action_allowed(self, role: str, action: str) -> bool:
        if not isinstance(role, str) or not isinstance(action, str):
            return False

        role_def = self._roles.get(role)
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
            "roles": deepcopy(self._roles),
            "read_only": True,
        }
