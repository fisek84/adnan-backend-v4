from typing import Any, Dict, Optional
from datetime import datetime
import copy


class AwarenessService:
    """
    Awareness Service — V1.1 AWARENESS CONTRACT (LOCKED)

    RULES:
    - READ-ONLY
    - NO decisions
    - NO execution
    - NO CSI mutation
    - awareness_level DERIVED ONLY from CSI.state
    """

    CONTRACT_VERSION = "1.1"

    def build_snapshot(
        self,
        *,
        command: Any,
        csi_state: Dict[str, Any],
        decision: Optional[Dict[str, Any]] = None,
        execution_result: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:

        safe_csi_state = copy.deepcopy(csi_state)
        safe_decision = copy.deepcopy(decision)
        safe_execution = copy.deepcopy(execution_result)

        snapshot: Dict[str, Any] = {
            "contract_version": self.CONTRACT_VERSION,
            "request_id": getattr(command, "request_id", None) if command else None,
            "timestamp": datetime.utcnow().isoformat(),
            "awareness_level": self._awareness_level(safe_csi_state),
            "where_are_we": self._describe_state(safe_csi_state),
            "what_we_know": self._extract_known_facts(command, safe_csi_state),
            "what_is_happening": self._describe_activity(
                safe_csi_state, safe_execution
            ),
            "next_expected_step": self._next_step_hint(
                safe_csi_state, safe_execution
            ),
        }

        return snapshot

    # =========================================================
    # CORE AWARENESS LOGIC (CSI → UX)
    # =========================================================

    def _awareness_level(self, csi_state: Dict[str, Any]) -> str:
        state = csi_state.get("state")

        if state == "FAILED":
            return "critical"
        if state in {"DECISION_PENDING", "EXECUTING"}:
            return "active"
        return "idle"

    # =========================================================
    # DESCRIPTORS (NON-AUTHORITATIVE)
    # =========================================================

    def _describe_state(self, csi_state: Dict[str, Any]) -> str:
        state = csi_state.get("state", "IDLE")

        if state == "DECISION_PENDING":
            return "Čekam tvoju potvrdu."
        if state == "EXECUTING":
            return "Izvršavam zadatak."
        if state == "SOP_ACTIVE":
            return "Aktivan je SOP."
        if state == "SOP_LIST":
            return "Biramo SOP."
        if state == "COMPLETED":
            return "Zadatak je završen."
        if state == "FAILED":
            return "Došlo je do greške."

        return "Spreman sam."

    def _extract_known_facts(
        self, command: Any, csi_state: Dict[str, Any]
    ) -> Dict[str, Any]:
        facts: Dict[str, Any] = {}

        if csi_state.get("active_sop_id"):
            facts["active_sop"] = csi_state.get("active_sop_id")

        if csi_state.get("pending_decision"):
            facts["pending_decision"] = csi_state.get("pending_decision")

        return facts

    def _describe_activity(
        self,
        csi_state: Dict[str, Any],
        execution_result: Optional[Dict[str, Any]],
    ) -> str:
        if execution_result is not None:
            return (
                "Akcija je uspješno izvršena."
                if execution_result.get("success")
                else "Akcija nije uspješno izvršena."
            )

        if csi_state.get("state") == "EXECUTING":
            return "Radim na zadatku."

        if csi_state.get("state") == "DECISION_PENDING":
            return "Čekam potvrdu."

        return "Nema aktivnih operacija."

    def _next_step_hint(
        self,
        csi_state: Dict[str, Any],
        execution_result: Optional[Dict[str, Any]],
    ) -> str:
        state = csi_state.get("state")

        if state == "DECISION_PENDING":
            return "Potrebna je tvoja potvrda."
        if state == "EXECUTING":
            return "Sačekaj završetak."
        if execution_result is not None:
            return "Spreman sam za sljedeći zadatak."

        return "Spreman sam za novu naredbu."
