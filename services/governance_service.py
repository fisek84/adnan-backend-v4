from typing import Dict, Any
from datetime import datetime


class GovernanceService:
    """
    Governance / Policy Layer — FAZA 9 (POLICY EVOLUTION)

    PURPOSE:
    - Final permission check before execution
    - HARD global write gate
    - Explicit write intent required
    - Deterministic rules only
    - NO side effects
    """

    # ============================================================
    # GLOBAL WRITE SWITCH (STATIC, CANONICAL)
    # ============================================================
    GLOBAL_WRITE_ENABLED = True  # 🔓 ENABLED

    WRITE_COMMANDS = {
        "create_database_entry",
        "update_database_entry",
        "create_page",
        "delete_page",
    }

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

        if not isinstance(decision, dict):
            return self._deny("Nema odluke za evaluaciju.")

        executor = decision.get("executor")
        command = decision.get("command")

        if not executor or not command:
            return self._deny("Nepotpuna odluka.")

        # --------------------------------------------------
        # WRITE INTENT + GLOBAL WRITE LOCK
        # --------------------------------------------------
        if command in self.WRITE_COMMANDS:
            if not self.GLOBAL_WRITE_ENABLED:
                return self._deny("Global WRITE je onemogućen (safety lock).")

            if decision.get("write_intent") is not True:
                return self._deny("WRITE operacija zahtijeva eksplicitni write_intent.")

        # --------------------------------------------------
        # TIME-BASED SAFETY RULE (DETERMINISTIC)
        # --------------------------------------------------
        hour = datetime.utcnow().hour
        if executor == "agent" and hour < 5:
            return self._deny(
                "Agent WRITE operacije su privremeno blokirane (noćni režim)."
            )

        # --------------------------------------------------
        # SOP CONFIRMATION GUARANTEE
        # --------------------------------------------------
        if executor == "sop_execution_manager":
            if decision.get("confirmed") is not True:
                return self._deny("SOP nije eksplicitno potvrđen.")

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
