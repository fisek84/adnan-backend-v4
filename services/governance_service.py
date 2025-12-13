# C:\adnan-backend-v4\services\governance_service.py

from typing import Dict, Any
from datetime import datetime


class GovernanceService:
    """
    Governance / Policy Layer

    PURPOSE:
    - Final permission check before execution
    - No decisions
    - No execution
    - Deterministic rules only
    """

    def __init__(self):
        pass

    # --------------------------------------------------
    # MAIN ENTRYPOINT
    # --------------------------------------------------
    def evaluate(self, decision: Dict[str, Any]) -> Dict[str, Any]:
        """
        Evaluate whether a delegated action is allowed.

        Returns:
        {
            allowed: bool,
            reason: str | None
        }
        """

        # --------------------------------------------------
        # BASIC VALIDATION
        # --------------------------------------------------
        if not decision:
            return self._deny("Nema odluke za evaluaciju.")

        executor = decision.get("executor")
        command = decision.get("command")
        payload = decision.get("payload", {})

        if not executor or not command:
            return self._deny("Nepotpuna odluka.")

        # --------------------------------------------------
        # TIME-BASED RULE (EXAMPLE)
        # --------------------------------------------------
        hour = datetime.utcnow().hour
        if executor == "notion_ops" and hour < 5:
            return self._deny(
                "Notion operacije su privremeno blokirane (noćni režim)."
            )

        # --------------------------------------------------
        # SOP CONFIRMATION GUARANTEE
        # --------------------------------------------------
        if executor == "sop_execution_manager":
            if not decision.get("confirmed"):
                return self._deny(
                    "SOP nije eksplicitno potvrđen."
                )

        # --------------------------------------------------
        # DEFAULT ALLOW
        # --------------------------------------------------
        return {
            "allowed": True,
            "reason": None,
        }

    # --------------------------------------------------
    # HELPERS
    # --------------------------------------------------
    def _deny(self, reason: str) -> Dict[str, Any]:
        return {
            "allowed": False,
            "reason": reason,
        }
