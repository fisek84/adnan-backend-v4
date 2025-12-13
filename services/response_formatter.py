# C:\adnan-backend-v4\services\response_formatter.py

from typing import Dict, Any, Optional


class ResponseFormatter:
    """
    Explainability & Response Formatter

    RULES:
    - No technical explanations
    - No architecture leakage
    - Natural, CEO-grade responses
    """

    def format(
        self,
        *,
        intent: str,
        confidence: float,
        csi_state: Dict[str, Any],
        decision: Optional[Dict[str, Any]] = None,
        execution_result: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Canonical response builder.
        """

        # --------------------------------------------------
        # EXECUTION RESULT (AGENT FINISHED)
        # --------------------------------------------------
        if execution_result:
            return self._format_execution_result(execution_result)

        # --------------------------------------------------
        # DECISION PHASE
        # --------------------------------------------------
        if decision:
            return self._format_decision(decision, confidence)

        # --------------------------------------------------
        # CSI-ONLY RESPONSE
        # --------------------------------------------------
        return self._format_csi_state(intent, csi_state)

    # ======================================================
    # INTERNAL FORMATTERS
    # ======================================================

    def _format_execution_result(self, result: Dict[str, Any]) -> Dict[str, Any]:
        if result.get("success"):
            return {
                "message": result.get("summary", "Završeno."),
                "status": "done",
            }

        return {
            "message": result.get("summary", "Došlo je do problema."),
            "status": "failed",
            "details": result.get("failed_steps"),
        }

    def _format_decision(self, decision: Dict[str, Any], confidence: float) -> Dict[str, Any]:
        if decision.get("confirmed"):
            return {
                "message": decision.get(
                    "system_response",
                    "Spremno za izvršenje."
                ),
                "status": "awaiting_execution",
                "confidence": round(confidence, 2),
            }

        return {
            "message": decision.get(
                "system_response",
                "Trebam potvrdu."
            ),
            "status": "awaiting_confirmation",
            "confidence": round(confidence, 2),
        }

    def _format_csi_state(self, intent: str, csi_state: Dict[str, Any]) -> Dict[str, Any]:
        state = csi_state.get("state")

        if state == "SOP_LIST":
            return {
                "message": "Koji SOP želiš pogledati?",
                "status": "awaiting_selection",
            }

        if state == "SOP_ACTIVE":
            return {
                "message": "Želiš li da pokrenem ovaj SOP?",
                "status": "awaiting_confirmation",
            }

        if state == "DECISION_PENDING":
            return {
                "message": "Da li da nastavim?",
                "status": "awaiting_confirmation",
            }

        return {
            "message": "Razumijem.",
            "status": "idle",
        }
