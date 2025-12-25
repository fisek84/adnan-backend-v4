# services/policy_service.py
# FULL FILE — zamijeni cijeli services/policy_service.py ovim.

from __future__ import annotations

import logging
import os

from services.rbac_service import RBACService

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class PolicyService:
    """
    CANONICAL POLICY SERVICE

    Odgovornost:
    - odlučuje da li initiator smije uopšte tražiti akciju (can_request)
    - odlučuje da li je directive dozvoljen za taj initiator (RBAC)
    - NE radi safety payload-inspection (to je drugi sloj)
    """

    def __init__(self) -> None:
        self.rbac = RBACService()
        self.ops_safe_mode = os.getenv("OPS_SAFE_MODE", "false").lower() == "true"

    # --------------------------------------------------------
    # INITIATOR POLICY
    # --------------------------------------------------------
    def can_request(self, initiator: str) -> bool:
        """
        Minimalna kanonska politika:
        - initiator mora biti poznat i mapiran na role
        """
        initiator_norm = (initiator or "").strip().lower()
        if not initiator_norm:
            return False

        role = self.rbac.get_role_for_initiator(initiator_norm)
        return role is not None

    # --------------------------------------------------------
    # ACTION (DIRECTIVE) POLICY
    # --------------------------------------------------------
    def is_action_allowed_for_role(self, initiator: str, directive: str) -> bool:
        """
        directive = AICommand.command (npr. "notion_write", "goal_task_workflow", "goal_write")
        """
        initiator_norm = (initiator or "").strip().lower()
        directive_norm = (directive or "").strip()

        if not initiator_norm or not directive_norm:
            return False

        role = self.rbac.get_role_for_initiator(initiator_norm)
        if role is None:
            return False

        # OPS_SAFE_MODE: global kill-switch za WRITE (ali read/propose može)
        if self.ops_safe_mode and self._is_write_directive(directive_norm):
            logger.warning(
                "OPS_SAFE_MODE active: blocking write directive=%s initiator=%s",
                directive_norm,
                initiator_norm,
            )
            return False

        return self.rbac.is_allowed(role, directive_norm)

    # --------------------------------------------------------
    # INTERNAL
    # --------------------------------------------------------
    @staticmethod
    def _is_write_directive(directive: str) -> bool:
        """
        Konzervativna klasifikacija (bolje block nego allow).
        """
        d = (directive or "").strip().lower()
        if not d:
            return True

        # eksplicitni write entrypoints u ovom sistemu
        if d in {"notion_write", "goal_write", "goal_task_workflow", "create_goal"}:
            return True

        # fallback: ako je nešto "write-ish"
        if "write" in d or "create" in d or "update" in d or "delete" in d:
            return True

        return False
