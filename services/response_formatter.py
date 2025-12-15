from typing import Any, Dict, Optional
import logging

logger = logging.getLogger(__name__)

# ============================================================
# RESPONSE CONTRACT (V2.0 — READ / WRITE SEPARATED)
# ============================================================

ALLOWED_STATUSES = {
    "idle",
    "sop_list",
    "sop_active",
    "waiting_confirmation",
    "executing",
    "completed",
    "failed",
    "blocked",
}

ALLOWED_AWARENESS_LEVELS = {
    "idle",
    "active",
    "critical",
}


class ResponseFormatter:
    """
    ResponseFormatter — SINGLE RESPONSE AUTHORITY

    Kanonska uloga:
    - formatira UX odgovor
    - NE izvršava
    - NE piše stanje
    - STROGO razdvaja READ (FAZA 2) i WRITE (FAZA 3)
    """

    CONTRACT_VERSION = "2.0"

    def format(
        self,
        intent: str,
        confidence: float,
        csi_state: Dict[str, Any],
        *,
        execution_result: Optional[Dict[str, Any]] = None,
        request_id: Optional[str] = None,
        awareness: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:

        try:
            state = csi_state.get("state", "IDLE")

            awareness_level = (
                awareness.get("awareness_level")
                if awareness else "idle"
            )

            if awareness_level not in ALLOWED_AWARENESS_LEVELS:
                logger.error("Illegal awareness level: %s", awareness_level)
                awareness_level = "idle"

            response: Dict[str, Any] = {
                "contract_version": self.CONTRACT_VERSION,
                "request_id": request_id,
                "state": state,
                "intent": intent,
                "confidence": confidence,
                "awareness_level": awareness_level,
                "status": "idle",
                "message": "",
                "read_only": True,
            }

            # ===================================================
            # READ PATH — FAZA 2 (SYSTEM SNAPSHOT)
            # ===================================================
            if (
                execution_result
                and execution_result.get("execution_state") == "COMPLETED"
                and "response" in execution_result
            ):
                response["status"] = "completed"
                response["message"] = execution_result.get("summary", "Stanje sistema.")
                response["snapshot"] = execution_result.get("response")
                response["read_only"] = True
                return self._finalize(response)

            # ===================================================
            # WRITE PATH — FAZA 3 (EXECUTION RESULT)
            # ===================================================
            if execution_result and "execution_state" in execution_result:
                execution_state = execution_result.get("execution_state")

                if execution_state == "BLOCKED":
                    response["status"] = "blocked"
                    response["message"] = execution_result.get("reason", "Izvršenje je blokirano.")
                elif execution_state == "FAILED":
                    response["status"] = "failed"
                    response["message"] = execution_result.get("summary", "Izvršenje nije uspjelo.")
                elif execution_state == "COMPLETED":
                    response["status"] = "completed"
                    response["message"] = execution_result.get("summary", "Izvršenje je završeno.")

                response["read_only"] = False
                response["execution"] = {
                    "execution_id": execution_result.get("execution_id"),
                    "state": execution_state,
                }

                return self._finalize(response)

            # ===================================================
            # STATE-DRIVEN UX (NO EXECUTION)
            # ===================================================
            if state == "DECISION_PENDING":
                response["status"] = "waiting_confirmation"
                response["message"] = "Čekam tvoju potvrdu."
                return self._finalize(response)

            if state == "EXECUTING":
                response["status"] = "executing"
                response["message"] = "Izvršenje je u toku."
                return self._finalize(response)

            if state == "SOP_ACTIVE":
                response["status"] = "sop_active"
                response["message"] = "SOP je aktivan."
                return self._finalize(response)

            if state == "SOP_LIST":
                response["status"] = "sop_list"
                response["message"] = "Dostupni SOP-ovi."
                return self._finalize(response)

            # ===================================================
            # DEFAULT (IDLE)
            # ===================================================
            response["status"] = "idle"
            response["message"] = "Spreman sam."
            return self._finalize(response)

        except Exception:
            logger.exception("Response formatting failed")

            return {
                "contract_version": self.CONTRACT_VERSION,
                "status": "failed",
                "message": "Došlo je do greške u odgovoru.",
                "read_only": True,
            }

    # ============================================================
    # FINAL CONTRACT GUARD
    # ============================================================
    def _finalize(self, response: Dict[str, Any]) -> Dict[str, Any]:
        status = response.get("status")

        if status not in ALLOWED_STATUSES:
            logger.critical("Illegal response status: %s", status)
            response["status"] = "failed"
            response["message"] = "Nevažeći status odgovora."

        return response
