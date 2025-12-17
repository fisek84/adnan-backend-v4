from typing import Any, Dict, Optional
import logging

logger = logging.getLogger(__name__)

ALLOWED_STATUSES = {
    "idle",
    "advisory",
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

ALLOWED_RESPONSE_TYPES = {
    "advisory",
    "execution",
    "blocked",
    "error",
}


class ResponseFormatter:
    """
    ResponseFormatter — SINGLE RESPONSE AUTHORITY (UX TRUTH LAYER)
    """

    CONTRACT_VERSION = "2.1"

    def format(
        self,
        intent: str,
        confidence: float,
        csi_state: Dict[str, Any],
        *,
        execution_result: Optional[Dict[str, Any]] = None,
        advisory: Optional[Dict[str, Any]] = None,
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
                awareness_level = "idle"

            response: Dict[str, Any] = {
                "contract_version": self.CONTRACT_VERSION,
                "request_id": request_id,
                "intent": intent,
                "confidence": confidence,
                "state": state,
                "awareness_level": awareness_level,
                "type": "advisory",
                "status": "idle",
                "message": "",
                "read_only": True,
            }

            # ================= ADVISORY =================
            if advisory:
                response.update(
                    {
                        "type": "advisory",
                        "status": "advisory",
                        "message": advisory.get("summary"),
                        "advisory": advisory,
                        "read_only": True,
                    }
                )
                return self._finalize(response)

            # ================= EXECUTION =================
            if execution_result and "execution_state" in execution_result:
                execution_state = execution_result.get("execution_state")

                if execution_state == "FAILED":
                    response.update(
                        {
                            "type": "execution",
                            "status": "failed",
                            "message": execution_result
                                .get("failure", {})
                                .get("reason", "Izvršenje nije uspjelo."),
                            "read_only": False,
                        }
                    )

                    # 🔑 FIX — PROPAGATE FAILURE SNAPSHOT
                    response["failure"] = execution_result.get("failure")

                elif execution_state == "COMPLETED":
                    response.update(
                        {
                            "type": "execution",
                            "status": "completed",
                            "message": execution_result.get(
                                "summary", "Izvršenje je završeno."
                            ),
                            "read_only": False,
                        }
                    )

                elif execution_state == "BLOCKED":
                    response.update(
                        {
                            "type": "blocked",
                            "status": "blocked",
                            "message": execution_result.get(
                                "reason", "Akcija je blokirana."
                            ),
                            "read_only": True,
                        }
                    )

                response["execution"] = {
                    "execution_id": execution_result.get("execution_id"),
                    "state": execution_state,
                }

                return self._finalize(response)

            # ================= DEFAULT =================
            response.update(
                {
                    "status": "idle",
                    "message": "Spreman sam. Bez aktivnih akcija.",
                }
            )
            return self._finalize(response)

        except Exception:
            logger.exception("Response formatting failed")
            return {
                "contract_version": self.CONTRACT_VERSION,
                "type": "error",
                "status": "failed",
                "message": "Greška u formiranju odgovora.",
                "read_only": True,
            }

    def _finalize(self, response: Dict[str, Any]) -> Dict[str, Any]:
        return response
