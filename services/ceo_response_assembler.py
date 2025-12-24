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

Napomena:
- Ovaj assembler je "Truthful UX" sloj.
- Za CEO Advisory endpoint (READ-only), očekujemo da advisory sadržaj bude stabilan:
  summary/questions/plan/options/proposed_commands/trace
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional


def _as_list_of_str(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [x for x in value if isinstance(x, str) and x.strip()]
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return []
        if "\n" in s:
            return [ln.strip() for ln in s.splitlines() if ln.strip()]
        return [s]
    return []


def _as_dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


class CEOResponseAssembler:
    """
    Final UX response builder (Truthful UX).
    """

    CONTRACT_VERSION = "1.2"

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

        Pravila:
        - READ-only advisory je uvijek read_only=True
        - Ako postoji execution ili approval snapshot, jasno označi read_only=False za taj blok
        - Ne interpretira rezultate (ne dodaje "odluke"), samo mapira stanje.
        """

        response: Dict[str, Any] = {
            "contract_version": self.CONTRACT_VERSION,
            "request_id": request_id,
            "timestamp": datetime.utcnow().isoformat(),
            "intent": intent,
            "confidence": confidence,
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
        # Stabilizovano za CEO Advisory endpoint: summary/questions/plan/options/proposed_commands/trace
        # -----------------------------------------------------
        if advisory:
            adv = _as_dict(advisory)
            response["advisory"] = {
                "summary": adv.get("summary")
                if isinstance(adv.get("summary"), str)
                else "\n".join(_as_list_of_str(adv.get("summary"))),
                "questions": _as_list_of_str(adv.get("questions")),
                "plan": _as_list_of_str(adv.get("plan")),
                "options": _as_list_of_str(adv.get("options")),
                "proposed_commands": adv.get("proposed_commands")
                if isinstance(adv.get("proposed_commands"), list)
                else [],
                "trace": _as_dict(adv.get("trace")),
                "read_only": True,
            }
            ux_blocks += 1

        # -----------------------------------------------------
        # EXECUTION RESULT (RESULT ONLY — NO INTERPRETATION)
        # -----------------------------------------------------
        if execution_result:
            ex = _as_dict(execution_result)
            response["execution"] = {
                "state": ex.get("execution_state"),
                "summary": ex.get("reason") or ex.get("summary"),
                "execution_id": ex.get("execution_id"),
                "read_only": False,
            }
            ux_blocks += 1

        # -----------------------------------------------------
        # WORKFLOW VISUALIZATION (READ ONLY)
        # -----------------------------------------------------
        if workflow_snapshot:
            wf = _as_dict(workflow_snapshot)
            response["workflow"] = {
                "workflow_id": wf.get("workflow_id"),
                "state": wf.get("state"),
                "current_step": wf.get("current_step"),
                "read_only": True,
            }
            ux_blocks += 1

        # -----------------------------------------------------
        # APPROVAL UX (EXPLICIT HUMAN ACTION REQUIRED)
        # -----------------------------------------------------
        if approval_snapshot:
            ap = _as_dict(approval_snapshot)
            fully = bool(ap.get("fully_approved"))
            response["approval"] = {
                "approval_id": ap.get("approval_id"),
                "required_levels": ap.get("required_levels"),
                "approved_levels": ap.get("approved_levels"),
                "next_required_level": ap.get("next_required_level"),
                "fully_approved": fully,
                "action_required": not fully,
                "read_only": False,
            }
            ux_blocks += 1

        # -----------------------------------------------------
        # FAILURE SNAPSHOT (READ ONLY)
        # -----------------------------------------------------
        if failure_snapshot:
            fs = _as_dict(failure_snapshot)
            response["failure"] = {
                "category": fs.get("category"),
                "error": fs.get("error"),
                "recovery_options": fs.get("recovery_options"),
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
