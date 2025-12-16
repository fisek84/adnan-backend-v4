# services/response_formatter.py

from typing import Any, Dict, Optional
import logging

logger = logging.getLogger(__name__)

# ============================================================
# RESPONSE CONTRACT (V2.1 — UX POLISH, TRUTHFUL)
# ============================================================

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
    "advisory",   # savjet / analiza (READ-only)
    "execution",  # rezultat izvršenja
    "blocked",    # eksplicitno blokirano
    "error",      # sistemska greška
}


class ResponseFormatter:
    """
    ResponseFormatter — SINGLE RESPONSE AUTHORITY (UX TRUTH LAYER)

    Kanon:
    - formatira UX odgovor
    - NE izvršava
    - NE piše stanje
    - jasno razdvaja: SAVJET ≠ AKCIJA ≠ BLOKADA
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
                logger.error("Illegal awareness level: %s", awareness_level)
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

            # ===================================================
            # ADVISORY (REASONING OUTPUT — READ-ONLY)
            # ===================================================
            if advisory:
                response.update(
                    {
                        "type": "advisory",
                        "status": "advisory",
                        "message": advisory.get("summary", "Savjetodavna analiza."),
                        "advisory": advisory,
                        "read_only": True,
                    }
                )
                return self._finalize(response)

            # ===================================================
            # EXECUTION RESULT (WRITE PATH — GOVERNED)
            # ===================================================
            if execution_result and "execution_state" in execution_result:
                execution_state = execution_result.get("execution_state")

                if execution_state == "BLOCKED":
                    response.update(
                        {
                            "type": "blocked",
                            "status": "blocked",
                            "message": execution_result.get(
                                "reason", "Akcija je blokirana pravilima."
                            ),
                            "read_only": True,
                        }
                    )
                elif execution_state == "FAILED":
                    response.update(
                        {
                            "type": "execution",
                            "status": "failed",
                            "message": execution_result.get(
                                "summary", "Izvršenje nije uspjelo."
                            ),
                            "read_only": False,
                        }
                    )
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

                response["execution"] = {
                    "execution_id": execution_result.get("execution_id"),
                    "state": execution_state,
                }

                if "response" in execution_result:
                    response["snapshot"] = execution_result.get("response")

                return self._finalize(response)

            # ===================================================
            # STATE-DRIVEN UX (NO EXECUTION)
            # ===================================================
            if state == "DECISION_PENDING":
                response.update(
                    {
                        "status": "waiting_confirmation",
                        "message": "Čekam tvoju potvrdu. Nema izvršenja bez odobrenja.",
                    }
                )
                return self._finalize(response)

            if state == "EXECUTING":
                response.update(
                    {
                        "status": "executing",
                        "message": "Izvršenje je u toku (praćenje).",
                        "type": "execution",
                        "read_only": False,
                    }
                )
                return self._finalize(response)

            if state == "SOP_ACTIVE":
                response.update(
                    {
                        "status": "sop_active",
                        "message": "SOP je aktivan.",
                    }
                )
                return self._finalize(response)

            if state == "SOP_LIST":
                response.update(
                    {
                        "status": "sop_list",
                        "message": "Dostupni SOP-ovi.",
                    }
                )
                return self._finalize(response)

            # ===================================================
            # DEFAULT (IDLE)
            # ===================================================
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
                "message": "Došlo je do greške u formiranju odgovora.",
                "read_only": True,
            }

    # ============================================================
    # FINAL CONTRACT GUARD
    # ============================================================
    def _finalize(self, response: Dict[str, Any]) -> Dict[str, Any]:
        status = response.get("status")
        rtype = response.get("type")

        if status not in ALLOWED_STATUSES:
            logger.critical("Illegal response status: %s", status)
            response.update(
                {
                    "type": "error",
                    "status": "failed",
                    "message": "Nevažeći status odgovora.",
                    "read_only": True,
                }
            )

        if rtype not in ALLOWED_RESPONSE_TYPES:
            logger.critical("Illegal response type: %s", rtype)
            response.update(
                {
                    "type": "error",
                    "status": "failed",
                    "message": "Nevažeći tip odgovora.",
                    "read_only": True,
                }
            )

        return response
