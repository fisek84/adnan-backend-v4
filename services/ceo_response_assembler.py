# services/ceo_response_assembler.py

"""
CEO RESPONSE ASSEMBLER — CANONICAL (FAZA 12 / UX POLISH)

Uloga:
- JEDINO mjesto gdje se formira CEO / UX odgovor
- istinito mapira sistemsku realnost u UX
- jasno razdvaja: SAVJET ≠ AKCIJA ≠ BLOKADA
- NE donosi odluke
- NE izvršava
- NE skriva governance
"""

from typing import Dict, Any, Optional
from datetime import datetime


class CEOResponseAssembler:
    """
    Final UX response builder (Truthful UX).
    """

    CONTRACT_VERSION = "1.1"

    # =========================================================
    # MAIN ENTRYPOINT
    # =========================================================
    def assemble(
        self,
        *,
        request_id: Optional[str],
        intent: Optional[str],
        confidence: Optional[float],
        system_state: Optional[Dict[str, Any]] = None,
        advisory: Optional[Dict[str, Any]] = None,
        execution_result: Optional[Dict[str, Any]] = None,
        workflow_snapshot: Optional[Dict[str, Any]] = None,
        approval_snapshot: Optional[Dict[str, Any]] = None,
        failure_snapshot: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Sastavlja JEDINSTVEN, KANONSKI CEO UX odgovor.
        """

        response: Dict[str, Any] = {
            "contract_version": self.CONTRACT_VERSION,
            "request_id": request_id,
            "timestamp": datetime.utcnow().isoformat(),
            "intent": intent,
            "confidence": confidence,
            "read_only": True,
        }

        ux_blocks = 0

        # -----------------------------------------------------
        # SYSTEM STATE (READ-ONLY SNAPSHOT)
        # -----------------------------------------------------
        if system_state:
            response["system"] = {
                "snapshot": system_state,
                "read_only": True,
            }
            ux_blocks += 1

        # -----------------------------------------------------
        # ADVISORY (REASONING OUTPUT — READ ONLY)
        # -----------------------------------------------------
        if advisory:
            response["advisory"] = {
                "summary": advisory.get("summary"),
                "options": advisory.get("options"),
                "risks": advisory.get("risks"),
                "read_only": True,
            }
            ux_blocks += 1

        # -----------------------------------------------------
        # EXECUTION RESULT (RESULT ONLY — NO INTERPRETATION)
        # -----------------------------------------------------
        if execution_result:
            response["execution"] = {
                "state": execution_result.get("execution_state"),
                "summary": execution_result.get("reason")
                or execution_result.get("summary"),
                "execution_id": execution_result.get("execution_id"),
                "read_only": False,
            }
            ux_blocks += 1

        # -----------------------------------------------------
        # WORKFLOW VISUALIZATION (READ ONLY)
        # -----------------------------------------------------
        if workflow_snapshot:
            response["workflow"] = {
                "workflow_id": workflow_snapshot.get("workflow_id"),
                "state": workflow_snapshot.get("state"),
                "current_step": workflow_snapshot.get("current_step"),
                "read_only": True,
            }
            ux_blocks += 1

        # -----------------------------------------------------
        # APPROVAL UX (EXPLICIT HUMAN ACTION REQUIRED)
        # -----------------------------------------------------
        if approval_snapshot:
            response["approval"] = {
                "approval_id": approval_snapshot.get("approval_id"),
                "required_levels": approval_snapshot.get("required_levels"),
                "approved_levels": approval_snapshot.get("approved_levels"),
                "next_required_level": approval_snapshot.get("next_required_level"),
                "fully_approved": approval_snapshot.get("fully_approved"),
                "action_required": not approval_snapshot.get("fully_approved"),
                "read_only": False,
            }
            ux_blocks += 1

        # -----------------------------------------------------
        # FAILURE SNAPSHOT (READ ONLY)
        # -----------------------------------------------------
        if failure_snapshot:
            response["failure"] = {
                "category": failure_snapshot.get("category"),
                "error": failure_snapshot.get("error"),
                "recovery_options": failure_snapshot.get("recovery_options"),
                "read_only": True,
            }
            ux_blocks += 1

        # -----------------------------------------------------
        # DEFAULT UX MESSAGE (TRUTHFUL IDLE)
        # -----------------------------------------------------
        if ux_blocks == 0:
            response["message"] = {
                "type": "system_info",
                "text": (
                    "Sistem je aktivan. "
                    "Nema savjeta, nema izvršenja i nema blokada za ovaj zahtjev."
                ),
                "read_only": True,
            }

        return response
