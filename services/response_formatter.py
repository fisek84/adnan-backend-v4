# services/response_formatter.py

from typing import Any, Dict, Optional


class ResponseFormatter:
    """
    Canonical response formatter.

    RULES:
    - Backend controls ALL wording
    - Frontend only renders message
    - No instruction-like prompts
    - No bot-style repetition
    """

    def format(
        self,
        intent: str,
        confidence: float,
        csi_state: Dict[str, Any],
        decision: Optional[Dict[str, Any]] = None,
        execution_result: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:

        state = csi_state.get("state")

        # --------------------------------------------------
        # EXECUTION RESULT HAS PRIORITY
        # --------------------------------------------------
        if execution_result:
            if execution_result.get("success"):
                return {
                    "message": "Završeno. Sve je prošlo bez problema.",
                    "state": state,
                }
            return {
                "message": "Zaustavljeno. Došlo je do greške tokom izvršenja.",
                "state": state,
            }

        # --------------------------------------------------
        # DECISION PENDING (CONFIRMATION)
        # --------------------------------------------------
        if decision and decision.get("decision_candidate") and not decision.get("confirmed"):
            msg = decision.get("system_response") or "Želiš li da nastavim?"
            return {
                "message": msg,
                "state": state,
            }

        # --------------------------------------------------
        # EXECUTING
        # --------------------------------------------------
        if state == "EXECUTING":
            return {
                "message": "Radim. Javit ću kad završim.",
                "state": state,
            }

        # --------------------------------------------------
        # SOP ACTIVE (VIEWED, NOT EXECUTED)
        # --------------------------------------------------
        if state == "SOP_ACTIVE":
            return {
                "message": "Ovo je aktivni SOP. Reci ako želiš da ga izvršim.",
                "state": state,
            }

        # --------------------------------------------------
        # SOP LIST
        # --------------------------------------------------
        if state == "SOP_LIST":
            return {
                "message": "Evo dostupnih SOP-ova.",
                "state": state,
            }

        # --------------------------------------------------
        # DEFAULT / IDLE
        # --------------------------------------------------
        return {
            "message": "Razumijem. Nastavi.",
            "state": state,
        }
