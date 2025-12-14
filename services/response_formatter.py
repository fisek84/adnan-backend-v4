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
    - LOCKED response contract
    - Backend is the only voice
    - Frontend renders, never interprets
    - STATE has priority over payload
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
            raise RuntimeError(f"Illegal awareness level: {awareness_level}")

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
        # CRITICAL AWARENESS OVERRIDE
        # --------------------------------------------------
        if awareness_level == "critical" and not execution_result:
            response["status"] = "failed"
            response["message"] = "Došlo je do greške u sistemu."
            return self._finalize(response)

        # --------------------------------------------------
        # REAL EXECUTION RESULT ONLY
        # --------------------------------------------------
        if execution_result and isinstance(execution_result, dict) and "success" in execution_result:
            if execution_result.get("success") is True:
                response["status"] = "completed"
                response["message"] = "Završeno. Sve je prošlo bez problema."
            else:
                response["status"] = "failed"
                response["message"] = "Zaustavljeno. Došlo je do greške tokom izvršenja."
            return self._finalize(response)

        # --------------------------------------------------
        # DECISION PENDING (STATE-DRIVEN — FAZA D1)
        # --------------------------------------------------
        if state == "DECISION_PENDING":
            response["status"] = "waiting_confirmation"
            response["message"] = "Čekam tvoju potvrdu. (da / ok)"
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
