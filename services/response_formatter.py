from typing import Any, Dict, Optional


# ============================================================
# RESPONSE CONTRACT (V1.1 LOCK)
# ============================================================

ALLOWED_STATUSES = {
    "idle",
    "sop_list",
    "sop_active",
    "waiting_confirmation",
    "executing",
    "completed",
    "failed",
}

ALLOWED_AWARENESS_LEVELS = {
    "idle",
    "active",
    "critical",
}


class ResponseFormatter:
    """
    ResponseFormatter — V1.1 SINGLE RESPONSE AUTHORITY

    RULES:
    - This is a LOCKED response contract
    - Backend is the only voice
    - Frontend renders, never interprets
    - Tone is derived ONLY from awareness
    """

    CONTRACT_VERSION = "1.1"

    def format(
        self,
        intent: str,
        confidence: float,
        csi_state: Dict[str, Any],
        decision: Optional[Dict[str, Any]] = None,
        execution_result: Optional[Dict[str, Any]] = None,
        request_id: Optional[str] = None,
        awareness: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:

        state = csi_state.get("state", "IDLE")

        awareness_level = (
            awareness.get("awareness_level")
            if awareness else "idle"
        )

        if awareness_level not in ALLOWED_AWARENESS_LEVELS:
            raise RuntimeError(
                f"Illegal awareness level: {awareness_level}"
            )

        response: Dict[str, Any] = {
            "contract_version": self.CONTRACT_VERSION,
            "request_id": request_id,
            "state": state,
            "intent": intent,
            "confidence": confidence,
            "awareness_level": awareness_level,
            "status": "idle",
            "message": "",
        }

        # --------------------------------------------------
        # CRITICAL AWARENESS OVERRIDE (V1.1)
        # --------------------------------------------------
        if awareness_level == "critical" and execution_result is None:
            response["status"] = "failed"
            response["message"] = "Došlo je do greške u sistemu."
            return self._finalize(response)

        # --------------------------------------------------
        # EXECUTION RESULT (HIGHEST PRIORITY)
        # --------------------------------------------------
        if execution_result is not None:
            if execution_result.get("success"):
                response["status"] = "completed"
                response["message"] = "Završeno. Sve je prošlo bez problema."
            else:
                response["status"] = "failed"
                response["message"] = "Zaustavljeno. Došlo je do greške tokom izvršenja."
            return self._finalize(response)

        # --------------------------------------------------
        # DECISION PENDING
        # --------------------------------------------------
        if decision and decision.get("decision_candidate") and not decision.get("confirmed"):
            response["status"] = "waiting_confirmation"
            response["message"] = (
                decision.get("system_response")
                or "Prije nego nastavim, trebam tvoju potvrdu."
            )
            return self._finalize(response)

        # --------------------------------------------------
        # EXECUTING
        # --------------------------------------------------
        if state == "EXECUTING":
            response["status"] = "executing"
            response["message"] = "Radim. Javit ću kad završim."
            return self._finalize(response)

        # --------------------------------------------------
        # SOP ACTIVE
        # --------------------------------------------------
        if state == "SOP_ACTIVE":
            response["status"] = "sop_active"
            response["message"] = "Ovo je aktivni SOP. Reci ako želiš da ga izvršim."
            return self._finalize(response)

        # --------------------------------------------------
        # SOP LIST
        # --------------------------------------------------
        if state == "SOP_LIST":
            response["status"] = "sop_list"
            response["message"] = "Evo dostupnih SOP-ova."
            return self._finalize(response)

        # --------------------------------------------------
        # DEFAULT / IDLE
        # --------------------------------------------------
        response["status"] = "idle"
        response["message"] = "Razumijem. Nastavi."
        return self._finalize(response)

    # ============================================================
    # FINAL CONTRACT GUARD
    # ============================================================
    def _finalize(self, response: Dict[str, Any]) -> Dict[str, Any]:
        status = response.get("status")
        if status not in ALLOWED_STATUSES:
            raise RuntimeError(f"Illegal response status: {status}")

        return response
