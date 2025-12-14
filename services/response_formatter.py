from typing import Any, Dict, Optional
import logging

logger = logging.getLogger(__name__)

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
    ResponseFormatter — SINGLE RESPONSE AUTHORITY

    FAZA 10.4 — API HARDENING

    RULES:
    - response contract NEVER breaks
    - no raw exceptions to client
    - frontend renders, never interprets
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

            # --------------------------------------------------
            # CRITICAL AWARENESS OVERRIDE
            # --------------------------------------------------
            if awareness_level == "critical" and not execution_result:
                response["status"] = "failed"
                response["message"] = "Došlo je do interne greške u sistemu."
                return self._finalize(response)

            # --------------------------------------------------
            # EXECUTION RESULT
            # --------------------------------------------------
            if execution_result and isinstance(execution_result, dict) and "success" in execution_result:
                results = execution_result.get("results", [])
                started_at = execution_result.get("started_at")
                finished_at = execution_result.get("finished_at")

                task_count = len(results)
                task_success = len([r for r in results if r.get("status") == "DONE"])
                task_failed = task_count - task_success

                response["execution_summary"] = {
                    "execution_state": execution_result.get("execution_state"),
                    "task_count": task_count,
                    "task_success": task_success,
                    "task_failed": task_failed,
                    "summary": execution_result.get("summary"),
                }

                if execution_result.get("success") is True:
                    response["status"] = "completed"
                    response["message"] = "Izvršenje je uspješno završeno."
                else:
                    response["status"] = "failed"
                    response["message"] = "Izvršenje nije uspješno završeno."

                return self._finalize(response)

            # --------------------------------------------------
            # STATE-DRIVEN RESPONSES
            # --------------------------------------------------
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

            # --------------------------------------------------
            # DEFAULT
            # --------------------------------------------------
            response["status"] = "idle"
            response["message"] = "Spreman sam."
            return self._finalize(response)

        except Exception as e:
            # HARD FAIL-SAFE RESPONSE
            logger.exception("Response formatting failed")

            return {
                "contract_version": self.CONTRACT_VERSION,
                "status": "failed",
                "message": "Došlo je do greške u odgovoru.",
                "read_only": True,
            }

    # ============================================================
    # FINAL CONTRACT GUARD (FAIL-SAFE)
    # ============================================================
    def _finalize(self, response: Dict[str, Any]) -> Dict[str, Any]:
        status = response.get("status")

        if status not in ALLOWED_STATUSES:
            logger.critical("Illegal response status: %s", status)
            response["status"] = "failed"
            response["message"] = "Nevažeći status odgovora."

        response["read_only"] = True
        return response
