"""
CEO RESPONSE ASSEMBLER — CANONICAL (FAZA 5)

Uloga:
- JEDINO mjesto gdje se formira UX / CEO odgovor
- prevodi interno stanje sistema u CEO-friendly snapshot
- NE donosi odluke
- NE izvršava
- NE tumači (UI samo renderuje)
- strogo poštuje response contract

CEOResponseAssembler ≠ Execution
CEOResponseAssembler ≠ Governance
CEOResponseAssembler ≠ Workflow
"""

from typing import Dict, Any, Optional
from datetime import datetime


class CEOResponseAssembler:
    """
    Final UX response builder.
    """

    CONTRACT_VERSION = "1.0"

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
        execution_result: Optional[Dict[str, Any]] = None,
        workflow_snapshot: Optional[Dict[str, Any]] = None,
        approval_snapshot: Optional[Dict[str, Any]] = None,
        failure_snapshot: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Sastavlja JEDINSTVEN CEO UX odgovor.
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
        # EXECUTION RESULT (SINGLE COMMAND)
        # -----------------------------------------------------
        if execution_result:
            response["execution"] = {
                "state": execution_result.get("execution_state"),
                "summary": execution_result.get("reason")
                or execution_result.get("summary"),
                "details": {
                    k: v
                    for k, v in execution_result.items()
                    if k
                    not in {
                        "execution_state",
                        "reason",
                        "summary",
                    }
                },
                "read_only": True,
            }
            ux_blocks += 1

            # ---------------------------------------------
            # UX PROMPT — INBOX → DELEGATION PREVIEW
            # ---------------------------------------------
            if execution_result.get("action") == "system_inbox_delegation_preview":
                count = execution_result.get("response", {}).get("count", 0)

                response["message"] = {
                    "type": "delegation_prompt",
                    "text": (
                        f"Vidim {count} stavki u inboxu koje mogu biti delegirane. "
                        "Želiš li da delegiram neku od njih?"
                    ),
                    "read_only": True,
                }
                ux_blocks += 1

        # -----------------------------------------------------
        # WORKFLOW VISUALIZATION
        # -----------------------------------------------------
        if workflow_snapshot:
            response["workflow"] = {
                "workflow_id": workflow_snapshot.get("workflow_id"),
                "state": workflow_snapshot.get("state"),
                "current_step": workflow_snapshot.get("current_step"),
                "failure_reason": workflow_snapshot.get("failure_reason"),
                "read_only": True,
            }
            ux_blocks += 1

        # -----------------------------------------------------
        # APPROVAL UX (WRITE CONFIRMATION ONLY)
        # -----------------------------------------------------
        if approval_snapshot:
            response["approval"] = {
                "approval_id": approval_snapshot.get("approval_id"),
                "required_levels": approval_snapshot.get("required_levels"),
                "approved_levels": approval_snapshot.get("approved_levels"),
                "next_required_level": approval_snapshot.get("next_required_level"),
                "fully_approved": approval_snapshot.get("fully_approved"),
                "read_only": False,
            }
            ux_blocks += 1

        # -----------------------------------------------------
        # FAILURE SNAPSHOT
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
        # DEFAULT READ-ONLY UX MESSAGE (MANDATORY)
        # -----------------------------------------------------
        if ux_blocks == 0:
            response["message"] = {
                "type": "system_info",
                "text": (
                    "Ja sam Adnan.AI. Sistem je aktivan i u read-only režimu. "
                    "Ovaj zahtjev ne sadrži izvršivu naredbu."
                ),
                "read_only": True,
            }

        return response
